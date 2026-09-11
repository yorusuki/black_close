"""線上拆分模式（方案 B）用的裝置代理。

流程：定期（poll_interval_seconds）打伺服器的 /api/devices/<id>/layout-data，拿到
「已選好 layout + 已解析好 http 資料」的 JSON；接著用更短的頻率（tick_seconds，
預設 1 秒）在本機反覆呼叫 server.render.compositor 的 render_from_elements()——
真正的合成畫面、dirty-box 比對、整幅/局部刷新節流全部在這裡、在本機算。

這樣設計是因為 layout-data 裡本地型別（manual/battery/time_until/time_progress）
的資料完全沒有被伺服器端解析、快取，而是留到 render_from_elements() 呼叫模組的
render() 時才即時算——倒數計時/生存進度條/吉祥物動畫這類「本地就能算」的內容才能
保持即時感，不受 poll_interval_seconds 限制。battery 型別更是只能在樹莓派本機
正確運作（讀本機的 data/runtime/battery.json），放到伺服器端解析一定讀不到檔案。

Pi 上跑這支的前提是 config.yaml 的 render_endpoint 設成伺服器網址（不是 "local"）。
all-in-one 模式（render_endpoint: local）請用 server/scheduler.py，不要跑這支。

依賴：除了 requests + pillow + 硬體驅動需要的 spidev/gpiozero 之外，這支現在也會
匯入 server.render.compositor / server.modules.*（拿 render_from_elements() 跟各
模組的 render() 邏輯）；這些模組本身只依賴 PIL/requests/pyyaml，不會連帶匯入
flask，所以不需要在 Pi 上安裝 flask 也能跑（只要不要去跑 server/app.py 就好）。
執行時記得整個 repo（server/ 跟 device_agent/ 要在同一份 checkout 底下，並從 repo
根目錄用 `python -m device_agent.agent` 啟動，才能正確 import server 套件）。
"""
from __future__ import annotations

import datetime
import logging
import time

import requests

from . import config as agent_config
from .drivers import build_driver

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("device_agent.agent")


def fetch_device_profile(base_url: str, device_id: str, headers: dict) -> dict:
    resp = requests.get(f"{base_url}/api/devices/{device_id}", headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()


def fetch_layout_data(base_url: str, device_id: str, headers: dict) -> dict:
    resp = requests.get(f"{base_url}/api/devices/{device_id}/layout-data", headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


def sync_assets(base_url: str, headers: dict, resolved: dict) -> None:
    """掃一遍這輪 layout-data 裡用到的 image 模組，本機沒有對應檔名的素材就下載。

    版本判斷完全靠檔名裡的內容 hash（見 server/assets.py），所以這裡只要「檔名存在
    就跳過、不存在才下載」，不用另外維護版本狀態。單一素材下載失敗不影響其他素材/
    其他模組，下一輪 poll 自動重試。"""
    assets_dir = agent_config.BASE_DIR / "data" / "assets"
    for el in resolved.get("elements", []):
        if el.get("module_id") != "image":
            continue
        cfg = el.get("config") or {}
        data = el.get("data") or {}
        asset_id = cfg.get("asset_id")
        filename = data.get("filename")
        if not asset_id or not filename:
            continue

        local_path = assets_dir / filename
        if local_path.exists():
            continue

        assets_dir.mkdir(parents=True, exist_ok=True)
        try:
            resp = requests.get(f"{base_url}/api/assets/{asset_id}", headers=headers, timeout=30)
            resp.raise_for_status()
            tmp_path = local_path.with_suffix(local_path.suffix + ".tmp")
            tmp_path.write_bytes(resp.content)
            tmp_path.replace(local_path)
            log.info("素材已下載：%s", filename)
        except Exception:
            log.exception("素材下載失敗，下一輪 poll 自動重試：%s", filename)


def run():
    from server.render.compositor import render_from_elements  # 延後匯入：保持模組頂端 import 最小

    cfg = agent_config.load_config()
    base_url = cfg["render_endpoint"]
    if base_url == "local":
        raise SystemExit(
            "config.yaml 的 render_endpoint 是 'local'，代表你要用 all-in-one 模式，"
            "請改跑 `python -m server.scheduler --device <id>`，不是這支 agent.py。"
        )

    device_id = cfg["device_id"]
    headers = {}
    if cfg.get("api_token"):
        headers["Authorization"] = f"Bearer {cfg['api_token']}"

    profile = fetch_device_profile(base_url, device_id, headers)
    driver = build_driver(profile)
    poll_interval = cfg.get("poll_interval_seconds", 30)
    tick_seconds = cfg.get("tick_seconds", 1)

    log.info(
        "agent 啟動（split 模式，本機渲染）：server=%s device=%s poll=%ss tick=%ss",
        base_url, device_id, poll_interval, tick_seconds,
    )

    resolved = None
    last_poll = 0.0

    while True:
        now_ts = time.time()
        if resolved is None or (now_ts - last_poll) >= poll_interval:
            try:
                resolved = fetch_layout_data(base_url, device_id, headers)
                last_poll = now_ts
                sync_assets(base_url, headers, resolved)
            except Exception:
                log.exception("layout-data 輪詢失敗，沿用上一份資料繼續本機渲染")

        if resolved is not None:
            try:
                image, meta = render_from_elements(resolved, datetime.datetime.now())
                if meta["refresh_mode"] != "none":
                    driver.show(image, mode=meta["refresh_mode"], dirty_boxes=meta["dirty_boxes"])
                    log.info("刷新完成：mode=%s dirty=%d", meta["refresh_mode"], len(meta["dirty_boxes"]))
            except Exception:
                log.exception("這輪本機渲染/刷新失敗，等下一個 tick 重試")

        time.sleep(tick_seconds)


if __name__ == "__main__":
    run()

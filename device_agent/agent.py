"""Pi agent: it knows only a Server URL and its own device token."""
from __future__ import annotations

import datetime
import json
import logging
import os
import time

import requests

from . import config as agent_config
from .drivers import build_driver

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("device_agent.agent")
LAYOUT_CACHE_PATH = agent_config.BASE_DIR / "data" / "runtime" / "last_device_layout.json"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def fetch_layout(server_url: str, headers: dict) -> dict:
    response = requests.get(f"{server_url}/api/v1/device/layout", headers=headers, timeout=15)
    response.raise_for_status()
    return response.json()


def _valid_cached_layout(value: object) -> bool:
    """只接受 agent 可安全拿去本機渲染的最小 layout 結構。"""
    if not isinstance(value, dict) or not isinstance(value.get("device_id"), str):
        return False
    profile = value.get("profile")
    resolution = profile.get("resolution") if isinstance(profile, dict) else None
    return (
        isinstance(resolution, list)
        and len(resolution) == 2
        and all(isinstance(item, int) and item > 0 for item in resolution)
        and isinstance(value.get("elements"), list)
    )


def load_layout_cache() -> dict | None:
    """載入最後一次 API 成功回應，讓 Pi 重啟後仍能在離線狀態本機刷新。"""
    try:
        value = json.loads(LAYOUT_CACHE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        log.warning("離線版面快取無法讀取，會等待 Server 提供新版本")
        return None
    if not _valid_cached_layout(value):
        log.warning("離線版面快取格式無效，會等待 Server 提供新版本")
        return None
    return value


def save_layout_cache(resolved: dict) -> None:
    """以原子替換保存非機密的已解析版面，檔案僅限 Pi 帳號讀寫。"""
    if not _valid_cached_layout(resolved):
        raise ValueError("Server 回傳的 layout 格式不完整")
    LAYOUT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = LAYOUT_CACHE_PATH.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(resolved, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(LAYOUT_CACHE_PATH)
    finally:
        # replace() 成功後暫存檔已不存在；失敗時盡力清理，不影響既有有效快取。
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def report_telemetry(server_url: str, headers: dict, payload: dict) -> None:
    try:
        requests.post(f"{server_url}/api/v1/device/telemetry", headers=headers, json=payload, timeout=10).raise_for_status()
    except requests.RequestException:
        # Telemetry is advisory: it must not stop rendering if a remote server is unavailable.
        log.warning("telemetry 上傳失敗，會在下個輪詢週期重試")


def sync_assets(server_url: str, headers: dict, resolved: dict) -> None:
    """Only request assets referenced by this device's layout through the v1 token boundary."""
    assets_dir = agent_config.BASE_DIR / "data" / "assets"
    for element in resolved.get("elements", []):
        if element.get("module_id") != "image":
            continue
        asset_id = (element.get("config") or {}).get("asset_id")
        filename = (element.get("data") or {}).get("filename")
        if not asset_id or not filename or (assets_dir / filename).is_file():
            continue
        assets_dir.mkdir(parents=True, exist_ok=True)
        try:
            response = requests.get(f"{server_url}/api/v1/device/assets/{asset_id}", headers=headers, timeout=30)
            response.raise_for_status()
            destination = assets_dir / filename
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            temporary.write_bytes(response.content)
            temporary.replace(destination)
            log.info("素材已同步：%s", filename)
        except requests.RequestException:
            log.exception("素材同步失敗，下一輪會重試：%s", asset_id)


def run() -> None:
    from server.render.compositor import render_from_elements

    cfg = agent_config.load_config()
    server_url, headers = cfg["server_url"], _headers(cfg["device_token"])
    poll_interval, tick_seconds = cfg["poll_interval_seconds"], cfg["tick_seconds"]
    resolved = load_layout_cache()
    driver = None
    last_poll = 0.0
    last_mode = "none"
    log.info("agent 啟動：server=%s，採 device token 驗證", server_url)
    if resolved is not None:
        try:
            driver = build_driver(resolved["profile"])
            log.info("已載入最後有效版面；Server 不可達時仍可依本機刷新政策運作")
        except (ValueError, KeyError):
            log.exception("離線版面設定無法建立硬體驅動，將等待 Server 提供新版本")
            resolved = None

    while True:
        now = time.monotonic()
        if resolved is None or now - last_poll >= poll_interval:
            try:
                fresh_layout = fetch_layout(server_url, headers)
                if not _valid_cached_layout(fresh_layout):
                    raise ValueError("Server 回傳的 layout 格式不完整")
                try:
                    save_layout_cache(fresh_layout)
                except OSError:
                    # 儲存空間或檔案權限問題不能妨礙已驗證的當前版面顯示；記錄後
                    # 下輪會重試保存，既有快取也不會被破壞。
                    log.exception("無法保存離線版面快取，這次仍使用 Server 新版面")
                resolved = fresh_layout
                last_poll = now
                sync_assets(server_url, headers, resolved)
                if driver is None:
                    driver = build_driver(resolved["profile"])
                report_telemetry(server_url, headers, {"status": "online", "agent_version": "v1", "refresh_mode": last_mode})
            except (requests.RequestException, ValueError, KeyError):
                log.exception("無法取得 device layout；保留上一份有效畫面")

        if resolved is not None and driver is not None:
            try:
                image, meta = render_from_elements(resolved, datetime.datetime.now())
                last_mode = meta["refresh_mode"]
                if last_mode != "none":
                    driver.show(image, mode=last_mode, dirty_boxes=meta["dirty_boxes"])
                    log.info("刷新完成：mode=%s dirty=%d", last_mode, len(meta["dirty_boxes"]))
            except Exception:
                log.exception("本機渲染／刷新失敗，將於下一個 tick 重試")
        time.sleep(tick_seconds)


if __name__ == "__main__":
    run()

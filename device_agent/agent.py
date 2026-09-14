"""Pi agent: it knows only a Server URL and its own device token."""
from __future__ import annotations

import datetime
import logging
import time

import requests

from . import config as agent_config
from .drivers import build_driver

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("device_agent.agent")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def fetch_layout(server_url: str, headers: dict) -> dict:
    response = requests.get(f"{server_url}/api/v1/device/layout", headers=headers, timeout=15)
    response.raise_for_status()
    return response.json()


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
    resolved = None
    driver = None
    last_poll = 0.0
    last_mode = "none"
    log.info("agent 啟動：server=%s，採 device token 驗證", server_url)

    while True:
        now = time.monotonic()
        if resolved is None or now - last_poll >= poll_interval:
            try:
                resolved = fetch_layout(server_url, headers)
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

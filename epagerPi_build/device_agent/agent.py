"""線上拆分模式（方案 B）用的裝置代理：只做「輪詢拿圖 → 推到螢幕」，不做任何合成/排版邏輯。

Pi 上跑這支的前提是 config.yaml 的 render_endpoint 設成伺服器網址（不是 "local"）。
all-in-one 模式（render_endpoint: local）請用 server/scheduler.py，不要跑這支。

依賴刻意保持最小：requests + pillow + 硬體驅動需要的 spidev/gpiozero，
不需要 flask、numpy 之外的東西，符合「Pi 上越省資源越好」。
"""
from __future__ import annotations

import io
import json
import logging
import time

import requests
from PIL import Image

from . import config as agent_config
from .drivers import build_driver

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("device_agent.agent")


def fetch_device_profile(base_url: str, device_id: str, headers: dict) -> dict:
    resp = requests.get(f"{base_url}/api/devices/{device_id}", headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()


def fetch_frame(base_url: str, device_id: str, headers: dict):
    resp = requests.get(f"{base_url}/api/devices/{device_id}/frame.png", headers=headers, timeout=15)
    resp.raise_for_status()
    image = Image.open(io.BytesIO(resp.content))
    image.load()
    meta = {
        "refresh_mode": resp.headers.get("X-Refresh-Mode", "full"),
        "dirty_boxes": json.loads(resp.headers.get("X-Dirty-Boxes", "[]")),
    }
    return image, meta


def run():
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

    log.info("agent 啟動（split 模式）：server=%s device=%s poll=%ss", base_url, device_id, poll_interval)

    while True:
        try:
            image, meta = fetch_frame(base_url, device_id, headers)
            if meta["refresh_mode"] != "none":
                driver.show(image, mode=meta["refresh_mode"], dirty_boxes=meta["dirty_boxes"])
                log.info("刷新完成：mode=%s dirty=%d", meta["refresh_mode"], len(meta["dirty_boxes"]))
        except Exception:
            log.exception("這輪輪詢/刷新失敗，等下一輪重試")
        time.sleep(poll_interval)


if __name__ == "__main__":
    run()

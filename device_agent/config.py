"""Pi agent 設定：僅接受 Server URL 與單一 Pi 的 device token。"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
BATTERY_STATE_PATH = BASE_DIR / "data" / "runtime" / "battery.json"


def load_config(path: str | Path | None = None) -> dict:
    path = Path(path or os.environ.get("EPAGERPI_AGENT_CONFIG", BASE_DIR / "device_agent" / "config.yaml"))
    if not path.is_file():
        raise SystemExit(f"找不到 device_agent 設定檔：{path}")
    with path.open(encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle) or {}
    if os.environ.get("EPAGERPI_SERVER_URL"):
        cfg["server_url"] = os.environ["EPAGERPI_SERVER_URL"]
    if os.environ.get("EPAGERPI_DEVICE_TOKEN"):
        cfg["device_token"] = os.environ["EPAGERPI_DEVICE_TOKEN"]
    url, token = cfg.get("server_url"), cfg.get("device_token")
    parsed = urlparse(url) if isinstance(url, str) else None
    if not parsed or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SystemExit("server_url 必須是完整 http(s) Server URL")
    if not isinstance(token, str) or len(token) < 32:
        raise SystemExit("device_token 缺失或格式不正確；請從管理端重新配發")
    return {
        "server_url": url.rstrip("/"), "device_token": token,
        "poll_interval_seconds": max(5, float(cfg.get("poll_interval_seconds", 30))),
        "tick_seconds": max(0.5, float(cfg.get("tick_seconds", 1))),
        "ups": cfg.get("ups", {}),
    }

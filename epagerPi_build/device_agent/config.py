"""device_agent 的設定載入：讀 config.yaml，環境變數可覆蓋常用項目。"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
PREVIEW_PATH = str(BASE_DIR / "data" / "preview" / "{device_id}.png")

# 跟 server/config.py 的 DATA_DIR 算出同一個路徑（兩者的 BASE_DIR 都是 repo 根目錄），
# UPS daemon 把最新電量寫在這裡，「電量顯示」模組（stat_pair + value_source type=battery）
# 直接讀這個檔案，不用另外開一次 I2C 連線去搶匯流排。
BATTERY_STATE_PATH = BASE_DIR / "data" / "runtime" / "battery.json"


def load_config(path: str | Path | None = None) -> dict:
    path = Path(path or os.environ.get("EPAGERPI_AGENT_CONFIG", BASE_DIR / "device_agent" / "config.yaml"))
    if not path.exists():
        raise SystemExit(
            f"找不到 device_agent 設定檔：{path}\n"
            f"請複製 device_agent/config.example.yaml 成 device_agent/config.yaml 並依實際情況修改。"
        )
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    # 環境變數覆蓋（方便 docker/systemd 用環境變數調整，不用改檔案）
    if os.environ.get("EPAGERPI_DEVICE_ID"):
        cfg["device_id"] = os.environ["EPAGERPI_DEVICE_ID"]
    if os.environ.get("EPAGERPI_RENDER_ENDPOINT"):
        cfg["render_endpoint"] = os.environ["EPAGERPI_RENDER_ENDPOINT"]
    if os.environ.get("EPAGERPI_API_TOKEN"):
        cfg["api_token"] = os.environ["EPAGERPI_API_TOKEN"]

    return cfg

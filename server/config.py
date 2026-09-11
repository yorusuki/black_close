"""集中管理環境變數設定。

Pi 本機模式：AUTH_ENABLED=0（預設），不做任何驗證。
線上 Docker 模式：AUTH_ENABLED=1，搭配 AUTH_USER/AUTH_PASS（網頁編輯器用 Basic Auth）
以及 API_TOKEN（裝置代理 / 其他程式呼叫 API 用 Bearer token）。
"""

from __future__ import annotations
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("EPAGERPI_DATA_DIR", BASE_DIR / "data"))

HOST = os.environ.get("EPAGERPI_HOST", "0.0.0.0")
PORT = int(os.environ.get("EPAGERPI_PORT", "8080"))

# 給模組的 http value_source 用：如果 url 是「/api/...」這種相對路徑，就補上這個
# base url 變成完整網址（模組要打自己這台伺服器的其他端點時很方便，例如範例 layout
# 裡「剩餘特休」打 /api/mock/leave-balance）。要接外部 API 就直接填完整網址即可，
# 不受這個設定影響。
SELF_BASE_URL = os.environ.get("EPAGERPI_SELF_BASE_URL", f"http://127.0.0.1:{PORT}")

# ---- 驗證設定（僅線上 Docker 版需要開啟）----
AUTH_ENABLED = os.environ.get("EPAGERPI_AUTH_ENABLED", "0") == "1"
AUTH_USER = os.environ.get("EPAGERPI_AUTH_USER", "admin")
AUTH_PASS = os.environ.get("EPAGERPI_AUTH_PASS", "")
API_TOKEN = os.environ.get("EPAGERPI_API_TOKEN", "")

# ---- 自訂字型 ----
# 指到一個 .ttf/.ttc/.otf 檔案，所有模組共用的 load_font()（modules/drawing.py）
# 會優先用這個字型；找不到檔案或字型本身壞掉會自動退回內建的 Noto Sans CJK 候選
# 清單，不會 crash。目前是全域換字型（所有模組共用同一套），不是每個模組各自選。
FONT_PATH = os.environ.get("EPAGERPI_FONT_PATH", "")

# ---- 排程 / 刷新設定 ----
TICK_SECONDS = float(os.environ.get("EPAGERPI_TICK_SECONDS", "1"))

# ---- 開發預覽 ----
PREVIEW_DIR = DATA_DIR / "preview"

# 跟 device_agent/config.py 的 BATTERY_STATE_PATH 指向同一個檔案（兩邊 BASE_DIR
# 都是 repo 根目錄）：UPS daemon 寫、progress_bar/stat_pair 模組的
# value_source type="battery" 讀，避免重複開 I2C。
BATTERY_STATE_PATH = DATA_DIR / "runtime" / "battery.json"


def ensure_dirs():
    (DATA_DIR / "layouts").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "scenes").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "runtime").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "assets").mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

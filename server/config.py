"""集中管理環境變數設定。

Pi 本機模式：AUTH_ENABLED=0（預設），不做任何驗證。
線上 Docker 模式：AUTH_ENABLED=1，搭配 AUTH_USER/AUTH_PASS（網頁編輯器用 Basic Auth）
以及 API_TOKEN（裝置代理 / 其他程式呼叫 API 用 Bearer token）。
"""

from __future__ import annotations
import os
import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("EPAGERPI_DATA_DIR", BASE_DIR / "data"))
WORKSPACE_DATABASE_URL = os.environ.get("EPAGERPI_DATABASE_URL", str(DATA_DIR / "epagerpi.sqlite3"))
DEVICE_TOKEN_PEPPER = os.environ.get("EPAGERPI_DEVICE_TOKEN_PEPPER", "")
_timezone_name = os.environ.get("EPAGERPI_TIMEZONE", "Asia/Taipei")
try:
    TIMEZONE = ZoneInfo(_timezone_name)
except ZoneInfoNotFoundError:
    # Minimal Windows Python installations may omit IANA zoneinfo. Taiwan has
    # no DST, so the default remains correct without adding a runtime package.
    if _timezone_name != "Asia/Taipei":
        raise RuntimeError(f"找不到時區資料：{_timezone_name}")
    TIMEZONE = datetime.timezone(datetime.timedelta(hours=8), "Asia/Taipei")

HOST = os.environ.get("EPAGERPI_HOST", "0.0.0.0")
PORT = int(os.environ.get("EPAGERPI_PORT", "8080"))

# 給模組的 http value_source 用：如果 url 是「/api/...」這種相對路徑，就補上這個
# base url 變成完整網址（模組要打自己這台伺服器的其他端點時很方便，例如範例 layout
# 裡的內部 API）。要接外部 API 就直接填完整網址即可，
# 不受這個設定影響。
SELF_BASE_URL = os.environ.get("EPAGERPI_SELF_BASE_URL", f"http://127.0.0.1:{PORT}")

# ---- 驗證設定（僅線上 Docker 版需要開啟）----
AUTH_ENABLED = os.environ.get("EPAGERPI_AUTH_ENABLED", "0") == "1"
AUTH_USER = os.environ.get("EPAGERPI_AUTH_USER", "admin")
AUTH_PASS = os.environ.get("EPAGERPI_AUTH_PASS", "")
API_TOKEN = os.environ.get("EPAGERPI_API_TOKEN", "")

# LINE Login is opt-in until its required deployment values are supplied.  Do not
# substitute a development secret here: production startup must validate these.
AUTH_MODE = os.environ.get("EPAGERPI_AUTH_MODE", "legacy")
LINE_CHANNEL_ID = os.environ.get("EPAGERPI_LINE_CHANNEL_ID", "")
LINE_CHANNEL_SECRET = os.environ.get("EPAGERPI_LINE_CHANNEL_SECRET", "")
LINE_REDIRECT_URI = os.environ.get("EPAGERPI_LINE_REDIRECT_URI", "")
LINE_CALLBACK_PATH = os.environ.get("EPAGERPI_LINE_CALLBACK_PATH", "/auth/line/callback")
# LINE Login does not use a webhook. This path is reserved for a future
# Messaging API integration and remains disabled until that integration exists.
LINE_WEBHOOK_PATH = os.environ.get("EPAGERPI_LINE_WEBHOOK_PATH", "/webhooks/line")
SESSION_SECRET = os.environ.get("EPAGERPI_SESSION_SECRET", "")
REGISTRATION_MODE = os.environ.get("EPAGERPI_REGISTRATION_MODE", "closed")
LINE_AUTHORIZE_URL = os.environ.get("EPAGERPI_LINE_AUTHORIZE_URL", "https://access.line.me/oauth2/v2.1/authorize")
LINE_TOKEN_URL = os.environ.get("EPAGERPI_LINE_TOKEN_URL", "https://api.line.me/oauth2/v2.1/token")
LINE_PROFILE_URL = os.environ.get("EPAGERPI_LINE_PROFILE_URL", "https://api.line.me/v2/profile")
SESSION_COOKIE_SECURE = os.environ.get("EPAGERPI_SESSION_COOKIE_SECURE", "1") == "1"
# Temporarily permits the old *read-only* agent routes with EPAGERPI_API_TOKEN.
# It never grants access to workspace management endpoints.
LEGACY_API_COMPAT = os.environ.get("EPAGERPI_LEGACY_API_COMPAT", "1") == "1"

# ---- 自訂字型 ----
# 指到一個 .ttf/.ttc/.otf 檔案，所有模組共用的 load_font()（modules/drawing.py）
# 會優先用這個字型；找不到檔案或字型本身壞掉會自動退回內建的 Noto Sans CJK 候選
# 清單，不會 crash。目前是全域換字型（所有模組共用同一套），不是每個模組各自選。
FONT_PATH = os.environ.get("EPAGERPI_FONT_PATH", "")

# ---- 排程 / 刷新設定 ----
TICK_SECONDS = float(os.environ.get("EPAGERPI_TICK_SECONDS", "1"))
# Local fail-safe: at or after this time a working-day display changes to the
# off-work page even when no remote attendance update can be obtained.
AUTO_OFF_WORK_TIME = datetime.time.fromisoformat(
    os.environ.get("EPAGERPI_AUTO_OFF_WORK_TIME", "20:00")
)

# ---- 開發預覽 ----
PREVIEW_DIR = DATA_DIR / "preview"

# 跟 device_agent/config.py 的 BATTERY_STATE_PATH 指向同一個檔案（兩邊 BASE_DIR
# 都是 repo 根目錄）：UPS daemon 寫、progress_bar/stat_pair 模組的
# value_source type="battery" 讀，避免重複開 I2C。
BATTERY_STATE_PATH = DATA_DIR / "runtime" / "battery.json"


def now_local() -> datetime.datetime:
    """回傳系統顯示與情境判斷共用的本地時間（不帶 tzinfo，與既有 API 相容）。"""
    return datetime.datetime.now(TIMEZONE).replace(tzinfo=None)


def ensure_dirs():
    (DATA_DIR / "layouts").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "scenes").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "runtime").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "assets").mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

"""通用資料來源解析：讓任何模組的任何欄位都能選擇「手動填值」或「網路請求」。

layout JSON 裡欄位長這樣：
    {"type": "manual", "value": 94}
    {"type": "http", "url": "https://.../api", "path": "data.value", "fallback": 0, "timeout": 5}

path 用 "." 分隔巢狀 key（陣列用數字索引），抓不到或逾時就回傳 fallback，
不會讓整個模組因為單一網路請求失敗而整個爛掉。
"""
from __future__ import annotations

import datetime
import json

import requests

from .. import config
from .workday import workday_window

_TIMEOUT_DEFAULT = 5


def _today_time(hhmm: str) -> datetime.datetime:
    now = config.now_local()
    return datetime.datetime.combine(now.date(), datetime.time.fromisoformat(hhmm))


def is_network_source(source: dict | None) -> bool:
    """回傳這個資料來源是不是「要打網路的」（目前只有 http）。

    給拆分模式用：fetch_data() 只解析 is_network_source() 為 True 的欄位（依
    refresh_interval 節流快取），其餘型別（manual/battery/time_until/time_progress）
    一律留到 render() 當下、在實際驅動螢幕的那台機器上即時解析 —— 這些本地型別
    "本地就能算"，不需要、也不應該被伺服器端的節流快取卡住即時性（倒數計時/
    生存進度條因此才能真的動）。
    """
    if not source:
        return False
    return source.get("type", "manual") == "http"


def resolve_value(source: dict | None, default=None, context: dict | None = None):
    if not source:
        return default
    stype = source.get("type", "manual")

    if stype == "manual":
        return source.get("value", default)

    if stype == "battery":
        # 讀 UPS daemon 寫的共用快取檔（見 device_agent/ups/battery.py），
        # 不會另外去戳 I2C。field 預設 "percent"，也可以填 "bus_voltage" 等。
        try:
            reading = json.loads(config.BATTERY_STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return source.get("fallback", default)
        return reading.get(source.get("field", "percent"), source.get("fallback", default))

    if stype == "time_until":
        # 回傳「現在到某個今天的時間點」還剩多少，格式 HH:MM；已過該時間回傳 00:00。
        now = config.now_local()
        target = _today_time(source["target"])
        remaining = target - now
        if remaining.total_seconds() <= 0:
            return "00:00"
        total_minutes = int(remaining.total_seconds() // 60)
        return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"

    if stype == "time_progress":
        # 回傳「現在」在 start~end 這段今天的時間區間中的進度百分比（0-100，會夾在範圍內）。
        now = config.now_local()
        start = _today_time(source["start"])
        end = _today_time(source["end"])
        if end <= start:
            return 0
        ratio = (now - start).total_seconds() / (end - start).total_seconds()
        return round(max(0.0, min(1.0, ratio)) * 100, 1)

    if stype in {"attendance_workday_until", "attendance_workday_progress"}:
        now = config.now_local()
        attendance = context.get("attendance") if isinstance(context, dict) else None
        window = workday_window(source, attendance, now)
        if window is None:
            return source.get("fallback", default)
        start, target = window
        if stype == "attendance_workday_until":
            remaining = max(0, int((target - now).total_seconds() // 60))
            return f"{remaining // 60:02d}:{remaining % 60:02d}"
        ratio = (now - start).total_seconds() / (target - start).total_seconds()
        return round(max(0.0, min(1.0, ratio)) * 100, 1)

    if stype == "http":
        fallback = source.get("fallback", default)
        url = source["url"]
        if url.startswith("/"):
            url = config.SELF_BASE_URL + url
        try:
            resp = requests.get(url, timeout=source.get("timeout", _TIMEOUT_DEFAULT))
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            return fallback

        path = source.get("path")
        if not path:
            return payload
        cur = payload
        for key in str(path).split("."):
            try:
                cur = cur[int(key)] if isinstance(cur, list) else cur.get(key)
            except (KeyError, IndexError, ValueError, AttributeError, TypeError):
                return fallback
            if cur is None:
                return fallback
        return cur

    return default

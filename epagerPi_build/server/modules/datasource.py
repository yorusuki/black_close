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

_TIMEOUT_DEFAULT = 5


def _today_time(hhmm: str) -> datetime.datetime:
    now = datetime.datetime.now()
    return datetime.datetime.combine(now.date(), datetime.time.fromisoformat(hhmm))


def resolve_value(source: dict | None, default=None):
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
        now = datetime.datetime.now()
        target = _today_time(source["target"])
        remaining = target - now
        if remaining.total_seconds() <= 0:
            return "00:00"
        total_minutes = int(remaining.total_seconds() // 60)
        return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"

    if stype == "time_progress":
        # 回傳「現在」在 start~end 這段今天的時間區間中的進度百分比（0-100，會夾在範圍內）。
        now = datetime.datetime.now()
        start = _today_time(source["start"])
        end = _today_time(source["end"])
        if end <= start:
            return 0
        ratio = (now - start).total_seconds() / (end - start).total_seconds()
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

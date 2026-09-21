"""依當日上班打卡時間推算工作日目標時間的純函式。"""
from __future__ import annotations

import datetime as dt
from typing import Any


DEFAULT_WORKDAY_MINUTES = 9 * 60 + 1


def clock_in_target(attendance: dict | None, now: dt.datetime, work_minutes: Any = DEFAULT_WORKDAY_MINUTES) -> dt.datetime | None:
    """有合法 HH:MM 上班卡時，回傳該時間加上工作分鐘數的目標時間。"""
    clock_in = attendance.get("clock_in") if isinstance(attendance, dict) else None
    if not isinstance(clock_in, str):
        return None
    try:
        start_time = dt.time.fromisoformat(clock_in)
        minutes = max(1, min(24 * 60, int(work_minutes)))
    except (TypeError, ValueError):
        return None
    start = dt.datetime.combine(now.date(), start_time, tzinfo=now.tzinfo)
    return start + dt.timedelta(minutes=minutes)


def fallback_target(now: dt.datetime, hhmm: Any = "18:30") -> dt.datetime | None:
    """未打卡時保留既有固定下班時間，避免空白或負倒數。"""
    try:
        return dt.datetime.combine(now.date(), dt.time.fromisoformat(str(hhmm)), tzinfo=now.tzinfo)
    except (TypeError, ValueError):
        return None


def workday_window(source: dict | None, attendance: dict | None, now: dt.datetime) -> tuple[dt.datetime, dt.datetime] | None:
    """回傳進度起訖；優先使用上班卡 + 9 小時 1 分鐘，否則採設定的固定時段。"""
    source = source if isinstance(source, dict) else {}
    target = clock_in_target(attendance, now, source.get("work_minutes", DEFAULT_WORKDAY_MINUTES))
    if target is not None:
        return (
            target - dt.timedelta(minutes=max(1, min(24 * 60, int(source.get("work_minutes", DEFAULT_WORKDAY_MINUTES))))),
            target,
        )
    try:
        start = dt.datetime.combine(now.date(), dt.time.fromisoformat(str(source.get("fallback_start", "09:00"))), tzinfo=now.tzinfo)
    except (TypeError, ValueError):
        return None
    end = fallback_target(now, source.get("fallback_end", "18:30"))
    return (start, end) if end is not None and end > start else None

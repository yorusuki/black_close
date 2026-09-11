"""伺服器端的出勤／請假資料。

資料保存在 ``data/attendance.json``，Docker 部署時由既有的 data volume 持久化。
這是每天都會變動的個人資料，不應放進映像檔或 .env；Pi 端只會收到當前畫面所需的
已解析資料，並不會保存這份紀錄。
"""
from __future__ import annotations

import datetime
import re
from typing import Any

from . import config, store

_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_MAX_NOTE_LENGTH = 80


def attendance_path():
    return config.DATA_DIR / "attendance.json"


def today() -> datetime.date:
    return config.now_local().date()


def _empty_record() -> dict[str, Any]:
    return {
        "clock_in": None,
        "clock_out": None,
        "on_leave": False,
        "leave_note": "",
    }


def _normalise_record(value: Any) -> dict[str, Any]:
    record = _empty_record()
    if not isinstance(value, dict):
        return record
    for key in record:
        if key in value:
            record[key] = value[key]
    return record


def get_record(day: datetime.date | None = None) -> dict[str, Any]:
    day = day or today()
    source = store.read_json(attendance_path(), {"records": {}})
    records = source.get("records", {}) if isinstance(source, dict) else {}
    return _normalise_record(records.get(day.isoformat()))


def status_for(record: dict[str, Any]) -> str:
    if record.get("on_leave"):
        return "leave"
    if record.get("clock_in") and record.get("clock_out"):
        return "off_work"
    if record.get("clock_in"):
        return "working"
    return "pending"


def get_snapshot(day: datetime.date) -> dict[str, Any]:
    record = get_record(day)
    return {"date": day.isoformat(), "status": status_for(record), **record}


def get_today_snapshot() -> dict[str, Any]:
    return get_snapshot(today())


def validate_record(payload: Any) -> dict[str, Any]:
    """驗證不可信 request JSON，再回傳正規化的完整記錄。"""
    if not isinstance(payload, dict):
        raise ValueError("request body 必須是 JSON 物件")
    allowed = {"clock_in", "clock_out", "on_leave", "leave_note"}
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"不支援的欄位：{', '.join(sorted(unknown))}")

    record = _empty_record()
    for key in ("clock_in", "clock_out"):
        value = payload.get(key)
        if value in (None, ""):
            record[key] = None
        elif isinstance(value, str) and _TIME_RE.fullmatch(value):
            record[key] = value
        else:
            raise ValueError(f"{key} 必須是 HH:MM 格式或空值")

    leave = payload.get("on_leave", False)
    if not isinstance(leave, bool):
        raise ValueError("on_leave 必須是 true 或 false")
    record["on_leave"] = leave

    note = payload.get("leave_note", "")
    if not isinstance(note, str):
        raise ValueError("leave_note 必須是文字")
    record["leave_note"] = note.strip()
    if len(record["leave_note"]) > _MAX_NOTE_LENGTH:
        raise ValueError(f"leave_note 最多 {_MAX_NOTE_LENGTH} 個字元")

    if record["on_leave"] and (record["clock_in"] or record["clock_out"]):
        raise ValueError("請假日不可同時填寫上下班時間")
    if record["clock_out"] and not record["clock_in"]:
        raise ValueError("填寫下班時間前，請先填寫上班時間")
    return record


def save_record(day: datetime.date, payload: Any) -> dict[str, Any]:
    record = validate_record(payload)
    source = store.read_json(attendance_path(), {"records": {}})
    if not isinstance(source, dict):
        source = {"records": {}}
    records = source.get("records")
    if not isinstance(records, dict):
        records = {}
        source["records"] = records
    records[day.isoformat()] = record
    store.write_json(attendance_path(), source)
    return {"date": day.isoformat(), "status": status_for(record), **record}


def save_today(payload: Any) -> dict[str, Any]:
    return save_record(today(), payload)

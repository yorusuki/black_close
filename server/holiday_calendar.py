"""帳號隔離的休假日行事曆與官方公開資料匯入。

資料仍以小型 JSON 檔保存，避免為行事曆功能變更既有 SQLite schema。官方來源
固定為政府資料開放平台公開的辦公日曆 API，刻意不接受前端傳入 URL，避免 SSRF。
"""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import re
from contextlib import contextmanager
from typing import Any

import requests

from . import config, store

OFFICIAL_CALENDAR_URL = "https://data.ntpc.gov.tw/api/datasets/308dcd75-6434-45bc-a95f-584da4fed251/json?page=0&size=10000"
OFFICIAL_SOURCE_LABEL = "政府辦公日曆公開資料"
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_MANUAL_DATES = 366


class HolidayCalendarError(ValueError):
    """可安全回傳管理台的行事曆錯誤。"""


def _path():
    return config.DATA_DIR / "user_holidays.json"


def _blank() -> dict[str, Any]:
    return {"version": 1, "users": {}}


def _load() -> dict[str, Any]:
    data = store.read_json(_path(), _blank())
    if not isinstance(data, dict) or not isinstance(data.get("users"), dict):
        return _blank()
    return data


def _save(data: dict[str, Any]) -> None:
    store.write_json(_path(), data)


@contextmanager
def _write_lock():
    """序列化多個 Gunicorn worker 的讀取、修改與寫入，避免覆蓋別人的日期。"""
    path = config.DATA_DIR / "user_holidays.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _user_data(data: dict[str, Any], user_id: str, *, create: bool) -> dict[str, Any]:
    users = data.setdefault("users", {})
    value = users.get(user_id)
    if not isinstance(value, dict):
        if not create:
            return {"official": {}, "manual": {}}
        value = {"official": {}, "manual": {}}
        users[user_id] = value
    if not isinstance(value.get("official"), dict):
        value["official"] = {}
    if not isinstance(value.get("manual"), dict):
        value["manual"] = {}
    return value


def _parse_iso_date(value: Any) -> dt.date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise HolidayCalendarError("日期必須是 YYYY-MM-DD")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise HolidayCalendarError("日期必須是 YYYY-MM-DD") from exc


def _clean_name(value: Any, *, fallback: str) -> str:
    if value is None:
        return fallback
    if not isinstance(value, str):
        raise HolidayCalendarError("假日名稱必須是文字")
    name = " ".join(value.split())
    if not name:
        return fallback
    if len(name) > 80:
        raise HolidayCalendarError("假日名稱最多 80 字")
    return name


def _legacy_dates() -> set[str]:
    """保留舊版固定日期的相容性；新版手動資料不會跨帳號共享。"""
    result: set[str] = set()
    for value in store.get_holidays():
        try:
            result.add(_parse_iso_date(value).isoformat())
        except HolidayCalendarError:
            continue
    return result


def list_holidays(user_id: str) -> list[dict[str, str]]:
    """列出此帳號有效休假日；手動日期可覆蓋同日官方／相容資料名稱。"""
    data = _load()
    user = _user_data(data, user_id, create=False)
    combined: dict[str, dict[str, str]] = {
        date: {"date": date, "name": "既有國定假日", "source": "legacy"}
        for date in _legacy_dates()
    }
    official = user["official"]
    for year, dates in official.items():
        if not isinstance(year, str) or not isinstance(dates, dict):
            continue
        for value, name in dates.items():
            try:
                date = _parse_iso_date(value).isoformat()
                combined[date] = {"date": date, "name": _clean_name(name, fallback="國定休假"), "source": "official"}
            except HolidayCalendarError:
                continue
    manual = user["manual"]
    for value, name in manual.items():
        try:
            date = _parse_iso_date(value).isoformat()
            combined[date] = {"date": date, "name": _clean_name(name, fallback="自訂休假"), "source": "manual"}
        except HolidayCalendarError:
            continue
    return [combined[key] for key in sorted(combined)]


def is_holiday(user_id: str, day: dt.date) -> bool:
    return day.isoformat() in {item["date"] for item in list_holidays(user_id)}


def add_manual_holiday(user_id: str, value: Any, name: Any = None) -> dict[str, str]:
    day = _parse_iso_date(value)
    label = _clean_name(name, fallback="自訂休假")
    with _write_lock():
        data = _load()
        user = _user_data(data, user_id, create=True)
        manual = user["manual"]
        if day.isoformat() not in manual and len(manual) >= _MAX_MANUAL_DATES:
            raise HolidayCalendarError("自訂休假日最多 366 筆")
        manual[day.isoformat()] = label
        _save(data)
    return {"date": day.isoformat(), "name": label, "source": "manual"}


def delete_manual_holiday(user_id: str, value: Any) -> bool:
    day = _parse_iso_date(value)
    with _write_lock():
        data = _load()
        user = _user_data(data, user_id, create=False)
        manual = user["manual"]
        if day.isoformat() not in manual:
            return False
        del manual[day.isoformat()]
        _save(data)
    return True


def _read_official_payload() -> Any:
    """以固定 HTTPS endpoint 讀取有限大小 JSON，避免外部資料無限佔用記憶體。"""
    response = None
    try:
        response = requests.get(
            OFFICIAL_CALENDAR_URL,
            headers={"Accept": "application/json"},
            timeout=10,
            stream=True,
            allow_redirects=False,
        )
        response.raise_for_status()
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > _MAX_RESPONSE_BYTES:
            raise HolidayCalendarError("官方行事曆資料過大，請稍後再試")
        body = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            body.extend(chunk)
            if len(body) > _MAX_RESPONSE_BYTES:
                raise HolidayCalendarError("官方行事曆資料過大，請稍後再試")
    except HolidayCalendarError:
        raise
    except (requests.RequestException, ValueError, OSError) as exc:
        raise HolidayCalendarError("無法取得官方行事曆，請稍後再試") from exc
    finally:
        # stream=True 不主動關閉會在長期運作的 Gunicorn worker 留下連線；mock
        # response 未必實作 close，因此只在它存在時呼叫。
        close = getattr(response, "close", None)
        if callable(close):
            close()
    try:
        return json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HolidayCalendarError("官方行事曆回傳格式不正確") from exc


def _records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("data", payload.get("records", []))
    else:
        rows = []
    if not isinstance(rows, list):
        raise HolidayCalendarError("官方行事曆回傳格式不正確")
    return [row for row in rows if isinstance(row, dict)]


def _official_date(value: Any) -> dt.date:
    if isinstance(value, str) and len(value) == 8 and value.isdigit():
        try:
            return dt.datetime.strptime(value, "%Y%m%d").date()
        except ValueError as exc:
            raise HolidayCalendarError("官方行事曆日期格式不正確") from exc
    return _parse_iso_date(value)


def import_official_holidays(user_id: str, year_value: Any, *, payload: Any = None) -> dict[str, Any]:
    """匯入某年度的平日休假。週六日原本已有週末規則，不重複寫入。"""
    if isinstance(year_value, bool) or not (
        isinstance(year_value, int) or isinstance(year_value, str) and re.fullmatch(r"\d{4}", year_value)
    ):
        raise HolidayCalendarError("年份必須是四位數")
    year = int(year_value)
    if not 2000 <= year <= 2100:
        raise HolidayCalendarError("年份必須介於 2000 到 2100")
    rows = _records(_read_official_payload() if payload is None else payload)
    imported: dict[str, str] = {}
    for row in rows:
        try:
            day = _official_date(row.get("date"))
        except HolidayCalendarError:
            continue
        is_holiday = str(row.get("isholiday", "")).strip().lower() in {"y", "yes", "true", "1", "是"}
        # 政府辦公日曆也列「特定節日」（例如僅軍人適用），不能當成所有使用者的國定假日。
        if day.year != year or day.weekday() >= 5 or not is_holiday or row.get("holidaycategory") == "特定節日":
            continue
        imported[day.isoformat()] = _clean_name(row.get("name"), fallback="國定休假")
    if not imported:
        raise HolidayCalendarError("官方資料中沒有找到該年度的平日休假日")
    with _write_lock():
        data = _load()
        user = _user_data(data, user_id, create=True)
        user["official"][str(year)] = imported
        _save(data)
    return {"year": year, "imported": len(imported), "source": OFFICIAL_SOURCE_LABEL, "dates": [
        {"date": date, "name": name, "source": "official"} for date, name in sorted(imported.items())
    ]}

"""SQLite 工作區資料與舊 JSON 的一次性遷移。"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import config, store

MODEL_IDS = {"inky_phat", "waveshare_4in26", "mock"}
_PLACEHOLDER_USER_ID = "legacy-unassigned"
_MIGRATION_KEY = "legacy_json_v1"


def _path() -> Path:
    return Path(config.WORKSPACE_DATABASE_URL)


@contextmanager
def _db():
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _row(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _parse_json(value: str | None, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except json.JSONDecodeError:
        return default


def init() -> None:
    """建立 schema；可安全升級先前未接線的 SQLite 草稿。"""
    with _db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS schema_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY, line_sub TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL,
          role TEXT NOT NULL CHECK(role IN ('owner','member')), is_placeholder INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS devices (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), legacy_id TEXT UNIQUE,
          name TEXT NOT NULL, model_id TEXT NOT NULL, profile_json TEXT NOT NULL DEFAULT '{}',
          token_hash TEXT NOT NULL UNIQUE, active INTEGER NOT NULL DEFAULT 1, hidden INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS pages (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), legacy_id TEXT UNIQUE,
          name TEXT NOT NULL, template_id TEXT NOT NULL DEFAULT 'custom', content_json TEXT NOT NULL DEFAULT '{"elements":[]}',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS rules (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
          device_id TEXT NOT NULL REFERENCES devices(id), page_id TEXT NOT NULL REFERENCES pages(id),
          name TEXT NOT NULL DEFAULT '規則', priority INTEGER NOT NULL DEFAULT 0,
          weekdays_json TEXT NOT NULL DEFAULT '[]', start_time TEXT, end_time TEXT,
          attendance_status TEXT, holiday INTEGER, enabled INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS assets (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), filename TEXT NOT NULL,
          original_filename TEXT NOT NULL, mime_type TEXT NOT NULL, digest TEXT NOT NULL, size INTEGER NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS attendance_records (
          user_id TEXT NOT NULL REFERENCES users(id), day TEXT NOT NULL, clock_in TEXT, clock_out TEXT,
          on_leave INTEGER NOT NULL DEFAULT 0, leave_note TEXT NOT NULL DEFAULT '', PRIMARY KEY(user_id, day)
        );
        CREATE TABLE IF NOT EXISTS device_telemetry (
          id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT NOT NULL REFERENCES devices(id),
          reported_at TEXT NOT NULL, payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_devices_user ON devices(user_id);
        CREATE INDEX IF NOT EXISTS idx_pages_user ON pages(user_id);
        CREATE INDEX IF NOT EXISTS idx_rules_device ON rules(device_id, priority DESC);
        CREATE INDEX IF NOT EXISTS idx_assets_user ON assets(user_id);
        CREATE INDEX IF NOT EXISTS idx_telemetry_device ON device_telemetry(device_id, reported_at DESC);
        """)
        # Upgrade the already-present draft schema if somebody initialized it.
        columns = {r[1] for r in con.execute("PRAGMA table_info(users)")}
        if "is_placeholder" not in columns:
            con.execute("ALTER TABLE users ADD COLUMN is_placeholder INTEGER NOT NULL DEFAULT 0")
        page_columns = {r[1] for r in con.execute("PRAGMA table_info(pages)")}
        if "content_json" not in page_columns:
            con.execute("ALTER TABLE pages ADD COLUMN content_json TEXT NOT NULL DEFAULT '{\"elements\":[]}'")
        if "template_id" not in page_columns:
            con.execute("ALTER TABLE pages ADD COLUMN template_id TEXT NOT NULL DEFAULT 'custom'")
        device_columns = {r[1] for r in con.execute("PRAGMA table_info(devices)")}
        for column, definition in (("legacy_id", "TEXT"), ("profile_json", "TEXT NOT NULL DEFAULT '{}'"),
                                   ("active", "INTEGER NOT NULL DEFAULT 1"), ("hidden", "INTEGER NOT NULL DEFAULT 0")):
            if column not in device_columns:
                con.execute(f"ALTER TABLE devices ADD COLUMN {column} {definition}")
        rule_columns = {r[1] for r in con.execute("PRAGMA table_info(rules)")}
        for column, definition in (("name", "TEXT NOT NULL DEFAULT '規則'"), ("weekdays_json", "TEXT NOT NULL DEFAULT '[]'")):
            if column not in rule_columns:
                con.execute(f"ALTER TABLE rules ADD COLUMN {column} {definition}")


def _placeholder(con: sqlite3.Connection) -> None:
    con.execute("INSERT OR IGNORE INTO users(id,line_sub,display_name,role,is_placeholder) VALUES(?,?,?,?,1)",
                (_PLACEHOLDER_USER_ID, "legacy-unassigned", "待認領的舊資料", "owner"))


def _token_hash(token: str) -> str:
    return hashlib.sha256((config.DEVICE_TOKEN_PEPPER + token).encode("utf-8")).hexdigest()


def issue_device_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, _token_hash(token)


def migrate_legacy_json() -> dict[str, int]:
    """一次性匯入 JSON；不改寫舊檔，重跑時回傳原結果。"""
    init()
    with _db() as con:
        done = con.execute("SELECT value FROM schema_metadata WHERE key=?", (_MIGRATION_KEY,)).fetchone()
        if done:
            return _parse_json(done["value"], {})
        _placeholder(con)
        summary = {"devices": 0, "pages": 0, "rules": 0, "assets": 0, "attendance": 0}
        device_ids: dict[str, str] = {}
        page_ids: dict[str, str] = {}
        for legacy in store.list_devices():
            legacy_id = str(legacy.get("id", "")).strip()
            if not legacy_id:
                continue
            model = str(legacy.get("driver", "mock"))
            model = model if model in MODEL_IDS else "mock"
            con.execute("""INSERT OR IGNORE INTO devices(id,user_id,legacy_id,name,model_id,profile_json,token_hash)
                           VALUES(?,?,?,?,?,?,?)""",
                        (str(uuid.uuid4()), _PLACEHOLDER_USER_ID, legacy_id, legacy.get("name") or legacy_id,
                         model, _json(legacy), _token_hash(secrets.token_urlsafe(32))))
            device_ids[legacy_id] = con.execute("SELECT id FROM devices WHERE legacy_id=?", (legacy_id,)).fetchone()["id"]
            summary["devices"] += 1
        for legacy_id in store.list_layout_ids():
            content = store.get_layout(legacy_id)
            if not isinstance(content, dict):
                continue
            con.execute("INSERT OR IGNORE INTO pages(id,user_id,legacy_id,name,template_id,content_json) VALUES(?,?,?,?,?,?)",
                        (str(uuid.uuid4()), _PLACEHOLDER_USER_ID, legacy_id, legacy_id, "legacy", _json(content)))
            page_ids[legacy_id] = con.execute("SELECT id FROM pages WHERE legacy_id=?", (legacy_id,)).fetchone()["id"]
            summary["pages"] += 1
        for legacy_id, device_id in device_ids.items():
            for scene in store.get_scenes(legacy_id):
                page_id = page_ids.get(str(scene.get("layout_id", "")))
                if not page_id:
                    continue
                condition = scene.get("condition") if isinstance(scene.get("condition"), dict) else {}
                time_range = condition.get("time_range") if isinstance(condition.get("time_range"), list) else [None, None]
                con.execute("""INSERT OR IGNORE INTO rules(id,user_id,device_id,page_id,name,priority,weekdays_json,start_time,end_time,holiday,enabled)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                            (f"legacy-{legacy_id}-{scene.get('id', uuid.uuid4().hex)}", _PLACEHOLDER_USER_ID, device_id,
                             page_id, str(scene.get("name") or "舊規則"), int(scene.get("priority", 0)),
                             _json(condition.get("weekdays", [])), time_range[0] if len(time_range) else None,
                             time_range[1] if len(time_range) > 1 else None,
                             None if "is_holiday" not in condition else int(bool(condition["is_holiday"])), 1))
                summary["rules"] += 1
        for asset in store.read_json(config.DATA_DIR / "assets.json", []):
            if not isinstance(asset, dict) or not asset.get("id"):
                continue
            con.execute("""INSERT OR IGNORE INTO assets(id,user_id,filename,original_filename,mime_type,digest,size)
                           VALUES(?,?,?,?,?,?,?)""",
                        (str(asset["id"]), _PLACEHOLDER_USER_ID, str(asset.get("filename", "")),
                         str(asset.get("original_filename") or asset["id"]), "application/octet-stream",
                         str(asset.get("hash", "")), int(asset.get("size", 0))))
            summary["assets"] += 1
        source = store.read_json(config.DATA_DIR / "attendance.json", {"records": {}})
        records = source.get("records", {}) if isinstance(source, dict) else {}
        for day, record in records.items():
            if not isinstance(record, dict):
                continue
            con.execute("""INSERT OR IGNORE INTO attendance_records(user_id,day,clock_in,clock_out,on_leave,leave_note)
                           VALUES(?,?,?,?,?,?)""",
                        (_PLACEHOLDER_USER_ID, str(day), record.get("clock_in"), record.get("clock_out"),
                         int(bool(record.get("on_leave"))), str(record.get("leave_note", ""))[:80]))
            summary["attendance"] += 1
        con.execute("INSERT INTO schema_metadata(key,value) VALUES(?,?)", (_MIGRATION_KEY, _json(summary)))
        return summary


def user_by_id(user_id: str) -> dict | None:
    with _db() as con:
        return _row(con.execute("SELECT * FROM users WHERE id=? AND is_placeholder=0", (user_id,)).fetchone())


def user(line_sub: str) -> dict | None:
    with _db() as con:
        return _row(con.execute("SELECT * FROM users WHERE line_sub=? AND is_placeholder=0", (line_sub,)).fetchone())


def ensure_first_owner(line_sub: str, display_name: str) -> dict | None:
    """原子建立首位 owner，並認領所有待認領的舊資料。"""
    if not isinstance(line_sub, str) or not line_sub:
        return None
    with _db() as con:
        existing = con.execute("SELECT * FROM users WHERE line_sub=? AND is_placeholder=0", (line_sub,)).fetchone()
        if existing:
            return _row(existing)
        if con.execute("SELECT COUNT(*) FROM users WHERE is_placeholder=0").fetchone()[0]:
            return None
        identifier = str(uuid.uuid4())
        con.execute("INSERT INTO users(id,line_sub,display_name,role,is_placeholder) VALUES(?,?,?,?,0)",
                    (identifier, line_sub, (display_name or "LINE 使用者")[:100], "owner"))
        for table in ("devices", "pages", "rules", "assets", "attendance_records"):
            con.execute(f"UPDATE {table} SET user_id=? WHERE user_id=?", (identifier, _PLACEHOLDER_USER_ID))
        con.execute("DELETE FROM users WHERE id=?", (_PLACEHOLDER_USER_ID,))
        return _row(con.execute("SELECT * FROM users WHERE id=?", (identifier,)).fetchone())


def _public_device(row: sqlite3.Row) -> dict:
    out = dict(row)
    out.pop("token_hash", None)
    out["profile"] = _parse_json(out.pop("profile_json", "{}"), {})
    out["active"], out["hidden"] = bool(out["active"]), bool(out["hidden"])
    return out


def list_devices(user_id: str, *, include_hidden: bool = True) -> list[dict]:
    sql = "SELECT * FROM devices WHERE user_id=?" + ("" if include_hidden else " AND hidden=0") + " ORDER BY name"
    with _db() as con:
        return [_public_device(row) for row in con.execute(sql, (user_id,))]


def get_device(user_id: str, device_id: str) -> dict | None:
    with _db() as con:
        row = con.execute("SELECT * FROM devices WHERE id=? AND user_id=?", (device_id, user_id)).fetchone()
        return _public_device(row) if row else None


def create_device(user_id: str, name: str, model_id: str, profile: dict | None = None) -> dict:
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
        raise ValueError("Pi 名稱必須為 1 至 100 個字元")
    if model_id not in MODEL_IDS:
        raise ValueError("不支援的硬體型號")
    profiles = {
        "inky_phat": {"driver": "inky_phat", "resolution": [212, 104], "color_mode": "3color", "partial_refresh": False},
        "waveshare_4in26": {"driver": "waveshare_4in26", "resolution": [800, 480], "color_mode": "1bit", "partial_refresh": True},
        "mock": {"driver": "mock", "resolution": [800, 480], "color_mode": "1bit", "partial_refresh": True},
    }
    token, token_hash, identifier = *issue_device_token(), str(uuid.uuid4())
    with _db() as con:
        con.execute("INSERT INTO devices(id,user_id,name,model_id,profile_json,token_hash) VALUES(?,?,?,?,?,?)",
                    (identifier, user_id, name.strip(), model_id, _json(profile or profiles[model_id]), token_hash))
        row = con.execute("SELECT * FROM devices WHERE id=?", (identifier,)).fetchone()
    result = _public_device(row)
    result["token"] = token  # 僅建立／重配發時回傳
    return result


def set_device_hidden(user_id: str, device_id: str, hidden: bool) -> bool:
    with _db() as con:
        return con.execute("UPDATE devices SET hidden=? WHERE id=? AND user_id=?", (int(hidden), device_id, user_id)).rowcount == 1


def rotate_device_token(user_id: str, device_id: str) -> str | None:
    token, token_hash = issue_device_token()
    with _db() as con:
        ok = con.execute("UPDATE devices SET token_hash=?,active=1 WHERE id=? AND user_id=?", (token_hash, device_id, user_id)).rowcount
    return token if ok else None


def device_for_token(token: str) -> dict | None:
    if not isinstance(token, str) or len(token) < 32 or not config.DEVICE_TOKEN_PEPPER:
        return None
    candidate = _token_hash(token)
    with _db() as con:
        rows = con.execute("SELECT * FROM devices WHERE active=1 AND hidden=0").fetchall()
    for row in rows:
        if hmac.compare_digest(row["token_hash"], candidate):
            return _public_device(row)
    return None


def _public_page(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["content"] = _parse_json(out.pop("content_json"), {"elements": []})
    return out


def list_pages(user_id: str) -> list[dict]:
    with _db() as con:
        return [_public_page(row) for row in con.execute("SELECT * FROM pages WHERE user_id=? ORDER BY name", (user_id,))]


def get_page(user_id: str, page_id: str) -> dict | None:
    with _db() as con:
        row = con.execute("SELECT * FROM pages WHERE id=? AND user_id=?", (page_id, user_id)).fetchone()
        return _public_page(row) if row else None


def _validate_page_content(content: Any) -> dict:
    if not isinstance(content, dict) or not isinstance(content.get("elements", []), list):
        raise ValueError("頁面內容必須包含 elements 陣列")
    if len(content["elements"]) > 100:
        raise ValueError("單一頁面最多 100 個元件")
    return content


def create_page(user_id: str, name: str, content: Any | None = None) -> dict:
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
        raise ValueError("頁面名稱必須為 1 至 100 個字元")
    identifier, content = str(uuid.uuid4()), _validate_page_content(content or {"elements": []})
    with _db() as con:
        con.execute("INSERT INTO pages(id,user_id,name,template_id,content_json) VALUES(?,?,?,?,?)", (identifier, user_id, name.strip(), "custom", _json(content)))
        return _public_page(con.execute("SELECT * FROM pages WHERE id=?", (identifier,)).fetchone())


def save_page(user_id: str, page_id: str, name: str, content: Any) -> dict | None:
    content = _validate_page_content(content)
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
        raise ValueError("頁面名稱必須為 1 至 100 個字元")
    with _db() as con:
        if not con.execute("UPDATE pages SET name=?,content_json=? WHERE id=? AND user_id=?", (name.strip(), _json(content), page_id, user_id)).rowcount:
            return None
        return _public_page(con.execute("SELECT * FROM pages WHERE id=?", (page_id,)).fetchone())


def _validate_rule(user_id: str, data: Any) -> dict:
    if not isinstance(data, dict):
        raise ValueError("規則必須是 JSON 物件")
    device_id, page_id = data.get("device_id"), data.get("page_id")
    if not isinstance(device_id, str) or not get_device(user_id, device_id):
        raise ValueError("找不到所選 Pi")
    if not isinstance(page_id, str) or not get_page(user_id, page_id):
        raise ValueError("找不到所選頁面")
    weekdays = data.get("weekdays", [])
    if not isinstance(weekdays, list) or any(not isinstance(day, int) or day not in range(7) for day in weekdays):
        raise ValueError("weekdays 必須是 0 到 6 的整數陣列")
    for field in ("start_time", "end_time"):
        value = data.get(field)
        if value not in (None, ""):
            try: dt.time.fromisoformat(value)
            except (TypeError, ValueError) as exc: raise ValueError(f"{field} 必須為 HH:MM") from exc
    status, holiday = data.get("attendance_status"), data.get("holiday")
    if status not in (None, "", "pending", "working", "off_work", "leave"):
        raise ValueError("attendance_status 不支援")
    if holiday not in (None, True, False):
        raise ValueError("holiday 必須是 true、false 或空值")
    return {"device_id": device_id, "page_id": page_id, "name": str(data.get("name") or "規則")[:100],
            "priority": int(data.get("priority", 0)), "weekdays": sorted(set(weekdays)),
            "start_time": data.get("start_time") or None, "end_time": data.get("end_time") or None,
            "attendance_status": status or None, "holiday": None if holiday is None else int(holiday),
            "enabled": int(bool(data.get("enabled", True)))}


def _public_rule(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["weekdays"] = _parse_json(out.pop("weekdays_json"), [])
    out["enabled"] = bool(out["enabled"])
    out["holiday"] = None if out["holiday"] is None else bool(out["holiday"])
    return out


def list_rules(user_id: str) -> list[dict]:
    with _db() as con:
        return [_public_rule(row) for row in con.execute("SELECT * FROM rules WHERE user_id=? ORDER BY priority DESC, name", (user_id,))]


def create_rule(user_id: str, data: Any) -> dict:
    rule, identifier = _validate_rule(user_id, data), str(uuid.uuid4())
    with _db() as con:
        con.execute("""INSERT INTO rules(id,user_id,device_id,page_id,name,priority,weekdays_json,start_time,end_time,attendance_status,holiday,enabled)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (identifier, user_id, rule["device_id"], rule["page_id"], rule["name"], rule["priority"], _json(rule["weekdays"]),
                     rule["start_time"], rule["end_time"], rule["attendance_status"], rule["holiday"], rule["enabled"]))
        return _public_rule(con.execute("SELECT * FROM rules WHERE id=?", (identifier,)).fetchone())


def delete_rule(user_id: str, rule_id: str) -> bool:
    with _db() as con:
        return con.execute("DELETE FROM rules WHERE id=? AND user_id=?", (rule_id, user_id)).rowcount == 1


def list_assets(user_id: str) -> list[dict]:
    with _db() as con:
        return [dict(row) for row in con.execute("SELECT * FROM assets WHERE user_id=? ORDER BY created_at DESC", (user_id,))]


def get_asset(user_id: str, asset_id: str) -> dict | None:
    with _db() as con:
        return _row(con.execute("SELECT * FROM assets WHERE id=? AND user_id=?", (asset_id, user_id)).fetchone())


def add_asset(user_id: str, record: dict, mime_type: str) -> dict:
    with _db() as con:
        con.execute("INSERT OR REPLACE INTO assets(id,user_id,filename,original_filename,mime_type,digest,size) VALUES(?,?,?,?,?,?,?)",
                    (record["id"], user_id, record["filename"], record.get("original_filename") or record["id"], mime_type,
                     record.get("hash", ""), int(record.get("size", 0))))
        return _row(con.execute("SELECT * FROM assets WHERE id=?", (record["id"],)).fetchone())


def attendance_snapshot(user_id: str, day: dt.date) -> dict:
    with _db() as con:
        row = con.execute("SELECT * FROM attendance_records WHERE user_id=? AND day=?", (user_id, day.isoformat())).fetchone()
    record = dict(row) if row else {"clock_in": None, "clock_out": None, "on_leave": 0, "leave_note": ""}
    status = "leave" if record.get("on_leave") else "off_work" if record.get("clock_in") and record.get("clock_out") else "working" if record.get("clock_in") else "pending"
    return {"date": day.isoformat(), "status": status, "clock_in": record.get("clock_in"), "clock_out": record.get("clock_out"),
            "on_leave": bool(record.get("on_leave")), "leave_note": record.get("leave_note", "")}


def save_attendance(user_id: str, day: dt.date, payload: Any) -> dict:
    if not isinstance(payload, dict) or set(payload) - {"clock_in", "clock_out", "on_leave", "leave_note"}:
        raise ValueError("出勤欄位不正確")
    clock_in, clock_out = payload.get("clock_in") or None, payload.get("clock_out") or None
    for value in (clock_in, clock_out):
        if value:
            try: dt.time.fromisoformat(value)
            except (TypeError, ValueError) as exc: raise ValueError("上下班時間必須為 HH:MM") from exc
    on_leave = payload.get("on_leave", False)
    note = payload.get("leave_note", "")
    if not isinstance(on_leave, bool) or not isinstance(note, str) or len(note.strip()) > 80:
        raise ValueError("出勤資料不正確")
    if on_leave and (clock_in or clock_out): raise ValueError("請假不可同時有上下班時間")
    if clock_out and not clock_in: raise ValueError("下班前必須先填上班時間")
    with _db() as con:
        con.execute("""INSERT INTO attendance_records(user_id,day,clock_in,clock_out,on_leave,leave_note) VALUES(?,?,?,?,?,?)
                       ON CONFLICT(user_id,day) DO UPDATE SET clock_in=excluded.clock_in,clock_out=excluded.clock_out,
                       on_leave=excluded.on_leave,leave_note=excluded.leave_note""",
                    (user_id, day.isoformat(), clock_in, clock_out, int(on_leave), note.strip()))
    return attendance_snapshot(user_id, day)


def _match_rule(rule: dict, now: dt.datetime, holiday: bool, attendance_status: str) -> bool:
    if not rule["enabled"] or (rule["weekdays"] and now.weekday() not in rule["weekdays"]): return False
    if rule["holiday"] is not None and rule["holiday"] != holiday: return False
    if rule["attendance_status"] and rule["attendance_status"] != attendance_status: return False
    start, end = rule["start_time"], rule["end_time"]
    if start and end:
        a, b = dt.time.fromisoformat(start), dt.time.fromisoformat(end)
        if not (a <= now.time() <= b if a <= b else now.time() >= a or now.time() <= b): return False
    return True


def _attendance_status(user_id: str, day: dt.date) -> str:
    with _db() as con:
        row = con.execute("SELECT * FROM attendance_records WHERE user_id=? AND day=?", (user_id, day.isoformat())).fetchone()
    if not row: return "pending"
    if row["on_leave"]: return "leave"
    return "off_work" if row["clock_in"] and row["clock_out"] else "working" if row["clock_in"] else "pending"


def device_layout(device: dict, now: dt.datetime | None = None) -> dict:
    """為 token 所屬 Pi 建立版面，不透露他人裝置與素材。"""
    from .modules.registry import get_module
    now = now or config.now_local()
    holiday = now.date().isoformat() in set(store.get_holidays())
    status = _attendance_status(device["user_id"], now.date())
    rules = [r for r in list_rules(device["user_id"]) if r["device_id"] == device["id"]]
    chosen = max((r for r in rules if _match_rule(r, now, holiday, status)), key=lambda r: r["priority"], default=None)
    page = get_page(device["user_id"], chosen["page_id"]) if chosen else None
    elements = []
    for item in (page or {"content": {"elements": []}})["content"].get("elements", []):
        module = get_module(item.get("module_id")) if isinstance(item, dict) else None
        if not module: continue
        data: dict = {}
        if item.get("module_id") == "image":
            asset = get_asset(device["user_id"], str((item.get("config") or {}).get("asset_id", "")))
            if asset: data["filename"] = asset["filename"]
        else:
            try: data = module.fetch_data(item.get("config") or {})
            except Exception: data = {}
        elements.append({**item, "data": data})
    return {"device_id": device["id"], "profile": device["profile"], "layout_id": page["id"] if page else None,
            "page_name": page["name"] if page else None, "scene": chosen["name"] if chosen else None,
            "elements": elements, "resolved_at": now.isoformat(timespec="seconds")}


def asset_for_device(device: dict, asset_id: str) -> dict | None:
    return get_asset(device["user_id"], asset_id)


def save_telemetry(device: dict, payload: Any) -> dict:
    if not isinstance(payload, dict): raise ValueError("telemetry 必須是 JSON 物件")
    allowed = {"agent_version", "battery_percent", "uptime_seconds", "refresh_mode", "status", "reported_at"}
    if set(payload) - allowed: raise ValueError("telemetry 包含不支援欄位")
    clean = {key: payload[key] for key in allowed if key in payload}
    clean["reported_at"] = clean.get("reported_at") or dt.datetime.now(dt.timezone.utc).isoformat()
    with _db() as con:
        con.execute("INSERT INTO device_telemetry(device_id,reported_at,payload_json) VALUES(?,?,?)", (device["id"], clean["reported_at"], _json(clean)))
    return clean

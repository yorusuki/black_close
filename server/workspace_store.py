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

MODEL_IDS = {"inky_phat", "waveshare_4in26", "waveshare_7in5_v2", "mock"}
_MODEL_RESOLUTIONS = {
    "inky_phat": (212, 104),
    "waveshare_4in26": (800, 480),
    "waveshare_7in5_v2": (800, 480),
    "mock": (800, 480),
}
_PLACEHOLDER_USER_ID = "legacy-unassigned"
_MIGRATION_KEY = "legacy_json_v1"
_WORK_LAYOUT_UPGRADE_KEY = "waveshare_work_layout_v2"
_WORK_LAYOUT_MASCOT_INTERVAL_UPGRADE_KEY = "waveshare_work_layout_mascot_interval_v3"
_REFRESH_POLICY_UPGRADE_KEY = "waveshare_refresh_policy_v2"
_OFF_WORK_LAYOUT_UPGRADE_KEY = "waveshare_off_work_greetings_v1"
_REFRESH_POLICY_DAILY_DEFAULT_UPGRADE_KEY = "waveshare_refresh_daily_default_v3"
_LUNCH_PAGE_UPGRADE_KEY = "waveshare_lunch_page_v1"
_WEEKEND_PAGE_UPGRADE_KEY = "waveshare_weekend_page_v1"
_LEAVE_PAGE_UPGRADE_KEY = "waveshare_leave_page_v1"
_QUIET_HOURS_DEFAULT_UPGRADE_KEY = "device_display_quiet_hours_v1"
_QUIET_HOURS_WEEKEND_UPGRADE_KEY = "device_display_quiet_hours_weekend_v2"
_ONLINE_AFTER_SECONDS = 180
_DEFAULT_QUIET_HOURS = {"enabled": True, "start": "20:00", "end": "08:30", "pause_weekends": True}
_HARDWARE_PROFILE_FIELDS = ("driver", "resolution", "color_mode", "partial_refresh")
_DEFAULT_DEVICE_PROFILES = {
    "inky_phat": {"driver": "inky_phat", "resolution": [212, 104], "color_mode": "3color", "partial_refresh": False},
    "waveshare_4in26": {"driver": "waveshare_4in26", "resolution": [800, 480], "color_mode": "1bit", "partial_refresh": True, "full_refresh_interval_seconds": 86_400, "server_full_refresh_daily_at": "12:00", "full_refresh_daily_at": "12:00", "display_quiet_hours": _DEFAULT_QUIET_HOURS},
    "waveshare_7in5_v2": {"driver": "waveshare_7in5_v2", "resolution": [800, 480], "color_mode": "1bit", "partial_refresh": True, "full_refresh_interval_seconds": 86_400, "server_full_refresh_daily_at": "12:00", "full_refresh_daily_at": "12:00", "display_quiet_hours": _DEFAULT_QUIET_HOURS},
    "mock": {"driver": "mock", "resolution": [800, 480], "color_mode": "1bit", "partial_refresh": True, "full_refresh_interval_seconds": 86_400, "server_full_refresh_daily_at": "12:00", "full_refresh_daily_at": "12:00", "display_quiet_hours": _DEFAULT_QUIET_HOURS},
}


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


def upgrade_default_work_layout() -> bool:
    """一次性更新已遷移的 4.26 吋預設工作頁，不觸碰任何自訂頁面或規則。"""
    from .default_layouts import waveshare_work_layout

    with _db() as con:
        done = con.execute("SELECT 1 FROM schema_metadata WHERE key=?", (_WORK_LAYOUT_UPGRADE_KEY,)).fetchone()
        if done:
            return False
        con.execute(
            "UPDATE pages SET content_json=? WHERE legacy_id='waveshare426-01_dashboard'",
            (_json(waveshare_work_layout()),),
        )
        con.execute("INSERT INTO schema_metadata(key,value) VALUES(?,?)", (_WORK_LAYOUT_UPGRADE_KEY, "1"))
        return True


def upgrade_default_mascot_interval() -> int:
    """將尚未自訂、仍使用舊 120 秒 AA 輪播的預設工作頁改為 6 秒。"""
    with _db() as con:
        done = con.execute(
            "SELECT 1 FROM schema_metadata WHERE key=?", (_WORK_LAYOUT_MASCOT_INTERVAL_UPGRADE_KEY,)
        ).fetchone()
        if done:
            return 0
        rows = con.execute(
            "SELECT id,content_json FROM pages WHERE legacy_id='waveshare426-01_dashboard'"
        ).fetchall()
        updated = 0
        for row in rows:
            content = _parse_json(row["content_json"], {})
            elements = content.get("elements") if isinstance(content, dict) else None
            if not isinstance(elements, list):
                continue
            changed = False
            for element in elements:
                if not isinstance(element, dict) or element.get("instance_id") != "mascot-work-main":
                    continue
                element_config = element.get("config")
                if not isinstance(element_config, dict):
                    continue
                # 同時符合舊預設才遷移；使用者改過任一欄位即保留原設定。
                if element.get("refresh_interval") == 120 and element_config.get("interval_seconds") == 120:
                    element["refresh_interval"] = 6
                    element_config["interval_seconds"] = 6
                    changed = True
            if changed:
                con.execute("UPDATE pages SET content_json=? WHERE id=?", (_json(content), row["id"]))
                updated += 1
        con.execute(
            "INSERT INTO schema_metadata(key,value) VALUES(?,?)",
            (_WORK_LAYOUT_MASCOT_INTERVAL_UPGRADE_KEY, str(updated)),
        )
        return updated


def upgrade_default_off_work_layout() -> int:
    """安全升級未修改過的 4.26 吋下班頁，加入可輪替的下班台詞。

    只辨識舊版的精確預設文案，避免覆寫使用者已自行排版或改字的下班頁。
    """
    from .default_layouts import waveshare_off_work_layout

    old_config = {
        "title": "今天已登出人類模式",
        "subtitle": "訊息明天再處理；現在只負責回家與放空。",
    }
    new_element = waveshare_off_work_layout()["elements"][0]
    with _db() as con:
        done = con.execute(
            "SELECT 1 FROM schema_metadata WHERE key=?", (_OFF_WORK_LAYOUT_UPGRADE_KEY,)
        ).fetchone()
        if done:
            return 0
        rows = con.execute(
            "SELECT id,content_json FROM pages WHERE legacy_id='waveshare426-01_off_work'"
        ).fetchall()
        updated = 0
        for row in rows:
            content = _parse_json(row["content_json"], {})
            elements = content.get("elements") if isinstance(content, dict) else None
            if not isinstance(elements, list):
                continue
            changed = False
            for element in elements:
                if not isinstance(element, dict):
                    continue
                if (
                    element.get("instance_id") == "off-work-notice"
                    and element.get("module_id") == "status_notice"
                    and element.get("config") == old_config
                ):
                    element["refresh_interval"] = new_element["refresh_interval"]
                    element["refresh_policy"] = new_element["refresh_policy"]
                    element["config"] = new_element["config"]
                    changed = True
            if changed:
                con.execute("UPDATE pages SET content_json=? WHERE id=?", (_json(content), row["id"]))
                updated += 1
        con.execute(
            "INSERT INTO schema_metadata(key,value) VALUES(?,?)",
            (_OFF_WORK_LAYOUT_UPGRADE_KEY, str(updated)),
        )
        return updated


def ensure_default_lunch_pages() -> dict[str, int]:
    """為既有 4.26 吋設備補建平日午休頁與規則。

    午休頁只在「上班中」且平日 12:00–13:10 套用，因此不會蓋掉請假、下班或
    假日頁。既有同名午休頁會優先沿用，避免重複建立使用者已客製的內容。
    """
    from .default_layouts import waveshare_lunch_layout

    page_name = "午休頁"
    rule_name = "平日午休（12:00–13:10）"
    result = {"pages": 0, "rules": 0}
    with _db() as con:
        done = con.execute("SELECT 1 FROM schema_metadata WHERE key=?", (_LUNCH_PAGE_UPGRADE_KEY,)).fetchone()
        if done:
            return result
        devices = con.execute(
            "SELECT id,user_id FROM devices WHERE model_id='waveshare_4in26' AND hidden=0"
        ).fetchall()
        pages_by_user: dict[str, str] = {}
        for device in devices:
            user_id = device["user_id"]
            page_id = pages_by_user.get(user_id)
            if page_id is None:
                existing = con.execute(
                    "SELECT id FROM pages WHERE user_id=? AND name=? AND template_id=? ORDER BY created_at LIMIT 1",
                    (user_id, page_name, "model:waveshare_4in26"),
                ).fetchone()
                if existing:
                    page_id = existing["id"]
                else:
                    page_id = str(uuid.uuid4())
                    con.execute(
                        "INSERT INTO pages(id,user_id,name,template_id,content_json) VALUES(?,?,?,?,?)",
                        (page_id, user_id, page_name, "model:waveshare_4in26", _json(waveshare_lunch_layout())),
                    )
                    result["pages"] += 1
                pages_by_user[user_id] = page_id
            existing_rule = con.execute(
                "SELECT 1 FROM rules WHERE device_id=? AND name=?", (device["id"], rule_name)
            ).fetchone()
            if existing_rule:
                continue
            con.execute(
                """INSERT INTO rules(id,user_id,device_id,page_id,name,priority,weekdays_json,start_time,end_time,
                                     attendance_status,holiday,enabled)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()), user_id, device["id"], page_id, rule_name, 100,
                    _json([0, 1, 2, 3, 4]), "12:00", "13:10", "working", 0, 1,
                ),
            )
            result["rules"] += 1
        con.execute("INSERT INTO schema_metadata(key,value) VALUES(?,?)", (_LUNCH_PAGE_UPGRADE_KEY, _json(result)))
    return result


def ensure_default_weekend_pages() -> dict[str, int]:
    """為既有 4.26 吋設備補建週末靜態休假頁與六日規則。"""
    from .default_layouts import waveshare_weekend_layout

    page_name = "週末休假頁"
    rule_name = "六日週休（靜態）"
    result = {"pages": 0, "rules": 0}
    with _db() as con:
        done = con.execute("SELECT 1 FROM schema_metadata WHERE key=?", (_WEEKEND_PAGE_UPGRADE_KEY,)).fetchone()
        if done:
            return result
        devices = con.execute(
            "SELECT id,user_id FROM devices WHERE model_id='waveshare_4in26' AND hidden=0"
        ).fetchall()
        pages_by_user: dict[str, str] = {}
        for device in devices:
            user_id = device["user_id"]
            page_id = pages_by_user.get(user_id)
            if page_id is None:
                existing = con.execute(
                    "SELECT id FROM pages WHERE user_id=? AND name=? AND template_id=? ORDER BY created_at LIMIT 1",
                    (user_id, page_name, "model:waveshare_4in26"),
                ).fetchone()
                if existing:
                    page_id = existing["id"]
                else:
                    page_id = str(uuid.uuid4())
                    con.execute(
                        "INSERT INTO pages(id,user_id,name,template_id,content_json) VALUES(?,?,?,?,?)",
                        (page_id, user_id, page_name, "model:waveshare_4in26", _json(waveshare_weekend_layout())),
                    )
                    result["pages"] += 1
                pages_by_user[user_id] = page_id
            if con.execute("SELECT 1 FROM rules WHERE device_id=? AND name=?", (device["id"], rule_name)).fetchone():
                continue
            con.execute(
                """INSERT INTO rules(id,user_id,device_id,page_id,name,priority,weekdays_json,enabled)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), user_id, device["id"], page_id, rule_name, 200, _json([5, 6]), 1),
            )
            result["rules"] += 1
        con.execute("INSERT INTO schema_metadata(key,value) VALUES(?,?)", (_WEEKEND_PAGE_UPGRADE_KEY, _json(result)))
    return result


def ensure_default_leave_pages() -> dict[str, int]:
    """為既有 Waveshare 設備補建全天請假頁與規則。

    不覆寫既有頁面，也不在該 Pi 已經有任一請假規則時新增另一條，避免將
    使用者已客製的請假頁變成重疊規則。4.26 與 7.5 雖同解析度，頁面仍分別綁定型號。
    """
    from .default_layouts import waveshare_leave_layout

    page_name = "全天請假頁"
    rule_name = "全天請假"
    models = ("waveshare_4in26", "waveshare_7in5_v2")
    result = {"pages": 0, "rules": 0}
    with _db() as con:
        done = con.execute("SELECT 1 FROM schema_metadata WHERE key=?", (_LEAVE_PAGE_UPGRADE_KEY,)).fetchone()
        if done:
            return result
        devices = con.execute(
            "SELECT id,user_id,model_id FROM devices WHERE model_id IN (?,?) AND hidden=0",
            models,
        ).fetchall()
        pages_by_user_model: dict[tuple[str, str], str] = {}
        for device in devices:
            existing_leave = con.execute(
                "SELECT 1 FROM rules WHERE device_id=? AND attendance_status='leave' LIMIT 1",
                (device["id"],),
            ).fetchone()
            if existing_leave:
                continue
            key = (device["user_id"], device["model_id"])
            page_id = pages_by_user_model.get(key)
            if page_id is None:
                template_id = f"model:{device['model_id']}"
                existing = con.execute(
                    "SELECT id FROM pages WHERE user_id=? AND name=? AND template_id=? ORDER BY created_at LIMIT 1",
                    (device["user_id"], page_name, template_id),
                ).fetchone()
                if existing:
                    page_id = existing["id"]
                else:
                    page_id = str(uuid.uuid4())
                    con.execute(
                        "INSERT INTO pages(id,user_id,name,template_id,content_json) VALUES(?,?,?,?,?)",
                        (page_id, device["user_id"], page_name, template_id, _json(waveshare_leave_layout())),
                    )
                    result["pages"] += 1
                pages_by_user_model[key] = page_id
            con.execute(
                """INSERT INTO rules(id,user_id,device_id,page_id,name,priority,weekdays_json,attendance_status,enabled)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), device["user_id"], device["id"], page_id, rule_name, 300, _json([]), "leave", 1),
            )
            result["rules"] += 1
        con.execute("INSERT INTO schema_metadata(key,value) VALUES(?,?)", (_LEAVE_PAGE_UPGRADE_KEY, _json(result)))
    return result


def upgrade_default_refresh_policy() -> int:
    """將尚未自訂、仍為舊 20 分鐘預設的局刷面板改為 5 小時全刷保護週期。"""
    with _db() as con:
        done = con.execute("SELECT 1 FROM schema_metadata WHERE key=?", (_REFRESH_POLICY_UPGRADE_KEY,)).fetchone()
        if done:
            return 0
        rows = con.execute("SELECT id,profile_json FROM devices").fetchall()
        updated = 0
        for row in rows:
            profile = _parse_json(row["profile_json"], {})
            if not isinstance(profile, dict) or not profile.get("partial_refresh"):
                continue
            if profile.get("full_refresh_interval_seconds", 1200) != 1200:
                continue
            profile["full_refresh_interval_seconds"] = 18_000
            con.execute("UPDATE devices SET profile_json=? WHERE id=?", (_json(profile), row["id"]))
            updated += 1
        con.execute("INSERT INTO schema_metadata(key,value) VALUES(?,?)", (_REFRESH_POLICY_UPGRADE_KEY, str(updated)))
        return updated


def upgrade_default_refresh_policy_to_daily() -> int:
    """將尚未自訂的 5 小時預設保護週期改為每日中午一次全刷。

    此判斷只處理沒有日排程標記、且仍剛好是前版預設 18,000 秒的局刷面板；
    使用者已選過其他間隔或每日時間的裝置一律保留。
    """
    with _db() as con:
        done = con.execute(
            "SELECT 1 FROM schema_metadata WHERE key=?", (_REFRESH_POLICY_DAILY_DEFAULT_UPGRADE_KEY,)
        ).fetchone()
        if done:
            return 0
        rows = con.execute("SELECT id,profile_json FROM devices").fetchall()
        updated = 0
        for row in rows:
            profile = _parse_json(row["profile_json"], {})
            if (
                not isinstance(profile, dict)
                or not profile.get("partial_refresh")
                or profile.get("full_refresh_interval_seconds") != 18_000
                or profile.get("server_full_refresh_daily_at")
                or profile.get("full_refresh_daily_at")
            ):
                continue
            profile["full_refresh_interval_seconds"] = 86_400
            profile["server_full_refresh_daily_at"] = "12:00"
            profile["full_refresh_daily_at"] = "12:00"
            con.execute("UPDATE devices SET profile_json=? WHERE id=?", (_json(profile), row["id"]))
            updated += 1
        con.execute(
            "INSERT INTO schema_metadata(key,value) VALUES(?,?)",
            (_REFRESH_POLICY_DAILY_DEFAULT_UPGRADE_KEY, str(updated)),
        )
        return updated


def upgrade_default_display_quiet_hours() -> int:
    """為既有可局刷面板補上夜間靜默時段，不覆寫使用者既有設定。"""
    with _db() as con:
        done = con.execute(
            "SELECT 1 FROM schema_metadata WHERE key=?", (_QUIET_HOURS_DEFAULT_UPGRADE_KEY,)
        ).fetchone()
        if done:
            return 0
        rows = con.execute("SELECT id,profile_json FROM devices").fetchall()
        updated = 0
        for row in rows:
            profile = _parse_json(row["profile_json"], {})
            if not isinstance(profile, dict) or not profile.get("partial_refresh"):
                continue
            if "display_quiet_hours" in profile:
                continue
            profile["display_quiet_hours"] = dict(_DEFAULT_QUIET_HOURS)
            con.execute("UPDATE devices SET profile_json=? WHERE id=?", (_json(profile), row["id"]))
            updated += 1
        con.execute(
            "INSERT INTO schema_metadata(key,value) VALUES(?,?)",
            (_QUIET_HOURS_DEFAULT_UPGRADE_KEY, str(updated)),
        )
        return updated


def upgrade_default_display_quiet_hours_weekends() -> int:
    """讓已部署第一版靜默設定的裝置，週末預設也維持靜態畫面。"""
    with _db() as con:
        done = con.execute(
            "SELECT 1 FROM schema_metadata WHERE key=?", (_QUIET_HOURS_WEEKEND_UPGRADE_KEY,)
        ).fetchone()
        if done:
            return 0
        rows = con.execute("SELECT id,profile_json FROM devices").fetchall()
        updated = 0
        for row in rows:
            profile = _parse_json(row["profile_json"], {})
            quiet_hours = profile.get("display_quiet_hours") if isinstance(profile, dict) else None
            if not isinstance(quiet_hours, dict) or "pause_weekends" in quiet_hours:
                continue
            quiet_hours = dict(quiet_hours)
            quiet_hours["pause_weekends"] = True
            profile["display_quiet_hours"] = quiet_hours
            con.execute("UPDATE devices SET profile_json=? WHERE id=?", (_json(profile), row["id"]))
            updated += 1
        con.execute(
            "INSERT INTO schema_metadata(key,value) VALUES(?,?)",
            (_QUIET_HOURS_WEEKEND_UPGRADE_KEY, str(updated)),
        )
        return updated


def user_by_id(user_id: str) -> dict | None:
    with _db() as con:
        return _row(con.execute("SELECT * FROM users WHERE id=? AND is_placeholder=0", (user_id,)).fetchone())


def user(line_sub: str) -> dict | None:
    with _db() as con:
        return _row(con.execute("SELECT * FROM users WHERE line_sub=? AND is_placeholder=0", (line_sub,)).fetchone())


def sync_owner() -> dict | None:
    """回傳 EIP 排程可安全寫入的唯一 owner。

    EIP 登入帳號是單一個人帳號；若未完成首次登入，或未來帳號模型有多位 owner，
    排程必須停止而不是猜測要覆寫誰的出勤資料。
    """
    with _db() as con:
        rows = con.execute(
            "SELECT * FROM users WHERE role='owner' AND is_placeholder=0 ORDER BY created_at, id"
        ).fetchall()
    return _row(rows[0]) if len(rows) == 1 else None


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


def _connection_state(latest: sqlite3.Row | None, now: dt.datetime | None = None) -> dict:
    """將最後一次已驗證的 Pi telemetry 轉為管理台可顯示的連線摘要。

    這不是額外 heartbeat；Pi 每次成功取得 layout 後既有的 telemetry 就是資料來源。
    reported_at 一律以 Server 接收時間為準，避免 Pi 時鐘不準造成錯誤的在線判斷。
    """
    if latest is None:
        return {"state": "unknown", "last_seen_at": None, "refresh_mode": None}
    try:
        seen_at = dt.datetime.fromisoformat(latest["reported_at"])
        if seen_at.tzinfo is None:
            seen_at = seen_at.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return {"state": "unknown", "last_seen_at": None, "refresh_mode": None}
    payload = _parse_json(latest["payload_json"], {})
    reference_time = now or dt.datetime.now(dt.timezone.utc)
    age_seconds = max(0, (reference_time - seen_at).total_seconds())
    refresh_mode = payload.get("refresh_mode") if isinstance(payload, dict) else None
    return {
        "state": "online" if age_seconds <= _ONLINE_AFTER_SECONDS else "offline",
        "last_seen_at": latest["reported_at"],
        "refresh_mode": refresh_mode if isinstance(refresh_mode, str) else None,
    }


def _latest_connections(device_ids: list[str]) -> dict[str, dict]:
    if not device_ids:
        return {}
    placeholders = ",".join("?" for _ in device_ids)
    with _db() as con:
        rows = con.execute(
            f"SELECT device_id,reported_at,payload_json FROM device_telemetry "
            f"WHERE device_id IN ({placeholders}) ORDER BY reported_at DESC",
            device_ids,
        ).fetchall()
    latest: dict[str, sqlite3.Row] = {}
    for row in rows:
        latest.setdefault(row["device_id"], row)
    now = dt.datetime.now(dt.timezone.utc)
    return {device_id: _connection_state(latest.get(device_id), now) for device_id in device_ids}


def list_devices(user_id: str, *, include_hidden: bool = True) -> list[dict]:
    sql = "SELECT * FROM devices WHERE user_id=?" + ("" if include_hidden else " AND hidden=0") + " ORDER BY name"
    with _db() as con:
        rows = con.execute(sql, (user_id,)).fetchall()
    connections = _latest_connections([row["id"] for row in rows])
    return [{**_public_device(row), "connection": connections.get(row["id"], _connection_state(None))} for row in rows]


def get_device(user_id: str, device_id: str) -> dict | None:
    with _db() as con:
        row = con.execute("SELECT * FROM devices WHERE id=? AND user_id=?", (device_id, user_id)).fetchone()
        return _public_device(row) if row else None


def _default_device_profile(model_id: str) -> dict:
    """回傳型號固定的硬體能力與可調整刷新設定的獨立副本。"""
    profile = _DEFAULT_DEVICE_PROFILES[model_id]
    result = {**profile, "resolution": list(profile["resolution"])}
    if "display_quiet_hours" in profile:
        result["display_quiet_hours"] = dict(profile["display_quiet_hours"])
    return result


def create_device(user_id: str, name: str, model_id: str, profile: dict | None = None) -> dict:
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
        raise ValueError("Pi 名稱必須為 1 至 100 個字元")
    if model_id not in MODEL_IDS:
        raise ValueError("不支援的硬體型號")
    canonical_profile = _default_device_profile(model_id)
    if profile is not None:
        if not isinstance(profile, dict):
            raise ValueError("設備 profile 必須是物件")
        changed_hardware = [field for field in _HARDWARE_PROFILE_FIELDS if field in profile and profile[field] != canonical_profile[field]]
        if changed_hardware:
            raise ValueError("硬體型號建立後不可替換 driver、解析度、色彩模式或局刷能力")
        # 僅供遷移／測試帶入非硬體設定；硬體身分始終由 model_id 決定。
        canonical_profile.update(profile)
    for field in _HARDWARE_PROFILE_FIELDS:
        canonical_profile[field] = _default_device_profile(model_id)[field]
    token, token_hash, identifier = *issue_device_token(), str(uuid.uuid4())
    with _db() as con:
        con.execute("INSERT INTO devices(id,user_id,name,model_id,profile_json,token_hash) VALUES(?,?,?,?,?,?)",
                    (identifier, user_id, name.strip(), model_id, _json(canonical_profile), token_hash))
        row = con.execute("SELECT * FROM devices WHERE id=?", (identifier,)).fetchone()
    result = _public_device(row)
    result["token"] = token  # 僅建立／重配發時回傳
    return result


def set_device_hidden(user_id: str, device_id: str, hidden: bool) -> bool:
    with _db() as con:
        return con.execute("UPDATE devices SET hidden=? WHERE id=? AND user_id=?", (int(hidden), device_id, user_id)).rowcount == 1


def update_device_refresh(user_id: str, device_id: str, refresh: Any) -> dict | None:
    """更新可局刷面板的全刷策略；設定存在 Server 的 profile_json，Pi 只接收結果。"""
    device = get_device(user_id, device_id)
    if not device:
        return None
    if not device["profile"].get("partial_refresh"):
        raise ValueError("此面板不支援局部刷新，無法設定局刷／全刷週期")
    if not isinstance(refresh, dict) or set(refresh) - {"mode", "interval_seconds", "daily_at", "quiet_hours"}:
        raise ValueError("刷新設定格式不正確")

    mode = refresh.get("mode")
    profile = dict(device["profile"])
    if mode == "interval":
        seconds = refresh.get("interval_seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, int) or not 600 <= seconds <= 86_400:
            raise ValueError("全刷間隔必須介於 10 分鐘至 24 小時")
        profile["full_refresh_interval_seconds"] = seconds
        profile.pop("server_full_refresh_daily_at", None)
        # Pi 端離線本機排程用的欄位也要一併移除，避免切回間隔模式後仍在
        # 每日舊時間額外全刷。
        profile.pop("full_refresh_daily_at", None)
    elif mode == "daily":
        daily_at = refresh.get("daily_at")
        if not isinstance(daily_at, str) or len(daily_at) != 5:
            raise ValueError("每日全刷時間必須為 HH:MM")
        try:
            dt.time.fromisoformat(daily_at)
        except ValueError as exc:
            raise ValueError("每日全刷時間必須為 HH:MM") from exc
        # 若 Server 指定的日更標記漏掉，24 小時是最後一道避免殘影長期累積的保護。
        profile["full_refresh_interval_seconds"] = 86_400
        profile["server_full_refresh_daily_at"] = daily_at
        # 新版 Pi 在沒有 API／網路時仍會保有上次取得的 profile；使用這個欄位
        # 直接在本機 tick 觸發每日全刷。server_* 欄位則保留給未升級 Pi 的
        # layout signature 相容機制。
        profile["full_refresh_daily_at"] = daily_at
    else:
        raise ValueError("刷新模式必須是 interval 或 daily")

    if "quiet_hours" in refresh:
        quiet_hours = refresh["quiet_hours"]
        required_quiet_keys = {"enabled", "start", "end"}
        if not isinstance(quiet_hours, dict) or not required_quiet_keys <= set(quiet_hours) <= required_quiet_keys | {"pause_weekends"}:
            raise ValueError("靜默時段設定格式不正確")
        if not isinstance(quiet_hours["enabled"], bool):
            raise ValueError("靜默時段啟用值不正確")
        pause_weekends = quiet_hours.get("pause_weekends", True)
        if not isinstance(pause_weekends, bool):
            raise ValueError("週末靜默啟用值不正確")
        start, end = quiet_hours["start"], quiet_hours["end"]
        if not isinstance(start, str) or not isinstance(end, str) or len(start) != 5 or len(end) != 5:
            raise ValueError("靜默時段必須為 HH:MM")
        try:
            if dt.time.fromisoformat(start) == dt.time.fromisoformat(end):
                raise ValueError("靜默開始與結束時間不可相同")
        except ValueError as exc:
            if str(exc) == "靜默開始與結束時間不可相同":
                raise
            raise ValueError("靜默時段必須為 HH:MM") from exc
        profile["display_quiet_hours"] = {
            "enabled": quiet_hours["enabled"], "start": start, "end": end, "pause_weekends": pause_weekends,
        }

    with _db() as con:
        con.execute("UPDATE devices SET profile_json=? WHERE id=? AND user_id=?", (_json(profile), device_id, user_id))
        row = con.execute("SELECT * FROM devices WHERE id=? AND user_id=?", (device_id, user_id)).fetchone()
    return _public_device(row) if row else None


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
    out["model_id"] = _page_model_id(out)
    return out


def _page_model_id(page: dict) -> str | None:
    """取得頁面所屬面板型號；舊資料則以已知 layout ID／畫布尺寸安全推斷。"""
    template_id = str(page.get("template_id") or "")
    if template_id.startswith("model:"):
        model_id = template_id.removeprefix("model:")
        return model_id if model_id in MODEL_IDS else None

    legacy_id = str(page.get("legacy_id") or "")
    if legacy_id.startswith("phat-01_"):
        return "inky_phat"
    if legacy_id.startswith("waveshare426-01_"):
        return "waveshare_4in26"

    elements = (page.get("content") or {}).get("elements", [])
    if not isinstance(elements, list) or not elements:
        return None
    try:
        right = max(int(item.get("x", 0)) + int(item.get("w", 0)) for item in elements if isinstance(item, dict))
        bottom = max(int(item.get("y", 0)) + int(item.get("h", 0)) for item in elements if isinstance(item, dict))
    except (TypeError, ValueError):
        return None
    if right <= 212 and bottom <= 104:
        return "inky_phat"
    if right <= 800 and bottom <= 480:
        return "waveshare_4in26"
    return None


def page_matches_device(page: dict, device: dict) -> bool:
    """未標記且無法推斷的舊頁面不允許新規則使用，避免跨面板錯誤顯示。"""
    return _page_model_id(page) == device.get("model_id")


def list_pages(user_id: str) -> list[dict]:
    with _db() as con:
        return [_public_page(row) for row in con.execute("SELECT * FROM pages WHERE user_id=? ORDER BY name", (user_id,))]


def get_page(user_id: str, page_id: str) -> dict | None:
    with _db() as con:
        row = con.execute("SELECT * FROM pages WHERE id=? AND user_id=?", (page_id, user_id)).fetchone()
        return _public_page(row) if row else None


def _validate_page_content(content: Any, model_id: str) -> dict:
    if not isinstance(content, dict) or not isinstance(content.get("elements", []), list):
        raise ValueError("頁面內容必須包含 elements 陣列")
    if len(content["elements"]) > 100:
        raise ValueError("單一頁面最多 100 個元件")
    resolution = _MODEL_RESOLUTIONS.get(model_id)
    if resolution is None:
        raise ValueError("頁面缺少可驗證的面板型號")
    canvas_width, canvas_height = resolution
    for index, element in enumerate(content["elements"], start=1):
        if not isinstance(element, dict):
            raise ValueError(f"第 {index} 個元件格式不正確")
        values = {key: element.get(key) for key in ("x", "y", "w", "h")}
        if any(type(value) is not int for value in values.values()):
            raise ValueError(f"第 {index} 個元件的位置與尺寸必須是整數")
        x, y, width, height = values["x"], values["y"], values["w"], values["h"]
        if x < 0 or y < 0 or width < 1 or height < 1 or x + width > canvas_width or y + height > canvas_height:
            raise ValueError(f"第 {index} 個元件超出 {canvas_width}×{canvas_height} 面板範圍")
    return content


def page_preset(model_id: str, preset: str | None) -> dict:
    """只回傳白名單中的內建版面，絕不把前端 preset 當成可執行或可任意取檔的名稱。"""
    if preset in (None, "", "blank"):
        return {"elements": []}
    if preset == "7in5_dashboard" and model_id == "waveshare_7in5_v2":
        from .default_layouts import waveshare_7in5_dashboard_layout
        return waveshare_7in5_dashboard_layout()
    raise ValueError("所選預設版面不支援此面板型號")


def create_page(user_id: str, name: str, content: Any | None = None, model_id: str | None = None) -> dict:
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
        raise ValueError("頁面名稱必須為 1 至 100 個字元")
    if model_id not in MODEL_IDS:
        raise ValueError("建立頁面時必須選擇支援的面板型號")
    identifier, content = str(uuid.uuid4()), _validate_page_content(content or {"elements": []}, model_id)
    with _db() as con:
        con.execute("INSERT INTO pages(id,user_id,name,template_id,content_json) VALUES(?,?,?,?,?)",
                    (identifier, user_id, name.strip(), f"model:{model_id}", _json(content)))
        return _public_page(con.execute("SELECT * FROM pages WHERE id=?", (identifier,)).fetchone())


def save_page(user_id: str, page_id: str, name: str, content: Any) -> dict | None:
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
        raise ValueError("頁面名稱必須為 1 至 100 個字元")
    with _db() as con:
        row = con.execute("SELECT * FROM pages WHERE id=? AND user_id=?", (page_id, user_id)).fetchone()
        if not row:
            return None
        model_id = _page_model_id(_public_page(row))
        content = _validate_page_content(content, model_id)
        con.execute("UPDATE pages SET name=?,content_json=? WHERE id=? AND user_id=?", (name.strip(), _json(content), page_id, user_id))
        return _public_page(con.execute("SELECT * FROM pages WHERE id=?", (page_id,)).fetchone())


def _validate_rule(user_id: str, data: Any) -> dict:
    if not isinstance(data, dict):
        raise ValueError("規則必須是 JSON 物件")
    device_id, page_id = data.get("device_id"), data.get("page_id")
    device = get_device(user_id, device_id) if isinstance(device_id, str) else None
    if not device:
        raise ValueError("找不到所選 Pi")
    page = get_page(user_id, page_id) if isinstance(page_id, str) else None
    if not page:
        raise ValueError("找不到所選頁面")
    if not page_matches_device(page, device):
        raise ValueError("此頁面不支援所選 Pi 的面板型號")
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


def _minutes(value: str) -> int:
    parsed = dt.time.fromisoformat(value)
    return parsed.hour * 60 + parsed.minute


def _time_ranges_overlap(left: dict, right: dict) -> bool:
    """比較可能跨午夜的規則時段；未填完整時段視為全天。"""
    def ranges(rule: dict) -> list[tuple[int, int]]:
        start, end = rule.get("start_time"), rule.get("end_time")
        if not start or not end:
            return [(0, 1440)]
        a, b = _minutes(start), _minutes(end)
        return [(a, b)] if a <= b else [(a, 1440), (0, b)]
    return any(max(a1, b1) <= min(a2, b2) for a1, a2 in ranges(left) for b1, b2 in ranges(right))


def _rules_overlap(left: dict, right: dict) -> bool:
    """判斷兩條規則是否可能在同一刻同時匹配，供 UI 與寫入驗證共用。"""
    if not left.get("enabled", True) or not right.get("enabled", True) or left.get("device_id") != right.get("device_id"):
        return False
    left_days, right_days = set(left.get("weekdays") or range(7)), set(right.get("weekdays") or range(7))
    if not left_days & right_days:
        return False
    left_status, right_status = left.get("attendance_status"), right.get("attendance_status")
    if left_status and right_status and left_status != right_status:
        return False
    left_holiday, right_holiday = left.get("holiday"), right.get("holiday")
    if left_holiday is not None and right_holiday is not None and left_holiday != right_holiday:
        return False
    return _time_ranges_overlap(left, right)


def rule_conflicts(user_id: str, candidate: dict, *, exclude_rule_id: str | None = None) -> list[dict]:
    """回傳會輸出不同頁面的重疊規則；同頁重複不需要設定優先序。"""
    conflicts = []
    for rule in list_rules(user_id):
        if rule["id"] == exclude_rule_id or rule["page_id"] == candidate["page_id"]:
            continue
        if _rules_overlap(rule, candidate):
            conflicts.append({"id": rule["id"], "name": rule["name"], "page_id": rule["page_id"], "priority": rule["priority"]})
    return conflicts


def list_rule_conflicts(user_id: str) -> list[dict]:
    rules = list_rules(user_id)
    result = []
    for index, rule in enumerate(rules):
        for other in rules[index + 1:]:
            if rule["page_id"] != other["page_id"] and _rules_overlap(rule, other):
                result.append({"left": {key: rule[key] for key in ("id", "name", "page_id", "priority")},
                               "right": {key: other[key] for key in ("id", "name", "page_id", "priority")}})
    return result


def create_rule(user_id: str, data: Any) -> dict:
    rule, identifier = _validate_rule(user_id, data), str(uuid.uuid4())
    conflicts = rule_conflicts(user_id, rule)
    if any(conflict["priority"] == rule["priority"] for conflict in conflicts):
        raise ValueError("此時段與既有規則衝突且優先序相同；請設定不同優先序")
    with _db() as con:
        con.execute("""INSERT INTO rules(id,user_id,device_id,page_id,name,priority,weekdays_json,start_time,end_time,attendance_status,holiday,enabled)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (identifier, user_id, rule["device_id"], rule["page_id"], rule["name"], rule["priority"], _json(rule["weekdays"]),
                     rule["start_time"], rule["end_time"], rule["attendance_status"], rule["holiday"], rule["enabled"]))
        return _public_rule(con.execute("SELECT * FROM rules WHERE id=?", (identifier,)).fetchone())


def update_rule(user_id: str, rule_id: str, data: Any) -> dict | None:
    rule = _validate_rule(user_id, data)
    if not any(existing["id"] == rule_id for existing in list_rules(user_id)):
        return None
    conflicts = rule_conflicts(user_id, rule, exclude_rule_id=rule_id)
    if any(conflict["priority"] == rule["priority"] for conflict in conflicts):
        raise ValueError("此時段與既有規則衝突且優先序相同；請設定不同優先序")
    with _db() as con:
        con.execute("""UPDATE rules SET device_id=?,page_id=?,name=?,priority=?,weekdays_json=?,start_time=?,end_time=?,
                       attendance_status=?,holiday=?,enabled=? WHERE id=? AND user_id=?""",
                    (rule["device_id"], rule["page_id"], rule["name"], rule["priority"], _json(rule["weekdays"]),
                     rule["start_time"], rule["end_time"], rule["attendance_status"], rule["holiday"], rule["enabled"], rule_id, user_id))
        row = con.execute("SELECT * FROM rules WHERE id=? AND user_id=?", (rule_id, user_id)).fetchone()
    return _public_rule(row) if row else None


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


def attendance_month_snapshot(user_id: str, day: dt.date, month_offset: Any = 0) -> dict:
    """回傳該帳號單月的最小出勤資料，供月曆模組安全隨 layout 下發。"""
    try:
        offset = max(-11, min(0, int(month_offset)))
    except (TypeError, ValueError):
        offset = 0
    serial = day.year * 12 + day.month - 1 + offset
    year, month = serial // 12, serial % 12 + 1
    first = dt.date(year, month, 1)
    next_month = dt.date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    with _db() as con:
        rows = con.execute(
            "SELECT day,clock_in,clock_out,on_leave FROM attendance_records WHERE user_id=? AND day>=? AND day<?",
            (user_id, first.isoformat(), next_month.isoformat()),
        ).fetchall()
    records = {}
    for row in rows:
        status = "leave" if row["on_leave"] else "off_work" if row["clock_in"] and row["clock_out"] else "working" if row["clock_in"] else "pending"
        records[str(int(str(row["day"])[-2:]))] = status
    return {"year": year, "month": month, "records": records}


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


def _effective_attendance_status(user_id: str, now: dt.datetime, holiday: bool) -> tuple[str, bool]:
    """回傳規則應使用的狀態與是否為下班保護時間的推導結果。

    這是顯示端的 fail-safe，不改寫實際打卡紀錄；隔天早上仍能正常偵測上班卡。
    """
    status = _attendance_status(user_id, now.date())
    auto_off_work = (
        not holiday
        and now.weekday() < 5
        and status in {"pending", "working"}
        and now.time() >= config.AUTO_OFF_WORK_TIME
    )
    return ("off_work" if auto_off_work else status), auto_off_work


def _resolve_device_assignment(device: dict, now: dt.datetime) -> tuple[dict | None, dict | None, str, bool, bool, list[dict]]:
    """以 Pi 實際使用的規則邏輯選出此刻應顯示的頁面。"""
    holiday = now.date().isoformat() in set(store.get_holidays())
    status, auto_off_work = _effective_attendance_status(device["user_id"], now, holiday)
    rules = [rule for rule in list_rules(device["user_id"]) if rule["device_id"] == device["id"]]
    # New edits reject same-priority overlaps. Older rules may still have one,
    # so keep the fallback deterministic and explain it in device_assignment.
    matching = sorted(
        (rule for rule in rules if _match_rule(rule, now, holiday, status)),
        key=lambda rule: (-int(rule["priority"]), rule["name"], rule["id"]),
    )
    chosen = matching[0] if matching else None
    page = get_page(device["user_id"], chosen["page_id"]) if chosen else None
    return chosen, page, status, holiday, auto_off_work, matching


def device_assignment(user_id: str, device_id: str, now: dt.datetime | None = None) -> dict | None:
    """提供管理台閱讀的設備指派摘要；資料範圍只限於該 owner。"""
    device = get_device(user_id, device_id)
    if not device:
        return None
    now = now or config.now_local()
    chosen, page, status, holiday, auto_off_work, matching = _resolve_device_assignment(device, now)
    rules = [rule for rule in list_rules(user_id) if rule["device_id"] == device_id]
    matching_ids = {rule["id"] for rule in matching}
    alternatives = [rule for rule in matching if chosen and rule["id"] != chosen["id"] and rule["page_id"] != chosen["page_id"]]
    same_priority = [rule for rule in alternatives if chosen and rule["priority"] == chosen["priority"]]
    if not chosen:
        selection_reason = "目前沒有規則同時符合日期、時段與出勤條件。"
    elif same_priority:
        selection_reason = (
            f"目前有 {len(matching)} 條規則符合；「{chosen['name']}」與 "
            f"{len(same_priority)} 條不同頁面規則優先序相同，暫以規則名稱排序。請在顯示規則修正衝突。"
        )
    elif alternatives:
        selection_reason = (
            f"目前有 {len(matching)} 條規則符合；「{chosen['name']}」的優先序 {chosen['priority']} "
            f"高於其他重疊頁面，因此套用此頁。"
        )
    elif len(matching) > 1:
        selection_reason = f"目前有 {len(matching)} 條規則符合，但都指向同一頁，不需要比較優先序。"
    else:
        selection_reason = f"目前只有「{chosen['name']}」符合日期、時段與出勤條件。"
    return {
        "device_id": device_id,
        "evaluated_at": now.isoformat(timespec="seconds"),
        "attendance_status": status,
        "attendance_status_source": "auto_off_work" if auto_off_work else "record",
        "is_holiday": holiday,
        "active_rule": None if not chosen else {
            "id": chosen["id"], "name": chosen["name"], "priority": chosen["priority"], "page_id": chosen["page_id"],
        },
        "active_page": None if not page else {"id": page["id"], "name": page["name"]},
        "selection_reason": selection_reason,
        "rules": [{
            "id": rule["id"], "name": rule["name"], "page_id": rule["page_id"], "priority": rule["priority"],
            "matches_now": rule["id"] in matching_ids,
        } for rule in rules],
    }


def _page_layout(device: dict, page: dict | None, now: dt.datetime, *, scene: str | None = None) -> dict:
    """將指定頁面轉為裝置可渲染資料；共用於 Pi layout 與管理端預覽。"""
    from .modules.registry import get_module
    elements = []
    for item in (page or {"content": {"elements": []}})["content"].get("elements", []):
        module = get_module(item.get("module_id")) if isinstance(item, dict) else None
        if not module: continue
        data: dict = {}
        if item.get("module_id") == "image":
            asset = get_asset(device["user_id"], str((item.get("config") or {}).get("asset_id", "")))
            if asset: data["filename"] = asset["filename"]
        elif item.get("module_id") in {"attendance", "clock_in_badge"}:
            # 新版 API 的 layout 必須與管理台／EIP 排程共用 SQLite 正本。舊版
            # compositor 仍可透過各模組 fetch_data() 讀舊 JSON，維持相容。
            data = attendance_snapshot(device["user_id"], now.date())
        elif item.get("module_id") == "monthly_attendance":
            data = attendance_month_snapshot(device["user_id"], now.date(), (item.get("config") or {}).get("month_offset", 0))
        else:
            try: data = module.fetch_data(item.get("config") or {})
            except Exception: data = {}
        elements.append({**item, "data": data})
    marker = _daily_refresh_marker(device["profile"], now)
    if marker:
        # 舊版 Pi 也會把 elements/config 納入 layout signature；未知模組會被安全略過，
        # 但 signature 改變仍會觸發一次全刷，不需要升級 Pi agent。
        elements.append({
            "instance_id": "_server-daily-refresh-marker",
            "module_id": "_server_refresh_marker",
            "x": 0, "y": 0, "w": 0, "h": 0, "z": -999,
            "config": {"marker": marker}, "data": {}, "refresh_policy": "auto",
        })
    return {"device_id": device["id"], "profile": device["profile"], "layout_id": page["id"] if page else None,
            "page_name": page["name"] if page else None, "scene": scene,
            "elements": elements, "resolved_at": now.isoformat(timespec="seconds")}


def _daily_refresh_marker(profile: dict, now: dt.datetime) -> str | None:
    """以排程前一日／當日的 marker 在指定時間點切換，供既有 Pi 觸發全刷。"""
    daily_at = profile.get("server_full_refresh_daily_at")
    if not isinstance(daily_at, str) or len(daily_at) != 5:
        return None
    try:
        scheduled = dt.time.fromisoformat(daily_at)
    except ValueError:
        return None
    marker_day = now.date() if now.time() >= scheduled else now.date() - dt.timedelta(days=1)
    return f"{marker_day.isoformat()}@{daily_at}"


def device_layout(device: dict, now: dt.datetime | None = None) -> dict:
    """為 token 所屬 Pi 建立版面，不透露他人裝置與素材。"""
    now = now or config.now_local()
    chosen, page, _, _, _, _ = _resolve_device_assignment(device, now)
    return _page_layout(device, page, now, scene=chosen["name"] if chosen else None)


def preview_layout(user_id: str, device_id: str, page_id: str, now: dt.datetime | None = None) -> dict | None:
    """管理者預覽指定頁面；所有 device/page 查詢都限制在同一 owner 範圍。"""
    device, page = get_device(user_id, device_id), get_page(user_id, page_id)
    if not device or not page or not page_matches_device(page, device):
        return None
    return _page_layout(device, page, now or config.now_local(), scene="預覽")


def asset_for_device(device: dict, asset_id: str) -> dict | None:
    return get_asset(device["user_id"], asset_id)


def save_telemetry(device: dict, payload: Any) -> dict:
    if not isinstance(payload, dict): raise ValueError("telemetry 必須是 JSON 物件")
    allowed = {"agent_version", "battery_percent", "uptime_seconds", "refresh_mode", "status", "reported_at"}
    if set(payload) - allowed: raise ValueError("telemetry 包含不支援欄位")
    clean: dict[str, Any] = {}
    if "agent_version" in payload:
        if not isinstance(payload["agent_version"], str) or len(payload["agent_version"]) > 64:
            raise ValueError("agent_version 格式不正確")
        clean["agent_version"] = payload["agent_version"]
    if "status" in payload:
        if payload["status"] not in {"online", "offline"}:
            raise ValueError("status 格式不正確")
        clean["status"] = payload["status"]
    if "refresh_mode" in payload:
        if payload["refresh_mode"] not in {"none", "partial", "full"}:
            raise ValueError("refresh_mode 格式不正確")
        clean["refresh_mode"] = payload["refresh_mode"]
    for key in ("battery_percent", "uptime_seconds"):
        if key not in payload:
            continue
        value = payload[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"{key} 格式不正確")
        if key == "battery_percent" and value > 100:
            raise ValueError("battery_percent 格式不正確")
        clean[key] = value
    # Pi 時鐘不一定準；連線判定只信任 Server 收到已驗證請求的時間。
    clean["reported_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    with _db() as con:
        con.execute("INSERT INTO device_telemetry(device_id,reported_at,payload_json) VALUES(?,?,?)", (device["id"], clean["reported_at"], _json(clean)))
    return clean

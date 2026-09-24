"""Docker 專用的 EIP 出勤同步排程。

這支程式必須由獨立的 attendance-sync 容器執行，而不是放進 Gunicorn worker：
避免多個 web worker 同時登入 EIP、重複寫入出勤資料。它只在工作日兩個窗口中工作：

* 08:30（含）至 10:00（不含）：尚未取得上班打卡時，每兩分鐘查詢。
* 17:50（含）至 19:30（不含）：尚未取得下班打卡時，每兩分鐘查詢。

外部網站、環境變數與子程序輸出都視為不可信。任何查詢／解析／驗證失敗都不覆寫既有
出勤資料，也不記錄帳密、網址、姓名或原始回應內容。
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import subprocess
import sys
import time
from typing import Any, Callable

from . import attendance, config, holiday_calendar, store, workspace_store

log = logging.getLogger("server.attendance_sync")

POLL_INTERVAL_SECONDS = 120
IDLE_INTERVAL_SECONDS = 30
SCRIPT_TIMEOUT_SECONDS = 90
MORNING_START = datetime.time(8, 30)
MORNING_END = datetime.time(10, 0)
EVENING_START = datetime.time(17, 50)
EVENING_END = datetime.time(19, 30)
_SCRIPT_PATH = config.BASE_DIR / "feat" / "slip" / "total.py"
_REQUIRED_EIP_ENV = ("EIP_LOGIN_URL", "LOGIN_USERNAME", "LOGIN_PASSWORD", "USER_NAME")


class AttendanceSyncError(RuntimeError):
    """可安全寫入 log 的同步錯誤；訊息絕不能帶入外部網站原始資料。"""


def is_workday(day: datetime.date, user_id: str | None = None) -> bool:
    """帳號工作日優先讀其自訂／官方行事曆；legacy 呼叫維持舊清單。"""
    holiday = holiday_calendar.is_holiday(user_id, day) if user_id else day.isoformat() in set(store.get_holidays())
    return day.weekday() < 5 and not holiday


def polling_window(now: datetime.datetime, record: dict[str, Any], user_id: str | None = None) -> str | None:
    """回傳此刻是否需要同步；已取得該時段打卡便立即停止請求。"""
    if not is_workday(now.date(), user_id) or record.get("on_leave"):
        return None
    current_time = now.time()
    if MORNING_START <= current_time < MORNING_END and not record.get("clock_in"):
        return "morning"
    if EVENING_START <= current_time < EVENING_END and not record.get("clock_out"):
        return "evening"
    return None


def _subprocess_env() -> dict[str, str]:
    """以最小環境權限傳給 Playwright 腳本，避免 API token 等其他秘密被子程序取得。"""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", "/tmp"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
    }
    browser_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if browser_path:
        env["PLAYWRIGHT_BROWSERS_PATH"] = browser_path
    for key in _REQUIRED_EIP_ENV:
        value = os.environ.get(key, "").strip()
        if not value:
            raise AttendanceSyncError(f"缺少必要環境變數：{key}")
        env[key] = value
    return env


def fetch_eip_snapshot() -> dict[str, Any]:
    """執行固定的本地腳本並驗證其 JSON 輸出，不透過 shell 執行。"""
    if not _SCRIPT_PATH.is_file():
        raise AttendanceSyncError("找不到 EIP 同步腳本")
    try:
        completed = subprocess.run(
            [sys.executable, str(_SCRIPT_PATH)],
            cwd=str(_SCRIPT_PATH.parent),
            env=_subprocess_env(),
            capture_output=True,
            text=True,
            timeout=SCRIPT_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AttendanceSyncError("EIP 查詢逾時") from exc
    except OSError as exc:
        raise AttendanceSyncError("無法啟動 EIP 同步腳本") from exc

    if completed.returncode != 0:
        raise AttendanceSyncError("EIP 同步腳本執行失敗")
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise AttendanceSyncError("EIP 同步結果不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise AttendanceSyncError("EIP 同步結果格式不正確")
    return payload


def record_from_snapshot(snapshot: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """只接受畫面所需欄位，並用 attendance 的 server-side 規則再次驗證。"""
    if not isinstance(snapshot.get("has_leave_today"), bool):
        raise AttendanceSyncError("EIP 同步結果缺少請假狀態")
    if snapshot["has_leave_today"]:
        return attendance.validate_record({
            "clock_in": None,
            "clock_out": None,
            "on_leave": True,
            "leave_note": current.get("leave_note") or "EIP 偵測到今日請假",
        })
    return attendance.validate_record({
        "clock_in": snapshot.get("clock_in") or None,
        "clock_out": snapshot.get("clock_out") or None,
        "on_leave": False,
        "leave_note": "",
    })


def _record_log_values(record: dict[str, Any]) -> tuple[str, str, bool]:
    """供使用者核對同步結果；刻意排除姓名、請假事由與所有登入資訊。"""
    return (
        record.get("clock_in") or "未打卡",
        record.get("clock_out") or "未打卡",
        bool(record.get("on_leave")),
    )


def sync_once(
    now: datetime.datetime | None = None,
    *,
    fetcher: Callable[[], dict[str, Any]] = fetch_eip_snapshot,
) -> bool:
    """需要同步且資料變更時回傳 True；不在窗口、失敗或資料相同時回傳 False。"""
    now = now or config.now_local()
    owner = workspace_store.sync_owner()
    if not owner:
        # 不猜測多使用者的 EIP 資料歸屬，也不在首次 LINE owner 尚未建立前寫入舊 JSON。
        log.warning("出勤同步未執行：找不到唯一的工作區 owner")
        return False
    current = workspace_store.attendance_snapshot(owner["id"], now.date())
    window = polling_window(now, current, owner["id"])
    if window is None:
        return False
    try:
        updated = record_from_snapshot(fetcher(), current)
    except AttendanceSyncError as exc:
        log.warning("出勤同步失敗：%s", exc)
        return False
    except (TypeError, ValueError):
        log.warning("出勤同步失敗：外部資料格式不合法")
        return False

    clock_in, clock_out, on_leave = _record_log_values(updated)
    log.info(
        "出勤同步已解析：window=%s 上班=%s 下班=%s 今日請假=%s",
        window, clock_in, clock_out, "是" if on_leave else "否",
    )
    current_payload = {key: current.get(key) for key in ("clock_in", "clock_out", "on_leave", "leave_note")}
    if updated == current_payload:
        log.info("出勤同步輸出：window=%s，資料未變更", window)
        return False
    workspace_store.save_attendance(owner["id"], now.date(), updated)
    log.info("出勤同步輸出：window=%s，已寫入出勤資料", window)
    return True


def run_forever() -> None:
    log.info("出勤同步服務啟動：morning=08:30-10:00 evening=17:50-19:30 interval=%ss", POLL_INTERVAL_SECONDS)
    while True:
        started = time.monotonic()
        now = config.now_local()
        # sync_once 內會再次確認唯一 owner、當日資料與時間窗口；若已打卡就不會
        # 發出 EIP 請求。仍維持 30 秒 idle，讓下一個窗口能即時開始。
        owner = workspace_store.sync_owner()
        if owner and is_workday(now.date(), owner["id"]) and (MORNING_START <= now.time() < MORNING_END or EVENING_START <= now.time() < EVENING_END):
            sync_once(now)
            elapsed = time.monotonic() - started
            time.sleep(max(1, POLL_INTERVAL_SECONDS - elapsed))
            continue
        time.sleep(IDLE_INTERVAL_SECONDS)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # attendance-sync 是獨立容器；不可假設 web worker 已先完成 schema 初始化。
    workspace_store.init()
    run_forever()


if __name__ == "__main__":
    main()

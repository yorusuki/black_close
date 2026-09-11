"""情境（scene）選擇邏輯：依「現在時間 + 星期 + 是否為假日」挑出目前該用哪份 layout。

一個裝置可以設定多個情境規則（見 data/scenes/<device_id>.json），
每條規則有 priority（數字越大越優先）與 condition，condition 支援：
    weekdays:   [0-6]，Monday=0 ... Sunday=6
    time_range: ["HH:MM", "HH:MM"]，需為當天區間（不支援跨午夜，跨午夜的
                "夜間" 情境請用「排除上班時段」的方式表達，見 data/scenes 範例）
    is_holiday: true/false，比對 data/holidays_tw.json 清單

condition 內的每個條件都要成立才算符合；多條規則都符合時，取 priority 最高的。
一個都不符合就退回裝置的 default_layout_id。
"""
from __future__ import annotations

import datetime

from .. import attendance, config, store


def _is_holiday(today: datetime.date) -> bool:
    return today.isoformat() in set(store.get_holidays())


def _in_time_range(now: datetime.time, time_range) -> bool:
    if not time_range:
        return True
    start = datetime.time.fromisoformat(time_range[0])
    end = datetime.time.fromisoformat(time_range[1])
    if start <= end:
        return start <= now <= end
    # 跨午夜區間
    return now >= start or now <= end


def _matches(condition: dict, now: datetime.datetime, holiday: bool) -> bool:
    if "weekdays" in condition and now.weekday() not in condition["weekdays"]:
        return False
    if "time_range" in condition and not _in_time_range(now.time(), condition["time_range"]):
        return False
    if "is_holiday" in condition and condition["is_holiday"] != holiday:
        return False
    return True


def _attendance_layout(device_id: str, now: datetime.datetime, holiday: bool) -> tuple[str, str] | None:
    """出勤顯示優先於一般情境規則。

    只有在 device profile 明確啟用時才套用，因此 pHAT 等其他裝置維持原本 scene
    行為。週末／國定假日永遠先顯示休假頁；平日有請假或上下班皆完成時則切成
    靜態全頁。下一個工作日 08:00 起，若沒有上述狀態，回到工作頁重新偵測。
    """
    device = store.get_device(device_id) or {}
    cfg = device.get("attendance_scenes")
    if not isinstance(cfg, dict):
        return None
    if holiday or now.weekday() >= 5:
        return "休假日", cfg.get("rest_layout_id")

    snapshot = attendance.get_snapshot(now.date())
    if snapshot["status"] == "leave":
        return "今日請假", cfg.get("leave_layout_id")
    if snapshot["status"] == "off_work":
        return "今日下班", cfg.get("off_work_layout_id")
    if now.time() >= datetime.time(8, 0):
        return "今日上班", cfg.get("work_layout_id")
    return None


def _selected_scene(device_id: str, now: datetime.datetime) -> tuple[str | None, str | None]:
    holiday = _is_holiday(now.date())
    attendance_scene = _attendance_layout(device_id, now, holiday)
    if attendance_scene is not None:
        return attendance_scene

    scenes = store.get_scenes(device_id)
    candidates = [s for s in scenes if _matches(s.get("condition", {}), now, holiday)]
    if candidates:
        best = max(candidates, key=lambda s: s.get("priority", 0))
        return best.get("name"), best.get("layout_id")
    device = store.get_device(device_id)
    return None, (device or {}).get("default_layout_id")


def select_layout_id(device_id: str, now: datetime.datetime | None = None) -> str | None:
    now = now or config.now_local()
    return _selected_scene(device_id, now)[1]


def active_scene_name(device_id: str, now: datetime.datetime | None = None) -> str | None:
    now = now or config.now_local()
    return _selected_scene(device_id, now)[0]

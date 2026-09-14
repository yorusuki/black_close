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

from .. import store


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


def select_layout_id(device_id: str, now: datetime.datetime | None = None) -> str | None:
    now = now or datetime.datetime.now()
    holiday = _is_holiday(now.date())

    scenes = store.get_scenes(device_id)
    candidates = [s for s in scenes if _matches(s.get("condition", {}), now, holiday)]
    if candidates:
        best = max(candidates, key=lambda s: s.get("priority", 0))
        return best.get("layout_id")

    device = store.get_device(device_id)
    return (device or {}).get("default_layout_id")


def active_scene_name(device_id: str, now: datetime.datetime | None = None) -> str | None:
    now = now or datetime.datetime.now()
    holiday = _is_holiday(now.date())
    scenes = store.get_scenes(device_id)
    candidates = [s for s in scenes if _matches(s.get("condition", {}), now, holiday)]
    if not candidates:
        return None
    return max(candidates, key=lambda s: s.get("priority", 0)).get("name")

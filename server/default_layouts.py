"""內建預設版型。

Docker 映像不會覆蓋掛載中的 data/，因此需要將可升級的預設版型放在程式碼內，
讓已完成 legacy migration 的工作區也能安全取得新版工作頁。
"""
from __future__ import annotations

from copy import deepcopy


_WAVESHARE_WORK_LAYOUT = {
    "elements": [
        {
            "instance_id": "clock_bar-top", "module_id": "clock_bar",
            "x": 0, "y": 0, "w": 800, "h": 48, "z": 10, "refresh_interval": 20,
            "config": {"time_format": "%H:%M"},
        },
        {
            "instance_id": "clock-in-small", "module_id": "clock_in_badge",
            "x": 584, "y": 60, "w": 192, "h": 64, "z": 20, "refresh_interval": 30,
            "refresh_policy": "partial", "config": {"label": "上班打卡"},
        },
        {
            "instance_id": "mascot-work-main", "module_id": "mascot",
            "x": 32, "y": 132, "w": 736, "h": 184, "z": 1, "refresh_interval": 6,
            "refresh_policy": "partial", "config": {"interval_seconds": 6},
        },
        {
            "instance_id": "workday-progress", "module_id": "progress_bar",
            "x": 96, "y": 338, "w": 608, "h": 132, "z": 1, "refresh_interval": 30,
            "refresh_policy": "partial",
            "config": {
                "title": "今日生存進度",
                "value_source": {"type": "time_progress", "start": "09:00", "end": "18:30"},
                "min": 0, "max": 100, "unit": "%",
                "footer_lines": [
                    {"text": "距離下班", "center": False},
                    {"big": True, "center": True, "value_source": {"type": "time_until", "target": "18:30"}},
                ],
            },
        },
    ],
}


_WAVESHARE_OFF_WORK_LAYOUT = {
    "elements": [
        {
            "instance_id": "off-work-notice", "module_id": "status_notice",
            "x": 0, "y": 0, "w": 800, "h": 480, "z": 1, "refresh_interval": 60,
            "refresh_policy": "partial",
            "config": {
                "title": "今天辛苦了",
                "messages": [
                    "今天的待辦，明天的我會處理。",
                    "下班打卡完成，現在開始把腦袋還給自己。",
                    "工作模式已收好，回家模式正在載入。",
                    "通知先靜音，晚餐和休息優先。",
                    "今天已盡力，剩下的留給明天。",
                    "離開座位成功，今晚不談 KPI。",
                    "下班不是逃跑，是正常結束營業。",
                    "辛苦了，現在可以安心放空。",
                ],
                "interval_seconds": 60,
            },
        },
    ],
}


_WAVESHARE_LUNCH_LAYOUT = {
    "elements": [
        {
            "instance_id": "clock-bar-lunch", "module_id": "clock_bar",
            "x": 0, "y": 0, "w": 800, "h": 48, "z": 10, "refresh_interval": 20,
            "refresh_policy": "partial", "config": {"time_format": "%H:%M"},
        },
        {
            "instance_id": "mascot-lunch-main", "module_id": "mascot",
            "x": 32, "y": 88, "w": 736, "h": 312, "z": 1, "refresh_interval": 12,
            "refresh_policy": "partial",
            "config": {
                "interval_seconds": 12,
                "frames": [
                    {"art": " /\\_/\\\n( =^.^= )\n /|___|\\", "line": "吃飯皇帝大，訊息等朕吃飽再說。"},
                    {"art": " /\\_/\\\n( o.o )\n /|___|\\", "line": "午休中：筷子優先於所有待辦。"},
                    {"art": " /\\_/\\\n( -.- ) z\n > ^ <", "line": "飯後發呆是正常的系統維護。"},
                    {"art": " /\\_/\\\n( ^.^ )\n /|___|\\", "line": "吃飽才有力氣繼續假裝很忙。"},
                    {"art": " /\\_/\\\n( =.= )\n > ^ <", "line": "會議可以等，湯冷掉不行。"},
                    {"art": " /\\_/\\\n( -_- )\n /   \\", "line": "午休剩下的時間，交給放空處理。"},
                    {"art": " /\\_/\\\n( o_o )\n > ^ <~~", "line": "已讀午餐菜單，下午再回覆工作。"},
                    {"art": " /\\_/\\\n( ^o^ )\n > ^ <", "line": "今天的 KPI：把午餐好好吃完。"},
                ],
            },
        },
    ],
}


_WAVESHARE_WEEKEND_LAYOUT = {
    "elements": [
        {
            "instance_id": "weekend-rest-notice", "module_id": "status_notice",
            "x": 0, "y": 0, "w": 800, "h": 480, "z": 1, "refresh_interval": 60,
            "refresh_policy": "partial",
            "config": {
                "title": "週末休假中",
                "messages": [
                    "週末已簽收，待辦延後處理。",
                    "今天休假，KPI 暫停營業。",
                    "週休模式啟動：不接收工作訊號。",
                    "假日合法放空中，請勿打擾。",
                    "今天不加班，連鬧鐘也請假。",
                    "週末的唯一行程：好好休息。",
                ],
                "interval_seconds": 0,
            },
        },
    ],
}


def waveshare_work_layout() -> dict:
    """回傳可安全修改的新版 4.26 吋工作頁副本。"""
    return deepcopy(_WAVESHARE_WORK_LAYOUT)


def waveshare_off_work_layout() -> dict:
    """回傳 4.26 吋下班頁的可輪播預設版型副本。"""
    return deepcopy(_WAVESHARE_OFF_WORK_LAYOUT)


def waveshare_lunch_layout() -> dict:
    """回傳 4.26 吋平日午休頁的可編輯副本。"""
    return deepcopy(_WAVESHARE_LUNCH_LAYOUT)


def waveshare_weekend_layout() -> dict:
    """回傳 4.26 吋週末靜態休假頁的可編輯副本。"""
    return deepcopy(_WAVESHARE_WEEKEND_LAYOUT)


_WAVESHARE_7IN5_DASHBOARD_LAYOUT = {
    "elements": [
        {"instance_id": "clock-bar-top", "module_id": "clock_bar", "x": 0, "y": 0, "w": 800, "h": 48, "z": 10, "refresh_interval": 20, "refresh_policy": "partial", "config": {"time_format": "%H:%M"}},
        {"instance_id": "mascot-work-main", "module_id": "mascot", "x": 24, "y": 64, "w": 432, "h": 224, "z": 1, "refresh_interval": 12, "refresh_policy": "partial", "config": {"interval_seconds": 12}},
        {"instance_id": "countdown-main", "module_id": "countdown", "x": 480, "y": 64, "w": 296, "h": 112, "z": 1, "refresh_interval": 5, "refresh_policy": "partial", "config": {"title": "下一個目標", "events": [{"label": "距離下班", "kind": "daily_time", "time": "18:30"}], "show_seconds": False}},
        {"instance_id": "attendance-month", "module_id": "monthly_attendance", "x": 480, "y": 194, "w": 296, "h": 180, "z": 1, "refresh_interval": 60, "refresh_policy": "partial", "config": {"title": "本月出勤", "month_offset": 0, "show_weekends": True, "show_summary": True}},
        {"instance_id": "todo-main", "module_id": "todo_list", "x": 24, "y": 312, "w": 432, "h": 112, "z": 1, "refresh_interval": 60, "refresh_policy": "partial", "config": {"title": "今天只做好這些", "show_completed": True, "items": [{"text": "完成最重要的一件事", "done": False}, {"text": "喝水、起身、呼吸", "done": False}]}},
        {"instance_id": "ticker-bottom", "module_id": "ticker", "x": 24, "y": 440, "w": 752, "h": 32, "z": 2, "refresh_interval": 10, "refresh_policy": "partial", "config": {"messages": ["今天也辛苦了，下一次休息值得先排進行事曆。", "記得喝水；訊息可以晚點回，人不行。"], "message_interval_seconds": 120, "scroll_step_seconds": 10, "pixels_per_step": 16}},
    ],
}


def waveshare_7in5_dashboard_layout() -> dict:
    """回傳 7.5 吋專用完整儀表板，不與 4.26 吋共用頁面。"""
    return deepcopy(_WAVESHARE_7IN5_DASHBOARD_LAYOUT)

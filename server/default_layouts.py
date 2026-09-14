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


def waveshare_work_layout() -> dict:
    """回傳可安全修改的新版 4.26 吋工作頁副本。"""
    return deepcopy(_WAVESHARE_WORK_LAYOUT)


def waveshare_off_work_layout() -> dict:
    """回傳 4.26 吋下班頁的可輪播預設版型副本。"""
    return deepcopy(_WAVESHARE_OFF_WORK_LAYOUT)

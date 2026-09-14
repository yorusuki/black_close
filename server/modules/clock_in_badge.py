"""工作頁用的精簡上班打卡時間模組。"""
from __future__ import annotations

from PIL import Image, ImageDraw

from .. import attendance
from .base import BaseModule
from .drawing import load_font, scaled_font_size


class ClockInBadgeModule(BaseModule):
    """只顯示今天的上班時間，讓工作頁保留主視覺空間。"""

    module_id = "clock_in_badge"
    category = "status"
    display_name = "上班打卡時間"
    description = "精簡顯示今日上班打卡時間；資料由出勤紀錄提供。"
    default_size = (220, 64)
    min_refresh_interval = 30
    refresh_policy = "partial"
    config_schema = [
        {"key": "label", "label": "標籤", "type": "text", "default": "上班打卡"},
        {"key": "label_scale", "label": "標籤字體大小（%）", "type": "number", "default": 100, "min": 60, "max": 200},
        {"key": "value_scale", "label": "打卡時間字體大小（%）", "type": "number", "default": 100, "min": 60, "max": 200},
    ]

    def fetch_data(self, cfg):
        # Legacy all-in-one 仍讀取既有 JSON；新版 layout API 在 workspace_store
        # 直接帶入 SQLite 正本資料，兩種模式都使用相同的 render 邏輯。
        return attendance.get_today_snapshot()

    def render(self, data, size, color_mode, cfg):
        w, h = size
        img = Image.new("RGB", size, "white")
        draw = ImageDraw.Draw(img)
        pad = max(6, int(min(w, h) * 0.10))
        label_font = load_font(scaled_font_size(h * 0.22, cfg.get("label_scale", 100), minimum=11))
        value_font = load_font(scaled_font_size(h * 0.42, cfg.get("value_scale", 100), minimum=16))

        if data.get("status") == "leave":
            value = "今日請假"
        else:
            value = data.get("clock_in") or "尚未打卡"
        draw.text((pad, pad), str(cfg.get("label") or "上班打卡"), fill="black", font=label_font)
        line_y = pad + int(h * 0.30)
        draw.line([(pad, line_y), (w - pad, line_y)], fill="black", width=1)
        value_box = draw.textbbox((0, 0), value, font=value_font)
        value_width = value_box[2] - value_box[0]
        draw.text((w - pad - value_width, h - pad - (value_box[3] - value_box[1]) - value_box[1]),
                  value, fill="black", font=value_font)
        return img

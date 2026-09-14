"""顯示今日上下班打卡與請假狀態的模組。"""
from __future__ import annotations

from PIL import Image, ImageDraw

from .. import attendance
from .base import BaseModule
from .drawing import load_font


class AttendanceModule(BaseModule):
    module_id = "attendance"
    display_name = "上下班打卡／請假"
    description = "顯示雲端儲存的今日上班、下班與請假狀態；可在編輯器右側直接更新。"
    default_size = (340, 180)
    min_refresh_interval = 30
    refresh_policy = "partial"
    config_schema = [
        {"key": "title", "label": "標題", "type": "text", "default": "上下班打卡與請假"},
    ]

    def fetch_data(self, cfg):
        return attendance.get_today_snapshot()

    def render(self, data, size, color_mode, cfg):
        w, h = size
        img = Image.new("RGB", size, "white")
        draw = ImageDraw.Draw(img)
        pad = max(8, int(min(w, h) * 0.06))
        title_font = load_font(max(13, int(h * 0.15)))
        text_font = load_font(max(12, int(h * 0.13)))
        value_font = load_font(max(15, int(h * 0.18)))
        title = cfg.get("title", "上下班打卡與請假")
        draw.text((pad, pad), title, fill="black", font=title_font)
        y = pad + int(h * 0.23)
        draw.line([(pad, y), (w - pad, y)], fill="black", width=1)
        y += max(7, int(h * 0.06))

        status = data.get("status", "pending")
        if status == "leave":
            note = data.get("leave_note") or "今日請假"
            draw.text((pad, y), "狀態", fill="black", font=text_font)
            draw.text((pad, y + int(h * 0.15)), note, fill="black", font=value_font)
            return img

        rows = [("上班", data.get("clock_in") or "尚未打卡"), ("下班", data.get("clock_out") or "尚未打卡")]
        row_h = max(1, (h - y - pad) // len(rows))
        for label, value in rows:
            draw.text((pad, y), label, fill="black", font=text_font)
            bbox = draw.textbbox((0, 0), value, font=value_font)
            draw.text((w - pad - (bbox[2] - bbox[0]), y + int(row_h * 0.08)), value, fill="black", font=value_font)
            y += row_h
        return img

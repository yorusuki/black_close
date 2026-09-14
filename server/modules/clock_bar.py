"""頂部日期/時間列，例如「2026/09/11 星期五      18:03」。"""
from __future__ import annotations

from PIL import Image, ImageDraw

from .. import config
from .base import BaseModule
from .drawing import load_font, scaled_font_size

_WEEKDAY = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


class ClockBarModule(BaseModule):
    module_id = "clock_bar"
    category = "status"
    display_name = "頂部日期時間列"
    description = "顯示星期/日期（靠左）與時間（靠右），底部有一條分隔線。"
    default_size = (800, 40)
    min_refresh_interval = 20
    refresh_policy = "partial"
    always_rerender = True
    config_schema = [
        {"key": "time_format", "label": "時間格式", "type": "text", "default": "%H:%M"},
        {"key": "font_scale", "label": "日期／時間字體大小（%）", "type": "number", "default": 100, "min": 60, "max": 200},
    ]

    def render(self, data, size, color_mode, cfg):
        w, h = size
        img = Image.new("RGB", size, "white")
        draw = ImageDraw.Draw(img)
        now = config.now_local()
        left = f"{now.strftime('%Y/%m/%d')} {_WEEKDAY[now.weekday()]}"
        right = now.strftime(cfg.get("time_format", "%H:%M"))
        font = load_font(scaled_font_size(h * 0.5, cfg.get("font_scale", 100), minimum=11))
        draw.text((4, h * 0.15), left, fill="black", font=font)
        rw = draw.textbbox((0, 0), right, font=font)[2]
        draw.text((w - rw - 4, h * 0.15), right, fill="black", font=font)
        draw.line([(0, h - 2), (w, h - 2)], fill="black", width=2)
        return img

"""低頻、局部刷新的文字跑馬燈。"""
from __future__ import annotations

import time

from PIL import Image, ImageDraw

from .base import BaseModule
from .drawing import load_font, scaled_font_size


class TickerModule(BaseModule):
    module_id = "ticker"
    category = "planning"
    display_name = "文字跑馬燈"
    description = "在自訂間隔切換提醒文字，並以可控步長向左捲動；僅支援局刷的面板建議使用。"
    default_size = (720, 36)
    min_refresh_interval = 1
    supports_partial = True
    refresh_policy = "partial"
    always_rerender = True
    config_schema = [
        {"key": "messages", "label": "跑馬燈文字", "type": "json", "editor": "messages", "default": ["記得喝水，也記得把工作留在下班後。"]},
        {"key": "message_interval_seconds", "label": "文字輪替秒數（0＝固定第一句）", "type": "number", "default": 120, "min": 0, "max": 86400, "partial_refresh_interval": True, "allow_zero": True},
        {"key": "scroll_step_seconds", "label": "捲動更新秒數", "type": "number", "default": 10, "min": 1, "max": 3600, "partial_refresh_interval": True, "help": "每次變動一次才局刷；數字越小，跑得越順也越常局刷。"},
        {"key": "pixels_per_step", "label": "每次捲動像素", "type": "number", "default": 16, "min": 0, "max": 200},
        {"key": "font_scale", "label": "字體大小（%）", "type": "number", "default": 100, "min": 60, "max": 200},
    ]

    def render(self, data, size, color_mode, cfg):
        w, h = size
        image = Image.new("RGB", size, "white")
        draw = ImageDraw.Draw(image)
        messages = [str(value).replace("\n", " ").strip()[:240] for value in cfg.get("messages", []) if isinstance(value, str) and value.strip()]
        if not messages:
            messages = ["請在管理台新增跑馬燈文字。"]
        try:
            message_interval = max(0.0, min(86400.0, float(cfg.get("message_interval_seconds", 120))))
            step_seconds = max(1.0, min(3600.0, float(cfg.get("scroll_step_seconds", 10))))
            pixels = max(0, min(200, int(cfg.get("pixels_per_step", 16))))
        except (TypeError, ValueError):
            message_interval, step_seconds, pixels = 120, 10, 16
        tick = int(time.time() // step_seconds)
        index = 0 if message_interval == 0 else int(time.time() // max(1, message_interval)) % len(messages)
        message = f"  {messages[index]}     "
        font = load_font(scaled_font_size(h * 0.55, cfg.get("font_scale", 100), minimum=9))
        text_width = max(1, int(draw.textlength(message, font=font)))
        offset = (tick * pixels) % (text_width + w) if pixels else 0
        x = w - offset
        y = max(0, (h - draw.textbbox((0, 0), message, font=font)[3]) // 2)
        draw.text((x, y), message, fill="black", font=font)
        # 補一份相同文字，讓文字完全離開左側前仍能無縫接續。
        draw.text((x + text_width + w // 4, y), message, fill="black", font=font)
        draw.line([(0, h - 1), (w, h - 1)], fill="black", width=1)
        return image

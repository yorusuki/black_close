"""靜態全頁狀態畫面，用於下班、週末與請假等不應持續刷新的場景。"""
from __future__ import annotations

from PIL import Image, ImageDraw

from .base import BaseModule
from .drawing import load_font


class StatusNoticeModule(BaseModule):
    module_id = "status_notice"
    display_name = "全頁狀態訊息"
    description = "以大字顯示靜態提示；適合下班、週末或請假頁，不會自行刷新。"
    default_size = (800, 480)
    min_refresh_interval = 300
    refresh_policy = "full"
    config_schema = [
        {"key": "title", "label": "主標題", "type": "text", "default": "今日休假 Zzz"},
        {"key": "subtitle", "label": "副標題", "type": "text", "default": "不用刷新，明天再見。"},
    ]

    def render(self, data, size, color_mode, cfg):
        w, h = size
        img = Image.new("RGB", size, "white")
        draw = ImageDraw.Draw(img)
        title = str(cfg.get("title", ""))
        subtitle = str(cfg.get("subtitle", ""))
        title_font = load_font(max(18, int(min(w, h) * 0.12)))
        subtitle_font = load_font(max(14, int(min(w, h) * 0.045)))
        title_box = draw.textbbox((0, 0), title, font=title_font)
        subtitle_box = draw.textbbox((0, 0), subtitle, font=subtitle_font)
        title_x = (w - (title_box[2] - title_box[0])) / 2
        subtitle_x = (w - (subtitle_box[2] - subtitle_box[0])) / 2
        draw.text((title_x, h * 0.36), title, fill="black", font=title_font)
        draw.line([(w * 0.2, h * 0.56), (w * 0.8, h * 0.56)], fill="black", width=max(1, h // 240))
        draw.text((subtitle_x, h * 0.63), subtitle, fill="black", font=subtitle_font)
        return img

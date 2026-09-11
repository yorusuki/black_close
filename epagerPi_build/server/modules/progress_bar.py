"""通用進度條模組：同時用來畫「今日生存進度」百分比條、「METEOR LEVEL」量表，
或任何「標題 + 數值條 + 附註文字」樣式的內容，靠 config 決定內容與數值來源。

config 範例（今日生存進度）：
{
  "title": "今日生存進度",
  "value_source": {"type": "manual", "value": 94},
  "min": 0, "max": 100, "unit": "%",
  "footer_lines": [
    {"text": "距離下班"},
    {"big": true, "value_source": {"type": "manual", "value": "00:27"}},
    {"text": "預計 18:30 解脫"}
  ]
}

config 範例（METEOR LEVEL）：
{
  "title": "☄ METEOR LEVEL",
  "value_source": {"type": "manual", "value": 6.8},
  "min": 0, "max": 10, "unit": "",
  "compact": true
}
"""
from __future__ import annotations

from PIL import Image, ImageDraw

from .base import BaseModule
from .datasource import resolve_value
from .drawing import draw_block_bar, load_font


class ProgressBarModule(BaseModule):
    module_id = "progress_bar"
    display_name = "進度條 / 量表"
    description = "標題 + 數值進度條 + 選填的附註文字列，數值可手動填或用網路請求取得。"
    default_size = (380, 160)
    min_refresh_interval = 30
    config_schema = [
        {"key": "title", "label": "標題", "type": "text", "default": "進度"},
        {"key": "value_source", "label": "數值來源", "type": "json",
         "default": {"type": "manual", "value": 50}},
        {"key": "min", "label": "最小值", "type": "number", "default": 0},
        {"key": "max", "label": "最大值", "type": "number", "default": 100},
        {"key": "unit", "label": "單位", "type": "text", "default": "%"},
        {"key": "footer_lines", "label": "附註文字列（JSON 陣列）", "type": "json", "default": []},
    ]

    def fetch_data(self, cfg):
        value = resolve_value(cfg.get("value_source"), cfg.get("min", 0))
        footer_values = []
        for line in cfg.get("footer_lines", []):
            if "value_source" in line:
                footer_values.append(resolve_value(line["value_source"], ""))
            else:
                footer_values.append(None)
        return {"value": value, "footer_values": footer_values}

    def render(self, data, size, color_mode, cfg):
        w, h = size
        img = Image.new("RGB", size, "white")
        draw = ImageDraw.Draw(img)

        title = cfg.get("title", "")
        value = data.get("value", 0)
        vmin, vmax = cfg.get("min", 0), cfg.get("max", 100)
        unit = cfg.get("unit", "")
        ratio = 0.0
        try:
            ratio = (float(value) - vmin) / (vmax - vmin) if vmax != vmin else 0.0
        except (TypeError, ValueError):
            pass

        pad = 8
        y = pad
        title_font = load_font(int(h * 0.13))
        draw.text((pad, y), title, fill="black", font=title_font)
        y += int(h * 0.20)

        bar_h = int(h * 0.16)
        draw_block_bar(draw, (pad, y), (w - pad * 2, bar_h), ratio, fg="black", bg="white")
        value_font = load_font(int(h * 0.13))
        try:
            value_text = f"{float(value):g}{unit}"
        except (TypeError, ValueError):
            value_text = f"{value}{unit}"
        draw.text((pad, y + bar_h + 4), value_text, fill="black", font=value_font)
        y += bar_h + int(h * 0.22)

        footer_lines = cfg.get("footer_lines", [])
        footer_values = data.get("footer_values", [])
        for line, fv in zip(footer_lines, footer_values):
            text = str(fv) if fv is not None else line.get("text", "")
            size_ratio = 0.22 if line.get("big") else 0.11
            f = load_font(int(h * size_ratio))
            bbox = draw.textbbox((0, 0), text, font=f)
            tw = bbox[2] - bbox[0]
            x = (w - tw) / 2 if line.get("center", True) else pad
            draw.text((x, y), text, fill="black", font=f)
            y += int(h * size_ratio) + 4

        return img

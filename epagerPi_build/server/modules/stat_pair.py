"""通用「標題 + 多列 label/value」模組：對應 mockup 的「今日出勤」「剩餘特休」「本月生存紀錄」。

config 範例：
{
  "title": "今日出勤",
  "rows": [
    {"label": "上班", "value_source": {"type": "manual", "value": "09:02"}},
    {"label": "工時", "value_source": {"type": "manual", "value": "08:31"}}
  ]
}
"""
from __future__ import annotations

from PIL import Image, ImageDraw

from .base import BaseModule
from .datasource import resolve_value
from .drawing import load_font


class StatPairModule(BaseModule):
    module_id = "stat_pair"
    display_name = "標籤/數值列表"
    description = "標題 + 一組 label/value 列，數值可手動填或用網路請求取得。"
    default_size = (260, 160)
    min_refresh_interval = 60
    config_schema = [
        {"key": "title", "label": "標題", "type": "text", "default": ""},
        {"key": "rows", "label": "資料列（JSON 陣列）", "type": "json", "default": [
            {"label": "項目", "value_source": {"type": "manual", "value": "0"}}
        ]},
    ]

    def fetch_data(self, cfg):
        values = []
        for row in cfg.get("rows", []):
            values.append(resolve_value(row.get("value_source"), ""))
        return {"values": values}

    def render(self, data, size, color_mode, cfg):
        w, h = size
        img = Image.new("RGB", size, "white")
        draw = ImageDraw.Draw(img)

        pad = 8
        y = pad
        title = cfg.get("title", "")
        if title:
            title_font = load_font(int(h * 0.11))
            draw.text((pad, y), title, fill="black", font=title_font)
            y += int(h * 0.16)
            draw.line([(pad, y), (w - pad, y)], fill="black", width=1)
            y += 6

        rows = cfg.get("rows", [])
        values = data.get("values", [])
        row_h = max(1, (h - y) // max(1, len(rows)))
        label_font = load_font(int(row_h * 0.35))
        value_font = load_font(int(row_h * 0.55))

        for row, val in zip(rows, values):
            label = row.get("label", "")
            big = row.get("big", False)
            if label:
                draw.text((pad, y), label, fill="black", font=label_font)
            value_text = f"{val}{row.get('suffix', '')}"
            vf = load_font(int(row_h * (0.75 if big else 0.55)))
            bbox = draw.textbbox((0, 0), value_text, font=vf)
            tw = bbox[2] - bbox[0]
            vx = (w - tw) / 2 if big else (w - pad - tw)
            vy = y + (row_h * 0.35 if label and not big else row_h * 0.15)
            draw.text((vx, vy), value_text, fill="black", font=vf)
            y += row_h

        return img

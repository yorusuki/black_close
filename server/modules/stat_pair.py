"""通用「標題 + 多列 label/value」模組。

config 範例：
{
  "title": "今日出勤",
  "rows": [
    {"label": "上班", "value_source": {"type": "manual", "value": "09:02"}},
    {"label": "工時", "value_source": {"type": "manual", "value": "08:31"}}
  ]
}

拆分模式下的資料流跟 progress_bar 模組一致：fetch_data() 只解析/快取 http 型別，
manual/battery/time_until/time_progress 這些本地型別留到 render() 當下即時解析
（見 progress_bar.py 開頭的說明）。
"""
from __future__ import annotations

from PIL import Image, ImageDraw

from .base import BaseModule
from .datasource import is_network_source, resolve_value
from .drawing import load_font


class StatPairModule(BaseModule):
    module_id = "stat_pair"
    category = "data"
    display_name = "標籤/數值列表"
    description = "標題 + 一組 label/value 列，數值可手動填或用網路請求取得。"
    default_size = (260, 160)
    min_refresh_interval = 60
    refresh_policy = "partial"
    config_schema = [
        {"key": "title", "label": "標題", "type": "text", "default": ""},
        {"key": "rows", "label": "資料列", "type": "json", "editor": "rows", "default": [
            {"label": "項目", "value_source": {"type": "manual", "value": "0"}}
        ]},
    ]

    def fetch_data(self, cfg):
        network_values = []
        for row in cfg.get("rows", []):
            vs = row.get("value_source")
            if is_network_source(vs):
                network_values.append(resolve_value(vs, ""))
            else:
                network_values.append(None)
        return {"network_values": network_values}

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
        network_values = data.get("network_values", [])
        row_h = max(1, (h - y) // max(1, len(rows)))
        label_font = load_font(int(row_h * 0.35))

        for i, row in enumerate(rows):
            vs = row.get("value_source")
            network_val = network_values[i] if i < len(network_values) else None
            val = network_val if is_network_source(vs) else resolve_value(vs, "")

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

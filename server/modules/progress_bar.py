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

拆分模式下的資料流（對應 docs/IMPLEMENTATION_NOTES.md「拆分模式改成樹莓派本機渲染」）：
fetch_data() 只解析 http 型別（is_network_source()==True）的 value_source，依
refresh_interval 節流快取；manual/battery/time_until/time_progress 這些本地型別
一律留到 render() 當下即時呼叫 resolve_value() 解析，不受快取節流影響，倒數計時/
生存進度條才能真的即時動。
"""
from __future__ import annotations

from PIL import Image, ImageDraw

from .base import BaseModule
from .datasource import is_network_source, resolve_value
from .drawing import draw_block_bar, load_font


def _resolve_for_render(source: dict | None, network_value, default=None):
    """render() 時用：http 型別直接吃 fetch_data() 已經解析好、節流過的值；
    其餘型別（本地就能算）在這裡即時重新解析一次。"""
    if is_network_source(source):
        return network_value if network_value is not None else default
    return resolve_value(source, default)


class ProgressBarModule(BaseModule):
    module_id = "progress_bar"
    category = "data"
    display_name = "進度條 / 量表"
    description = "標題 + 數值進度條 + 選填的附註文字列，數值可手動填或用網路請求取得。"
    default_size = (380, 160)
    min_refresh_interval = 30
    refresh_policy = "partial"
    config_schema = [
        {"key": "title", "label": "標題", "type": "text", "default": "進度"},
        {"key": "value_source", "label": "數值來源", "type": "json", "editor": "value_source",
         "default": {"type": "manual", "value": 50}},
        {"key": "min", "label": "最小值", "type": "number", "default": 0},
        {"key": "max", "label": "最大值", "type": "number", "default": 100},
        {"key": "unit", "label": "單位", "type": "text", "default": "%"},
        {"key": "footer_lines", "label": "附註文字列", "type": "json", "editor": "footer_lines", "default": []},
    ]

    def fetch_data(self, cfg):
        value_source = cfg.get("value_source")
        network_value = resolve_value(value_source, cfg.get("min", 0)) if is_network_source(value_source) else None

        footer_network_values = []
        for line in cfg.get("footer_lines", []):
            vs = line.get("value_source")
            if is_network_source(vs):
                footer_network_values.append(resolve_value(vs, ""))
            else:
                footer_network_values.append(None)

        return {"network_value": network_value, "footer_network_values": footer_network_values}

    def render(self, data, size, color_mode, cfg):
        w, h = size
        img = Image.new("RGB", size, "white")
        draw = ImageDraw.Draw(img)

        title = cfg.get("title", "")
        vmin, vmax = cfg.get("min", 0), cfg.get("max", 100)
        unit = cfg.get("unit", "")
        value = _resolve_for_render(cfg.get("value_source"), data.get("network_value"), vmin)

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
        footer_network_values = data.get("footer_network_values", [])
        for i, line in enumerate(footer_lines):
            network_val = footer_network_values[i] if i < len(footer_network_values) else None
            fv = _resolve_for_render(line.get("value_source"), network_val, None) if "value_source" in line else None
            text = str(fv) if fv is not None else line.get("text", "")
            size_ratio = 0.22 if line.get("big") else 0.11
            f = load_font(int(h * size_ratio))
            bbox = draw.textbbox((0, 0), text, font=f)
            tw = bbox[2] - bbox[0]
            x = (w - tw) / 2 if line.get("center", True) else pad
            draw.text((x, y), text, fill="black", font=f)
            y += int(h * size_ratio) + 4

        return img

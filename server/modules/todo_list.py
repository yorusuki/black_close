"""可在管理台直接編輯的待辦清單模組。"""
from __future__ import annotations

from PIL import Image, ImageDraw

from .base import BaseModule
from .drawing import load_font, scaled_font_size


def _fit_line(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    """將單行文字裁成元件可顯示的寬度，避免文字壓到核取方框。"""
    text = str(text).replace("\n", " ").strip()
    if draw.textlength(text, font=font) <= max_width:
        return text
    suffix = "…"
    while text and draw.textlength(text + suffix, font=font) > max_width:
        text = text[:-1]
    return (text + suffix) if text else suffix


class TodoListModule(BaseModule):
    module_id = "todo_list"
    category = "planning"
    display_name = "今日待辦清單"
    description = "顯示可勾選的短待辦；每列可在右側直接新增、完成或刪除。"
    default_size = (360, 144)
    min_refresh_interval = 60
    refresh_policy = "partial"
    config_schema = [
        {"key": "title", "label": "標題", "type": "text", "default": "今日待辦"},
        {
            "key": "items", "label": "待辦項目", "type": "json", "editor": "todos",
            "default": [
                {"text": "今天最重要的一件事", "done": False},
                {"text": "留一段時間給自己", "done": False},
            ],
        },
        {"key": "show_completed", "label": "顯示已完成項目", "type": "boolean", "default": True},
        {"key": "title_scale", "label": "標題字體大小（%）", "type": "number", "default": 100, "min": 60, "max": 200},
        {"key": "item_scale", "label": "項目字體大小（%）", "type": "number", "default": 100, "min": 60, "max": 200},
    ]

    def render(self, data, size, color_mode, cfg):
        w, h = size
        image = Image.new("RGB", size, "white")
        draw = ImageDraw.Draw(image)
        pad = max(5, min(w, h) // 16)
        title_font = load_font(scaled_font_size(h * 0.16, cfg.get("title_scale", 100), minimum=10))
        title = _fit_line(draw, cfg.get("title", "今日待辦"), title_font, max(1, w - pad * 2))
        draw.text((pad, pad), title, fill="black", font=title_font)
        title_h = draw.textbbox((0, 0), title, font=title_font)[3]
        y = pad + title_h + max(3, pad // 2)
        draw.line([(pad, y), (w - pad, y)], fill="black", width=1)
        y += max(4, pad)

        raw_items = cfg.get("items") if isinstance(cfg.get("items"), list) else []
        show_completed = cfg.get("show_completed", True) is not False
        items = [item for item in raw_items if isinstance(item, dict) and str(item.get("text", "")).strip()]
        if not show_completed:
            items = [item for item in items if not item.get("done")]
        items = items[:12]
        if not items:
            empty_font = load_font(max(9, int(h * 0.13)))
            draw.text((pad, y), "暫無待辦，先讓腦袋放空。", fill="black", font=empty_font)
            return image

        row_h = max(14, (h - y - pad) // len(items))
        item_font = load_font(scaled_font_size(row_h * 0.55, cfg.get("item_scale", 100), minimum=8))
        box = max(8, min(row_h - 3, int(h * 0.12)))
        for item in items:
            done = bool(item.get("done"))
            box_y = y + max(0, (row_h - box) // 2)
            draw.rectangle((pad, box_y, pad + box, box_y + box), outline="black", width=1)
            if done:
                draw.line((pad + 2, box_y + box // 2, pad + box // 2, box_y + box - 2), fill="black", width=1)
                draw.line((pad + box // 2, box_y + box - 2, pad + box - 2, box_y + 2), fill="black", width=1)
            text = _fit_line(draw, item.get("text", ""), item_font, max(1, w - pad * 3 - box))
            text_y = y + max(0, (row_h - draw.textbbox((0, 0), text, font=item_font)[3]) // 2)
            draw.text((pad * 2 + box, text_y), text, fill="black", font=item_font)
            if done:
                text_w = draw.textlength(text, font=item_font)
                draw.line((pad * 2 + box, text_y + row_h * 0.55, pad * 2 + box + text_w, text_y + row_h * 0.55), fill="black", width=1)
            y += row_h
        return image

"""全頁狀態畫面，用於下班、週末與請假等場景。"""
from __future__ import annotations

import time

from PIL import Image, ImageDraw

from .base import BaseModule
from .drawing import load_font


_DEFAULT_OFF_WORK_MESSAGES = [
    "今天的待辦，明天的我會處理。",
    "下班打卡完成，現在開始把腦袋還給自己。",
    "工作模式已收好，回家模式正在載入。",
    "通知先靜音，晚餐和休息優先。",
    "今天已盡力，剩下的留給明天。",
    "離開座位成功，今晚不談 KPI。",
    "下班不是逃跑，是正常結束營業。",
    "辛苦了，現在可以安心放空。",
]


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    """以實際字寬換行，讓下班台詞不會溢出面板。"""
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        line = ""
        for char in paragraph:
            candidate = line + char
            if line and draw.textlength(candidate, font=font) > max_width:
                lines.append(line)
                line = char
            else:
                line = candidate
        lines.append(line)
    return "\n".join(lines)


def _fitted_text(draw: ImageDraw.ImageDraw, text: str, desired_size: int, max_width: int, max_height: int):
    """將自訂台詞縮放並換行至可安全顯示的範圍。"""
    for size in range(max(12, desired_size), 11, -1):
        font = load_font(size)
        wrapped = _wrap_text(draw, text, font, max_width)
        box = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=5)
        if box[2] - box[0] <= max_width and box[3] - box[1] <= max_height:
            return font, wrapped, box
    font = load_font(12)
    wrapped = _wrap_text(draw, text, font, max_width)
    return font, wrapped, draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=5)


def _messages(cfg: dict) -> list[str]:
    """相容舊 subtitle；新頁面才使用可輪替的 messages。"""
    raw_messages = cfg.get("messages")
    if isinstance(raw_messages, list):
        # 限制渲染工作量；UI 可管理多句，顯示端只需安全使用前 30 句。
        messages = [str(item).strip()[:160] for item in raw_messages if isinstance(item, str) and item.strip()]
        if messages:
            return messages[:30]
    subtitle = str(cfg.get("subtitle") or "").strip()
    return [subtitle] if subtitle else _DEFAULT_OFF_WORK_MESSAGES


class StatusNoticeModule(BaseModule):
    module_id = "status_notice"
    category = "status"
    display_name = "全頁狀態訊息"
    description = "以大字顯示下班、週末或請假提示；下班頁可選擇輪播多句台詞。"
    default_size = (800, 480)
    min_refresh_interval = 5
    supports_partial = True
    refresh_policy = "partial"
    always_rerender = True
    config_schema = [
        {"key": "title", "label": "主標題", "type": "text", "default": "今天辛苦了"},
        {
            "key": "messages", "label": "下班輪替台詞", "type": "json", "editor": "messages",
            "default": _DEFAULT_OFF_WORK_MESSAGES,
        },
        {
            "key": "interval_seconds", "label": "台詞輪替／局刷間隔（秒）", "type": "number",
            "default": 60, "min": 5, "max": 3600,
            "help": "下班頁有多句台詞時，依此秒數換一句並優先局刷；全刷仍遵循設備的保護週期。",
        },
    ]

    def render(self, data, size, color_mode, cfg):
        w, h = size
        img = Image.new("RGB", size, "white")
        draw = ImageDraw.Draw(img)
        title = str(cfg.get("title", ""))
        messages = _messages(cfg)
        try:
            interval = max(5, min(3600, int(cfg.get("interval_seconds", 60))))
        except (TypeError, ValueError):
            interval = 60
        subtitle = messages[int(time.time() // interval) % len(messages)]
        title_font = load_font(max(18, int(min(w, h) * 0.12)))
        title_box = draw.textbbox((0, 0), title, font=title_font)
        title_x = (w - (title_box[2] - title_box[0])) / 2
        subtitle_font, subtitle_text, subtitle_box = _fitted_text(
            draw, subtitle, max(14, int(min(w, h) * 0.052)), int(w * 0.76), int(h * 0.18)
        )
        subtitle_width = subtitle_box[2] - subtitle_box[0]
        subtitle_height = subtitle_box[3] - subtitle_box[1]
        subtitle_x = (w - subtitle_width) / 2 - subtitle_box[0]
        subtitle_y = h * 0.63 + max(0, (h * 0.18 - subtitle_height) / 2) - subtitle_box[1]
        draw.text((title_x, h * 0.36), title, fill="black", font=title_font)
        draw.line([(w * 0.2, h * 0.56), (w * 0.8, h * 0.56)], fill="black", width=max(1, h // 240))
        draw.multiline_text((subtitle_x, subtitle_y), subtitle_text, fill="black", font=subtitle_font, spacing=5)
        return img

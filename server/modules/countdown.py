"""本機時間計算的倒數模組，不依賴 Server 輪詢。"""
from __future__ import annotations

import datetime as dt

from PIL import Image, ImageDraw

from .. import config
from .base import BaseModule
from .drawing import load_font, scaled_font_size
from .workday import clock_in_target, fallback_target


def _next_event(events: list, now: dt.datetime, attendance: dict | None = None):
    candidates = []
    for event in events[:12]:
        if not isinstance(event, dict):
            continue
        label = str(event.get("label", "")).strip()[:60]
        kind = event.get("kind")
        try:
            if kind == "daily_time":
                target_time = dt.time.fromisoformat(str(event.get("time", "")))
                target = dt.datetime.combine(now.date(), target_time, tzinfo=now.tzinfo)
                if target <= now:
                    target += dt.timedelta(days=1)
            elif kind == "date_time":
                target = dt.datetime.fromisoformat(str(event.get("datetime", "")))
                if target.tzinfo is None:
                    target = target.replace(tzinfo=now.tzinfo)
                else:
                    target = target.astimezone(now.tzinfo)
                if target <= now:
                    continue
            elif kind == "attendance_workday":
                target = clock_in_target(attendance, now, event.get("work_minutes", 541))
                if target is None:
                    target = fallback_target(now, event.get("fallback_time", "18:30"))
                if target is None:
                    continue
            else:
                continue
        except (TypeError, ValueError):
            continue
        candidates.append((target, label or "下一個目標"))
    return min(candidates, default=None, key=lambda entry: entry[0])


def _fit(draw: ImageDraw.ImageDraw, text: str, desired: int, width: int):
    for size in range(max(8, desired), 7, -1):
        font = load_font(size)
        if draw.textlength(text, font=font) <= width:
            return font
    return load_font(8)


class CountdownModule(BaseModule):
    module_id = "countdown"
    category = "planning"
    display_name = "事件倒數"
    description = "倒數至每天固定時間或指定日期時間；由 Pi 本機時間計算，離線仍可更新。"
    default_size = (280, 112)
    min_refresh_interval = 1
    supports_partial = True
    refresh_policy = "partial"
    always_rerender = True
    config_schema = [
        {"key": "title", "label": "標題", "type": "text", "default": "下一個目標"},
        {
            "key": "events", "label": "倒數事件", "type": "json", "editor": "countdowns",
            "default": [{"label": "距離下班", "kind": "attendance_workday", "work_minutes": 541, "fallback_time": "18:30"}],
        },
        {"key": "show_seconds", "label": "顯示秒數（會增加局刷頻率）", "type": "boolean", "default": False},
        {"key": "title_scale", "label": "標題字體大小（%）", "type": "number", "default": 100, "min": 60, "max": 200},
        {"key": "value_scale", "label": "倒數字體大小（%）", "type": "number", "default": 100, "min": 60, "max": 200},
    ]

    def render(self, data, size, color_mode, cfg):
        w, h = size
        image = Image.new("RGB", size, "white")
        draw = ImageDraw.Draw(image)
        pad = max(5, min(w, h) // 16)
        now = config.now_local()
        event = _next_event(cfg.get("events") if isinstance(cfg.get("events"), list) else [], now, data.get("attendance"))
        title = str(cfg.get("title", "下一個目標")).strip() or "下一個目標"
        title_font = _fit(draw, title, scaled_font_size(h * 0.17, cfg.get("title_scale", 100), minimum=9), w - pad * 2)
        draw.text((pad, pad), title, fill="black", font=title_font)
        y = pad + draw.textbbox((0, 0), title, font=title_font)[3] + max(3, pad // 2)
        draw.line([(pad, y), (w - pad, y)], fill="black", width=1)
        if event is None:
            font = load_font(max(9, int(h * 0.16)))
            draw.text((pad, y + pad), "請新增一個未到期的事件", fill="black", font=font)
            return image
        target, label = event
        remaining = max(0, int((target - now).total_seconds()))
        days, remainder = divmod(remaining, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        value = f"{days}天 {hours:02d}:{minutes:02d}" if days else f"{hours:02d}:{minutes:02d}"
        if cfg.get("show_seconds"):
            value += f":{seconds:02d}"
        label_font = _fit(draw, label, max(8, int(h * 0.15)), w - pad * 2)
        value_font = _fit(draw, value, scaled_font_size(h * 0.31, cfg.get("value_scale", 100), minimum=12), w - pad * 2)
        draw.text((pad, y + pad), label, fill="black", font=label_font)
        value_y = h - pad - draw.textbbox((0, 0), value, font=value_font)[3]
        draw.text((pad, max(y + pad + draw.textbbox((0, 0), label, font=label_font)[3], value_y)), value, fill="black", font=value_font)
        return image

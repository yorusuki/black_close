"""黑白月曆式出勤熱圖。資料由 Server 隨 layout 下發，Pi 離線仍可顯示最後資料。"""
from __future__ import annotations

import calendar
import datetime as dt

from PIL import Image, ImageDraw

from .. import config
from .base import BaseModule
from .drawing import load_font, scaled_font_size


_WEEKDAYS = "一二三四五六日"


def _month_with_offset(now: dt.date, offset) -> tuple[int, int]:
    try:
        offset = max(-11, min(0, int(offset)))
    except (TypeError, ValueError):
        offset = 0
    serial = now.year * 12 + now.month - 1 + offset
    return serial // 12, serial % 12 + 1


class MonthlyAttendanceModule(BaseModule):
    module_id = "monthly_attendance"
    category = "planning"
    display_name = "本月出勤熱圖"
    description = "以黑白月曆顯示完成下班、上班中與請假；資料由 Server 隨版面安全下發。"
    default_size = (280, 176)
    min_refresh_interval = 60
    refresh_policy = "partial"
    config_schema = [
        {"key": "title", "label": "標題", "type": "text", "default": "本月出勤"},
        {"key": "month_offset", "label": "月份（0＝本月，-1＝上月）", "type": "number", "default": 0, "min": -11, "max": 0},
        {"key": "show_weekends", "label": "標示週末格", "type": "boolean", "default": True},
        {"key": "show_summary", "label": "顯示出勤摘要", "type": "boolean", "default": True},
        {"key": "font_scale", "label": "字體大小（%）", "type": "number", "default": 100, "min": 60, "max": 200},
    ]

    def render(self, data, size, color_mode, cfg):
        w, h = size
        image = Image.new("RGB", size, "white")
        draw = ImageDraw.Draw(image)
        pad = max(4, min(w, h) // 24)
        today = config.now_local().date()
        year, month = _month_with_offset(today, cfg.get("month_offset", 0))
        if isinstance(data, dict) and data.get("year") == year and data.get("month") == month:
            records = data.get("records", {})
        else:
            records = {}
        if not isinstance(records, dict):
            records = {}
        holidays = data.get("holidays", {}) if isinstance(data, dict) and data.get("year") == year and data.get("month") == month else {}
        if not isinstance(holidays, dict):
            holidays = {}
        title = str(cfg.get("title", "本月出勤")).strip() or "本月出勤"
        title_font = load_font(scaled_font_size(h * 0.12, cfg.get("font_scale", 100), minimum=8))
        draw.text((pad, pad), title, fill="black", font=title_font)
        month_text = f"{year}/{month:02d}"
        month_font = load_font(max(8, int(h * 0.10)))
        month_w = draw.textlength(month_text, font=month_font)
        draw.text((w - pad - month_w, pad), month_text, fill="black", font=month_font)
        header_h = max(12, int(h * 0.14))
        grid_y = pad + header_h
        summary_h = max(14, int(h * 0.13)) if cfg.get("show_summary", True) else 0
        cell_w = max(1, (w - pad * 2) // 7)
        weeks = calendar.monthcalendar(year, month)
        cell_h = max(1, (h - grid_y - pad - summary_h) // (len(weeks) + 1))
        label_font = load_font(max(6, int(cell_h * 0.45)))
        day_font = load_font(max(7, int(cell_h * 0.52)))
        for column, weekday in enumerate(_WEEKDAYS):
            label_w = draw.textlength(weekday, font=label_font)
            draw.text((pad + column * cell_w + (cell_w - label_w) / 2, grid_y), weekday, fill="black", font=label_font)
        grid_y += cell_h
        counts = {"off_work": 0, "working": 0, "leave": 0}
        holiday_counts = {"national": 0, "manual": 0}
        for row, week in enumerate(weeks):
            for column, day in enumerate(week):
                if not day:
                    continue
                x, y = pad + column * cell_w, grid_y + row * cell_h
                weekend = column >= 5
                status = records.get(str(day), "pending")
                holiday = holidays.get(str(day), {})
                holiday_kind = holiday.get("kind") if isinstance(holiday, dict) else None
                if holiday_kind in holiday_counts:
                    holiday_counts[holiday_kind] += 1
                if status in counts:
                    counts[status] += 1
                if weekend and cfg.get("show_weekends", True):
                    draw.rectangle((x, y, x + cell_w - 1, y + cell_h - 1), fill="#eeeeee")
                draw.rectangle((x, y, x + cell_w - 1, y + cell_h - 1), outline="black", width=1)
                number_color = "white" if status == "off_work" else "black"
                if status == "off_work":
                    draw.rectangle((x + 1, y + 1, x + cell_w - 2, y + cell_h - 2), fill="black")
                elif status == "leave":
                    draw.line((x + 2, y + 2, x + cell_w - 3, y + cell_h - 3), fill="black", width=1)
                    draw.line((x + cell_w - 3, y + 2, x + 2, y + cell_h - 3), fill="black", width=1)
                elif status == "working":
                    draw.ellipse((x + cell_w * .58, y + cell_h * .58, x + cell_w - 3, y + cell_h - 3), fill="black")
                number = str(day)
                draw.text((x + 2, y + 1), number, fill=number_color, font=day_font)
                # 右上角以小標籤區分國定假日與自訂休假；不覆蓋出勤底色與日期數字。
                if holiday_kind in ("national", "manual"):
                    badge = "國" if holiday_kind == "national" else "休"
                    badge_font = load_font(max(6, min(9, int(cell_h * 0.34))))
                    badge_w = max(8, int(draw.textlength(badge, font=badge_font) + 3))
                    badge_h = max(8, int(cell_h * 0.38))
                    bx = x + cell_w - badge_w - 1
                    by = y + 1
                    if bx > x + 2 and by + badge_h < y + cell_h - 1:
                        if holiday_kind == "national":
                            draw.rectangle((bx, by, bx + badge_w, by + badge_h), fill="black")
                            draw.text((bx + 1, by), badge, fill="white", font=badge_font)
                        else:
                            draw.rectangle((bx, by, bx + badge_w, by + badge_h), outline="black", width=1)
                            draw.text((bx + 1, by), badge, fill="black", font=badge_font)
        if summary_h:
            summary = f"完成 {counts['off_work']} · 上班中 {counts['working']} · 請假 {counts['leave']} · 國 {holiday_counts['national']} · 休 {holiday_counts['manual']}"
            summary_font = load_font(max(7, int(summary_h * 0.55)))
            # 極小尺寸時截字，確保不會壓出模組邊界。
            while summary and draw.textlength(summary, font=summary_font) > w - pad * 2:
                summary = summary[:-1]
            draw.text((pad, h - pad - summary_h + 2), summary, fill="black", font=summary_font)
        return image

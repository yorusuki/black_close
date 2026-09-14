"""AA 吉祥物模組：在數個「AA 人物 + 台詞」影格之間輪播，可做動畫。

電子紙的動畫必須遵守裝置刷新能力：模組雖支援局部刷新，但 Inky pHAT 等
只能整幅刷新的面板仍會跟著裝置的整幅刷新間隔更新，不會為了動畫頻繁全刷。
"""
from __future__ import annotations

import time

from PIL import Image, ImageDraw

from .base import BaseModule
from .drawing import load_font, scaled_font_size


_DEFAULT_FRAMES = [
    {"art": " /\\_/\\\n( o.o )\n > ^ <", "line": "打卡完成，貓貓的靈魂還在載入。"},
    {"art": " /\\_/\\\n( -.- ) z\n > ^ <", "line": "今天先當一隻安靜連線的貓。"},
    {"art": " /\\_/\\\n( O.O )\n > ^ <", "line": "會議開始了，耳朵先收起來。"},
    {"art": " /\\_/\\\n( o.o )\n /  |  \\", "line": "咖啡到位，現在勉強願意工作。"},
    {"art": " /\\_/\\\n( =.= )\n > ^ <", "line": "待辦清單正在靠近，先假裝沒看見。"},
    {"art": " /\\_/\\\n( ^.^ )\n > ^ <", "line": "已讀訊息，接著看窗外五分鐘。"},
    {"art": " /\\_/\\\n( -_- )\n /|   |\\", "line": "午休結束，貓窩模式關閉。"},
    {"art": " /\\_/\\\n( o.o )\n > ^ <~~", "line": "再一封信，就再甩一次尾巴。"},
    {"art": " /\\_/\\\n( >.< )\n > ^ <", "line": "不是拖延，是正在把鍵盤壓暖。"},
    {"art": " /\\_/\\\n( =^.^= )\n (\")_(\")", "line": "下班時間到了，貓已經在門邊集合。"},
    {"art": " /\\_/\\\n( -.- )\n > ^ <", "line": "星期一的貓：請勿靠近，會哈氣。"},
    {"art": " /\\_/\\\n( o_o )\n /|___|\\", "line": "需求可以慢慢講，貓正在整理鬍鬚。"},
    {"art": " /\\_/\\\n( ^o^ )\n > ^ <", "line": "今天也很努力地假裝自己不想睡。"},
    {"art": " /\\_/\\\n( ._. )\n > ^ <", "line": "請把我加入 CC，讓貓假裝參與。"},
    {"art": " /\\_/\\\n( -.- )\n /   \\", "line": "先對著空白表格伸個懶腰。"},
    {"art": " /\\_/\\\n( ^.^ )\n > ^ <", "line": "週五的貓仍在營業，請輕聲催促。"},
]


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    """依實際字寬換行；中文沒有空白分詞時仍能安全處理。"""
    if max_width < 1:
        return text
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


def _fit_text_block(draw: ImageDraw.ImageDraw, text: str, desired_size: int, max_width: int,
                    max_height: int, spacing: int, minimum: int = 8):
    """回傳可放進指定區域的 font、換行文字與 bbox；最小字仍由呼叫端安全裁切。"""
    for size in range(max(minimum, desired_size), minimum - 1, -1):
        font = load_font(size)
        wrapped = _wrap_text(draw, text, font, max_width)
        box = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=spacing)
        if box[2] - box[0] <= max_width and box[3] - box[1] <= max_height:
            return font, wrapped, box
    font = load_font(minimum)
    wrapped = _wrap_text(draw, text, font, max_width)
    return font, wrapped, draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=spacing)


class MascotModule(BaseModule):
    module_id = "mascot"
    category = "visual"
    display_name = "AA 人物吉祥物"
    description = "在多組「多行 AA 人物 + 台詞」之間輪播，可做成簡易動畫（實際刷新頻率受裝置局部刷新能力限制）。"
    default_size = (800, 150)
    min_refresh_interval = 5
    supports_partial = True
    refresh_policy = "partial"
    always_rerender = True
    config_schema = [
        {"key": "frames", "label": "影格", "type": "json", "editor": "frames", "default": _DEFAULT_FRAMES},
        {
            "key": "interval_seconds", "label": "AA 輪播／局刷間隔（秒）", "type": "number",
            "default": 6, "min": 1, "max": 3600,
            "help": "設定 6 代表 AA 最多每 6 秒換一格並局刷一次；Inky 等不支援局刷的面板不適用。",
        },
        {"key": "art_scale", "label": "AA 人物字體大小（%）", "type": "number", "default": 100, "min": 60, "max": 200},
        {"key": "line_scale", "label": "語錄字體大小（%）", "type": "number", "default": 100, "min": 60, "max": 200},
    ]

    def render(self, data, size, color_mode, cfg):
        w, h = size
        frames = cfg.get("frames") or _DEFAULT_FRAMES
        if not isinstance(frames, list) or not frames:
            frames = _DEFAULT_FRAMES
        # config 可能由舊版頁面或 API 輸入，不能只信任管理台的 min/max。
        interval = max(1, min(3600, int(cfg.get("interval_seconds", 6))))
        frame = frames[int(time.time() // interval) % len(frames)]
        if not isinstance(frame, dict):
            frame = {}

        img = Image.new("RGB", size, "white")
        draw = ImageDraw.Draw(img)
        # art 是新版的多行人物欄位；face 保留給既有版面，不會因升級而消失。
        art = str(frame.get("art") or frame.get("face") or "")
        line = f"「{frame.get('line', '')}」"
        pad, gap = max(8, int(min(w, h) * 0.06)), 12
        inner_width, inner_height = max(1, w - pad * 2), max(1, h - pad * 2)
        art_size = scaled_font_size(h * 0.20, cfg.get("art_scale", 100), minimum=13)
        line_size = scaled_font_size(h * 0.22, cfg.get("line_scale", 100), minimum=13)

        # 先嘗試左右配置：人物維持原本的視覺比重，台詞依剩餘寬度換行與縮字。
        art_font, art_text, art_box = _fit_text_block(draw, art, art_size, inner_width, inner_height, spacing=2)
        art_width, art_height = art_box[2] - art_box[0], art_box[3] - art_box[1]
        line_width_limit = inner_width - art_width - gap
        if art and line_width_limit >= 96:
            line_font, line_text, line_box = _fit_text_block(
                draw, line, line_size, line_width_limit, inner_height, spacing=4
            )
            line_width, line_height = line_box[2] - line_box[0], line_box[3] - line_box[1]
            if art_height <= inner_height and line_height <= inner_height:
                art_x, art_y = pad, pad + (inner_height - art_height) // 2 - art_box[1]
                line_x, line_y = art_x + art_width + gap, pad + (inner_height - line_height) // 2 - line_box[1]
                draw.multiline_text((art_x, art_y), art_text, fill="black", font=art_font, spacing=2)
                draw.multiline_text((line_x, line_y), line_text, fill="black", font=line_font, spacing=4)
                return img

        # 無法左右並排時，明確切成兩個垂直安全區。人物與台詞各自在自己的
        # 高度內縮字／換行，因此即使 AA 很寬或台詞很長也不會互相重疊。
        art_area_height = max(1, int((inner_height - gap) * 0.58))
        line_area_height = max(1, inner_height - gap - art_area_height)
        art_font, art_text, art_box = _fit_text_block(draw, art, art_size, inner_width, art_area_height, spacing=2)
        line_font, line_text, line_box = _fit_text_block(draw, line, line_size, inner_width, line_area_height, spacing=4)
        art_width, art_height = art_box[2] - art_box[0], art_box[3] - art_box[1]
        line_width, line_height = line_box[2] - line_box[0], line_box[3] - line_box[1]
        art_x = pad + max(0, (inner_width - art_width) // 2)
        art_y = pad + max(0, (art_area_height - art_height) // 2) - art_box[1]
        line_x = pad + max(0, (inner_width - line_width) // 2)
        line_y = pad + art_area_height + gap + max(0, (line_area_height - line_height) // 2) - line_box[1]
        draw.multiline_text((art_x, art_y), art_text, fill="black", font=art_font, spacing=2)
        draw.multiline_text((line_x, line_y), line_text, fill="black", font=line_font, spacing=4)
        return img

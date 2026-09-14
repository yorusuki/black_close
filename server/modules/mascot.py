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
    {"art": "  _(:3 」∠)_\n   |   |\n  _| |_ ", "line": "打卡完成，靈魂還在載入……"},
    {"art": "  ( -_- )\n   |   |\n  _| |_ ", "line": "今天的我：已連線，未回應。"},
    {"art": "  (╯°□°）╯︵ ┻━┻\n  ┬─┬ ノ( º _ ºノ)", "line": "會議開始了，時間開始失去意義。"},
    {"art": "  ( ´･ω･ )\n   | ☕ |\n  _| |_ ", "line": "咖啡不是飲料，是生命延長線。"},
    {"art": "  ＼(°o°)／\n     | \n    _|_ ", "line": "待辦清單比我的電量還長。"},
    {"art": "  (・_・)\n   |   |\n  _| |_ ", "line": "正在努力把「收到」打得像有在做事。"},
    {"art": "  (＾ω＾)\n   |   | >>\n  _| |_ ", "line": "午休結束，快樂也一起結束。"},
    {"art": "  (´･_･)\n   |   |\n  _| |_ ", "line": "再一封信，我就再喝一口水。"},
    {"art": "  ヽ(´∀｀)ﾉ\n    | | \n   _| |_ ", "line": "我不是拖延，我是在等待靈感上班。"},
    {"art": "  (ゝ´∀｀)ノ\n   |   | ->\n  _| |_ ", "line": "下班時間到了，理智先走一步。"},
    {"art": "  (´･ω･)\n   |   |\n  _| |_ ", "line": "星期一不是日子，是天氣災害。"},
    {"art": "  └(´･ω･)┘\n    | | \n   _| |_ ", "line": "需求可以慢慢說，我的靈魂已下線。"},
    {"art": "  (´∀｀)つ\n   |   |\n  _| |_ ", "line": "今天也很努力地假裝從容。"},
    {"art": "  (・ω・)ノ\n   |   |\n  _| |_ ", "line": "請把我加入 CC，讓我假裝參與。"},
    {"art": "  _(:з 」∠)_\n     | \n    _|_ ", "line": "等一下，讓我先對著空白表格發呆。"},
    {"art": "  (≧▽≦)\n   |   |\n  _| |_ ", "line": "週五的我：仍在營業，請勿催促。"},
]


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
        {"key": "interval_seconds", "label": "輪播間隔秒數（僅支援局部刷新的裝置生效）", "type": "number", "default": 5},
        {"key": "art_scale", "label": "AA 人物字體大小（%）", "type": "number", "default": 100, "min": 60, "max": 200},
        {"key": "line_scale", "label": "語錄字體大小（%）", "type": "number", "default": 100, "min": 60, "max": 200},
    ]

    def render(self, data, size, color_mode, cfg):
        w, h = size
        frames = cfg.get("frames") or _DEFAULT_FRAMES
        if not isinstance(frames, list) or not frames:
            frames = _DEFAULT_FRAMES
        interval = max(1, int(cfg.get("interval_seconds", 5)))
        frame = frames[int(time.time() // interval) % len(frames)]
        if not isinstance(frame, dict):
            frame = {}

        img = Image.new("RGB", size, "white")
        draw = ImageDraw.Draw(img)
        art_font = load_font(scaled_font_size(h * 0.20, cfg.get("art_scale", 100), minimum=13))
        line_font = load_font(scaled_font_size(h * 0.22, cfg.get("line_scale", 100), minimum=13))

        # art 是新版的多行人物欄位；face 保留給既有版面，不會因升級而消失。
        art = str(frame.get("art") or frame.get("face") or "")
        art_box = draw.multiline_textbbox((0, 0), art, font=art_font, spacing=2)
        art_width, art_height = art_box[2] - art_box[0], art_box[3] - art_box[1]
        art_x = 16
        art_y = max(4, (h - art_height) // 2 - art_box[1])
        draw.multiline_text((art_x, art_y), art, fill="black", font=art_font, spacing=2)

        line = f"「{frame.get('line', '')}」"
        line_box = draw.multiline_textbbox((0, 0), line, font=line_font, spacing=4)
        line_width, line_height = line_box[2] - line_box[0], line_box[3] - line_box[1]
        # 大型 AA 人物太寬時，台詞改放在下方，避免超出電子紙畫面。
        if art_width + 56 + line_width <= w:
            line_x = art_x + art_width + 40
            line_y = max(4, (h - line_height) // 2 - line_box[1])
        else:
            line_x = 16
            line_y = max(4, h - line_height - 8 - line_box[1])
        draw.multiline_text((line_x, line_y), line, fill="black", font=line_font, spacing=4)
        return img

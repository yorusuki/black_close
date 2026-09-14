"""AA 表情吉祥物模組：在數個「表情 + 台詞」影格之間輪播，可做動畫。

⚠ 動畫刷新的實際限制（很重要，避免燒到電子紙）：
  - 這個模組宣告 supports_partial=True，代表「如果裝置支援局部刷新，可以只刷這個
    模組的區域、頻率可以比整幅刷新快」。
  - 但只有 device profile 裡 partial_refresh=true 的裝置（目前規劃是未來的微雪 4.26"）
    才會真的用 interval_seconds 這麼快的頻率刷新。
  - 在 Inky pHAT 這類「只能整幅刷新」的裝置上，compositor 會忽略 interval_seconds，
    改成跟著該裝置設定的最短整幅刷新間隔一起更新（見 render/compositor.py），
    不會為了動畫去頻繁整幅刷新面板。

影格用「目前時間 // interval_seconds」直接算出來，模組本身不需要保存狀態，
所以 render() 可以每個 tick 都被呼叫也沒問題（便宜、不用額外的排程資料結構）。
"""
from __future__ import annotations

import time

from PIL import Image, ImageDraw

from .base import BaseModule
from .drawing import load_font

_DEFAULT_FRAMES = [
    {"face": "( ´･ω･`)", "line": "拜託不要在 18:29 開新需求。"},
    {"face": "(￣ω￣;)", "line": "再撐一下就可以了。"},
    {"face": "(´・_・`)", "line": "會議是不會結束的幻覺。"},
]


class MascotModule(BaseModule):
    module_id = "mascot"
    category = "visual"
    display_name = "AA 表情吉祥物"
    description = "在多組「表情 + 台詞」之間輪播，可做成動畫（實際刷新頻率受裝置局部刷新能力限制）。"
    default_size = (800, 60)
    min_refresh_interval = 5
    supports_partial = True
    refresh_policy = "partial"
    always_rerender = True
    config_schema = [
        {"key": "frames", "label": "影格", "type": "json", "editor": "frames",
         "default": _DEFAULT_FRAMES},
        {"key": "interval_seconds", "label": "輪播間隔秒數（僅支援局部刷新的裝置生效）",
         "type": "number", "default": 5},
    ]

    def render(self, data, size, color_mode, cfg):
        w, h = size
        frames = cfg.get("frames") or _DEFAULT_FRAMES
        interval = max(1, cfg.get("interval_seconds", 5))
        idx = int(time.time() // interval) % len(frames)
        frame = frames[idx]

        img = Image.new("RGB", size, "white")
        draw = ImageDraw.Draw(img)
        face_font = load_font(int(h * 0.55))
        line_font = load_font(int(h * 0.30))

        face = frame.get("face", "")
        fb = draw.textbbox((0, 0), face, font=face_font)
        fw = fb[2] - fb[0]
        draw.text((16, (h - (fb[3] - fb[1])) / 2 - fb[1]), face, fill="black", font=face_font)

        line = f"「{frame.get('line', '')}」"
        lb = draw.textbbox((0, 0), line, font=line_font)
        lx = fw + 40
        draw.text((lx, (h - (lb[3] - lb[1])) / 2 - lb[1]), line, fill="black", font=line_font)
        return img

"""模組共用的繪圖小工具：字型載入（含中文）與方塊進度條繪製。

已知限制：Noto Sans CJK 不含大部分 emoji/符號（如 ☄），config 裡的文字用到這類字元
會變成方塊（tofu）。要顯示裝飾符號，建議用一般標點或字母（* / » /★ 視實際字型
涵蓋範圍而定），或另外裝一套 emoji 字型再擴充 _FONT_CANDIDATES／改成多字型合成繪製
（PIL 單一 ImageFont 物件不會自動跨字型 fallback，要混用需要自己依字元分段換字型）。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import ImageDraw, ImageFont

# 依序嘗試的字型路徑（Debian/Raspberry Pi OS 上 `apt install fonts-noto-cjk` 後即可用中文；
# 找不到就退回內建的等寬英文字型，中文會顯示不出來但不會整個 crash）。
_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]


@lru_cache(maxsize=64)
def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def draw_block_bar(draw: ImageDraw.ImageDraw, xy, wh, ratio: float, fg, bg) -> None:
    """畫一條用方塊字元風格呈現的水平進度條（實心矩形＋外框，視覺上對應 mockup 的 █░ 風格）。"""
    x, y = xy
    w, h = wh
    ratio = max(0.0, min(1.0, ratio))
    draw.rectangle([x, y, x + w, y + h], outline=fg, width=1)
    fill_w = int((w - 2) * ratio)
    if fill_w > 0:
        draw.rectangle([x + 1, y + 1, x + 1 + fill_w, y + h - 1], fill=fg)


def text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]

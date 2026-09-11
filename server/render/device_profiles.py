"""裝置 profile 讀取，以及依裝置色彩模式做的畫面量化（給預覽/實際輸出共用）。"""
from __future__ import annotations

from PIL import Image

from .. import store

_ACCENT_RGB = {
    "red": (190, 30, 30),
    "yellow": (230, 200, 40),
}


def get_profile(device_id: str) -> dict | None:
    return store.get_device(device_id)


def _palette_image(flat_palette: list[int]) -> Image.Image:
    pal_img = Image.new("P", (1, 1))
    palette = list(flat_palette) + [0] * (768 - len(flat_palette))
    pal_img.putpalette(palette)
    return pal_img


def quantize(img: Image.Image, profile: dict) -> Image.Image:
    """依裝置色彩模式量化畫面：3色（含跳色網點）/4階灰階/純黑白。

    回傳的仍是 RGB 圖（方便預覽直接存 PNG），實際要送進面板前，
    device_agent 的驅動程式會再各自轉成面板需要的 bit-packed buffer。
    """
    color_mode = profile.get("color_mode", "1bit")
    rgb = img.convert("RGB")

    if color_mode == "3color":
        accent = _ACCENT_RGB.get(profile.get("accent_color", "red"), _ACCENT_RGB["red"])
        pal = [255, 255, 255, 0, 0, 0, *accent]
        pal_img = _palette_image(pal)
        return rgb.quantize(palette=pal_img, dither=Image.FLOYDSTEINBERG).convert("RGB")

    if color_mode == "4gray":
        # 這四個值（0x00/0x80/0xC0/0xFF）刻意對齊微雪官方 epd4in26.py 的
        # getbuffer_4Gray()：它是靠「像素值剛好等於這幾個特定值」來分組，
        # 不是均分灰階，用其他等分值（如 0/85/170/255）餵進去會分組錯誤。
        levels = [0x00, 0x80, 0xC0, 0xFF]
        pal = []
        for level in levels:
            pal += [level, level, level]
        pal_img = _palette_image(pal)
        return rgb.quantize(palette=pal_img, dither=Image.FLOYDSTEINBERG).convert("RGB")

    # 1bit：純黑白，開 Floyd-Steinberg 網點模擬灰階觀感
    return rgb.convert("1").convert("RGB")

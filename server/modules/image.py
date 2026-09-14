"""圖片模組：顯示素材庫裡的一張圖片，依 fit 模式縮放/裁切填滿元件範圍。

config：{"asset_id": "...", "fit": "cover"|"contain"|"stretch"}

拆分模式下的設計重點（對應 docs/IMPLEMENTATION_NOTES.md「圖片素材庫」章節）：
fetch_data() 只查本機 assets.json 拿目前的檔名（這一步查的是本機索引檔，不是網路
請求，但因為 assets.json 只存在伺服器端，所以拆分模式下這步驟自然會在
resolve_layout_elements()「伺服器端」那個階段執行，把檔名資訊透過 layout-data
帶給樹莓派）；render() 一律讀本機檔案（樹莓派上就是 device_agent 的
sync_assets() 同步下來的那份），圖片還沒同步到時顯示「圖片下載中…」佔位框，
不會讓整個模組壞掉。
"""
from __future__ import annotations

from PIL import Image, ImageDraw

from .. import assets as asset_store
from .. import config
from .base import BaseModule
from .drawing import load_font


class ImageModule(BaseModule):
    module_id = "image"
    display_name = "圖片"
    description = "顯示素材庫裡的一張圖片（先在編輯器的「圖片素材庫」面板上傳）。"
    default_size = (160, 160)
    min_refresh_interval = 300
    refresh_policy = "full"
    config_schema = [
        {"key": "asset_id", "label": "素材 ID（從圖片素材庫面板點選）", "type": "text", "default": ""},
        {"key": "fit", "label": "填滿方式（cover/contain/stretch）", "type": "text", "default": "cover"},
    ]

    def fetch_data(self, cfg):
        asset_id = cfg.get("asset_id")
        if not asset_id:
            return {}
        record = asset_store.get_asset(asset_id)
        if record is None:
            return {}
        return {"filename": record["filename"]}

    def _placeholder(self, size, text: str) -> Image.Image:
        w, h = size
        img = Image.new("RGB", size, "white")
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, w - 1, h - 1], outline="black")
        font = load_font(max(9, int(min(w, h) * 0.12)))
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((max(0, (w - tw) / 2), max(0, (h - th) / 2)), text, fill="black", font=font)
        return img

    def render(self, data, size, color_mode, cfg):
        w, h = size
        asset_id = cfg.get("asset_id")
        if not asset_id:
            return self._placeholder(size, "（未選擇圖片）")

        filename = (data or {}).get("filename")
        if not filename:
            return self._placeholder(size, "（找不到素材，請確認素材庫還在）")

        path = config.DATA_DIR / "assets" / filename
        if not path.exists():
            return self._placeholder(size, "圖片下載中…")

        try:
            img = Image.open(path).convert("RGB")
        except Exception:
            return self._placeholder(size, "圖片讀取失敗")

        fit = cfg.get("fit", "cover")
        if fit == "stretch":
            return img.resize(size)

        src_ratio = img.width / img.height
        dst_ratio = w / h

        if fit == "contain":
            if src_ratio > dst_ratio:
                new_w, new_h = w, max(1, round(w / src_ratio))
            else:
                new_h, new_w = h, max(1, round(h * src_ratio))
            resized = img.resize((new_w, new_h))
            canvas = Image.new("RGB", size, "white")
            canvas.paste(resized, ((w - new_w) // 2, (h - new_h) // 2))
            return canvas

        # cover（預設）：等比例縮放後置中裁切填滿
        if src_ratio > dst_ratio:
            new_h, new_w = h, max(1, round(h * src_ratio))
        else:
            new_w, new_h = w, max(1, round(w / src_ratio))
        resized = img.resize((new_w, new_h))
        left = (new_w - w) // 2
        top = (new_h - h) // 2
        return resized.crop((left, top, left + w, top + h))

"""圖片模組：顯示素材庫裡的一張圖片，依 fit 模式縮放/裁切填滿元件範圍。

config：{"asset_id": "...", "fit": "cover"|"contain"|"stretch",
         "animation_interval_seconds": 0|安全下限以上秒數}

拆分模式下的設計重點（對應 docs/IMPLEMENTATION_NOTES.md「圖片素材庫」章節）：
fetch_data() 只查本機 assets.json 拿目前的檔名（這一步查的是本機索引檔，不是網路
請求，但因為 assets.json 只存在伺服器端，所以拆分模式下這步驟自然會在
resolve_layout_elements()「伺服器端」那個階段執行，把檔名資訊透過 layout-data
帶給樹莓派）；render() 一律讀本機檔案（樹莓派上就是 device_agent 的
sync_assets() 同步下來的那份），圖片還沒同步到時顯示「圖片下載中…」佔位框，
不會讓整個模組壞掉。
"""
from __future__ import annotations

import time
from pathlib import Path

from PIL import Image, ImageDraw

from .. import assets as asset_store
from .. import config
from .base import BaseModule
from .drawing import load_font


class ImageModule(BaseModule):
    module_id = "image"
    category = "visual"
    display_name = "圖片"
    description = "顯示圖庫圖片；GIF／動態 WebP 會依影格播放（受面板局刷安全下限限制）。"
    default_size = (160, 160)
    min_refresh_interval = 300
    supports_partial = True
    # 靜態圖片不會改變；動態圖片在 render() 依時間挑選安全同步完成的影格。同位置
    # 替換圖片或播放影格都可完整覆蓋這個元素範圍，無須為此觸發整幅閃爍。
    refresh_policy = "partial"
    config_schema = [
        {"key": "asset_id", "label": "圖庫圖片", "type": "asset", "default": "", "help": "在下拉選單挑選目前帳號的圖庫圖片；圖庫頁可預覽、上傳或刪除。"},
        {"key": "fit", "label": "填滿方式（cover/contain/stretch）", "type": "text", "default": "cover"},
        {"key": "animation_interval_seconds", "label": "GIF 影格切換秒數（0＝依原始 GIF）", "type": "number", "default": 0, "min": 0, "max": 3600, "partial_refresh_interval": True, "allow_zero": True, "zero_help": "0 代表依 GIF／動態 WebP 的原始影格延遲。", "help": "0 會使用 GIF／動態 WebP 的原始影格延遲；任何設定都會受面板安全局刷下限限制。靜態圖片不受此設定影響。"},
    ]

    def fetch_data(self, cfg):
        asset_id = cfg.get("asset_id")
        if not asset_id:
            return {}
        record = asset_store.get_asset(asset_id)
        if record is None:
            return {}
        animation = asset_store.animation_info(record)
        return {"filename": record["filename"], "animation": animation} if animation.get("animated") else {"filename": record["filename"]}

    @staticmethod
    def _animation_filename(data: dict, cfg: dict) -> str | None:
        animation = data.get("animation") if isinstance(data, dict) else None
        if not isinstance(animation, dict) or animation.get("animated") is not True:
            return None
        frames = animation.get("frames")
        if not isinstance(frames, list) or not frames:
            return None
        clean: list[tuple[str, int]] = []
        for frame in frames:
            if not isinstance(frame, dict):
                return None
            filename, duration = frame.get("filename"), frame.get("duration_ms")
            if not isinstance(filename, str) or not filename or Path(filename).name != filename or filename in {".", ".."}:
                return None
            if not isinstance(duration, int) or not 20 <= duration <= 10_000:
                return None
            clean.append((filename, duration))
        try:
            override = float(cfg.get("animation_interval_seconds", 0))
        except (TypeError, ValueError):
            override = 0
        now_ms = int(time.time() * 1000)
        if override > 0:
            return clean[int(now_ms // max(1, round(override * 1000))) % len(clean)][0]
        cycle = sum(duration for _, duration in clean)
        position = now_ms % cycle
        elapsed = 0
        for filename, duration in clean:
            elapsed += duration
            if position < elapsed:
                return filename
        return clean[-1][0]

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

        filename = self._animation_filename(data or {}, cfg) or (data or {}).get("filename")
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

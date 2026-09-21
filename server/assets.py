"""圖片素材庫的驗證、正規化、內容去重與實體檔案保存。

使用者上傳的原始檔案不是直接提供給 Pi。Server 會先驗證、轉正方向、移除不需要的
動畫影格／透明通道、縮小到足以覆蓋目前最大面板兩倍的解析度，再在 lossless PNG 與
高品質 JPEG 間選擇較合適的版本。實體檔名由正規化後內容的 SHA-256 決定，因此同一張
圖片不會重複佔用磁碟；工作區圖庫的去重由 ``workspace_store`` 以 digest 處理。

GIF 目前只保留第一張影格：電子紙沒有連續播放的能力，保留動畫檔只會增加傳輸與快取
成本，並且與既有圖片模組「顯示首影格」的行為一致。
"""
from __future__ import annotations

import hashlib
import io
import os
import tempfile
import time
import uuid
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from . import config, store


ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
MAX_UPLOAD_BYTES = 30 * 1024 * 1024
# 防止解壓縮炸彈；此值遠高於 800×480 面板實際所需，仍能容納一般手機照片。
MAX_SOURCE_PIXELS = 40_000_000
# 最大裝置目前是 800×480。保留兩倍長邊可讓裁切與日後小幅調整仍清楚，卻不讓 Pi
# 下載手機原圖。
MAX_STORED_EDGE = 1600


def assets_dir() -> Path:
    directory = config.DATA_DIR / "assets"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def assets_index_path() -> Path:
    return config.DATA_DIR / "assets.json"


def list_assets() -> list[dict]:
    return store.read_json(assets_index_path(), [])


def _save_index(items: list[dict]) -> None:
    store.write_json(assets_index_path(), items)


def get_asset(asset_id: str) -> dict | None:
    for item in list_assets():
        if item["id"] == asset_id:
            return item
    return None


def asset_file_path(asset: dict) -> Path:
    filename = asset.get("filename")
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise ValueError("素材檔名不正確")
    return assets_dir() / filename


def _read_and_normalize(original_filename: str, content: bytes) -> Image.Image:
    """回傳可安全儲存的 RGB 首影格。

    透明像素以白色合成，符合目前黑白電子紙與 compositor 的白底行為；不會在 Pi 端
    因為 PNG alpha 值產生與預覽不同的結果。
    """
    source_ext = Path(original_filename).suffix.lower()
    if source_ext not in ALLOWED_EXTENSIONS:
        raise ValueError("只允許 PNG、JPG、GIF、BMP 或 WebP 圖片")
    if not content:
        raise ValueError("素材檔案不可為空")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("素材檔案不可超過 30MB")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as verified:
                verified.verify()
            # verify() 後該 image 不能再讀取，所以重新開啟再完整載入像素。
            with Image.open(io.BytesIO(content)) as source:
                if source.width * source.height > MAX_SOURCE_PIXELS:
                    raise ValueError("圖片像素數過大，請縮小後再上傳")
                source.seek(0)  # GIF/WebP 動畫一律只保留第一影格。
                normalized = ImageOps.exif_transpose(source)
                if normalized.mode in {"RGBA", "LA"} or "transparency" in normalized.info:
                    rgba = normalized.convert("RGBA")
                    canvas = Image.new("RGBA", rgba.size, "white")
                    canvas.alpha_composite(rgba)
                    normalized = canvas.convert("RGB")
                else:
                    normalized = normalized.convert("RGB")
                normalized.load()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("圖片像素數過大，請縮小後再上傳") from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        if isinstance(exc, ValueError) and "圖片像素數過大" in str(exc):
            raise
        raise ValueError("上傳內容不是有效圖片") from exc

    if max(normalized.size) > MAX_STORED_EDGE:
        ratio = MAX_STORED_EDGE / max(normalized.size)
        normalized = normalized.resize(
            (max(1, round(normalized.width * ratio)), max(1, round(normalized.height * ratio))),
            Image.Resampling.LANCZOS,
        )
    return normalized


def _encode(image: Image.Image) -> tuple[bytes, str, str]:
    """先試無損 PNG；只有 JPEG 節省超過 10% 才犧牲極少細節。"""
    png = io.BytesIO()
    image.save(png, format="PNG", optimize=True, compress_level=9)
    jpeg = io.BytesIO()
    image.save(jpeg, format="JPEG", quality=92, optimize=True, progressive=True, subsampling=0)
    png_bytes, jpeg_bytes = png.getvalue(), jpeg.getvalue()
    if len(jpeg_bytes) < len(png_bytes) * 0.9:
        return jpeg_bytes, ".jpg", "image/jpeg"
    return png_bytes, ".png", "image/png"


def _write_canonical_file(filename: str, body: bytes) -> None:
    """以原子替換建立實體檔；相同 digest 的既有檔案不重寫。"""
    destination = asset_file_path({"filename": filename})
    if destination.is_file():
        return
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=assets_dir(), prefix=f".{filename}.", suffix=".tmp", delete=False) as temporary:
            temporary_name = temporary.name
            temporary.write(body)
            temporary.flush()
            os.fsync(temporary.fileno())
        # 在同一個 assets 目錄內 replace 才是原子的。另一個請求已寫入相同檔時，
        # 覆寫內容也完全相同（digest 相同），因此不會造成資料錯置。
        os.replace(temporary_name, destination)
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def prepare_asset(original_filename: str, content: bytes) -> dict:
    """正規化並保存實體檔，回傳尚未加入圖庫索引的 record。"""
    image = _read_and_normalize(original_filename, content)
    body, extension, mime_type = _encode(image)
    digest = hashlib.sha256(body).hexdigest()
    filename = f"image_{digest}{extension}"
    _write_canonical_file(filename, body)

    # id 是工作區圖庫項目的穩定識別碼；hash 是跨上傳去重、快取和檔名用的內容識別。
    asset_id = uuid.uuid4().hex[:12]
    record = {
        "id": asset_id,
        "filename": filename,
        "original_filename": Path(original_filename).name or "upload",
        "hash": digest,
        "size": len(body),
        "mime_type": mime_type,
        "uploaded_at": time.time(),
        "source_size": len(content),
        "width": image.width,
        "height": image.height,
    }
    return record


def register_asset(record: dict) -> None:
    """將已驗證的素材加入 legacy 索引，供 server 解析圖片模組檔名。"""
    items = list_assets()
    if not any(item.get("id") == record.get("id") for item in items):
        items.append(record)
    _save_index(items)


def save_asset(original_filename: str, content: bytes) -> dict:
    """legacy API 相容入口：準備素材後立即登錄圖庫索引。"""
    record = prepare_asset(original_filename, content)
    register_asset(record)
    return record


def delete_asset(asset_id: str) -> bool:
    """刪除 legacy 索引項目，不直接刪除去重後可能被其他工作區使用的實體檔。"""
    items = list_assets()
    keep = [asset for asset in items if asset["id"] != asset_id]
    if len(keep) == len(items):
        return False
    _save_index(keep)
    return True

"""圖片素材庫的驗證、正規化、內容去重與實體檔案保存。

使用者上傳的原始檔案不是直接提供給 Pi。Server 會先驗證、轉正方向、移除透明通道、
縮小到電子紙足夠使用的解析度，再在 lossless PNG 與高品質 JPEG 間選擇較合適的版本。
實體檔名由正規化後內容的 SHA-256 決定，因此同一張圖片不會重複佔用磁碟；工作區圖庫
的去重由 ``workspace_store`` 以 digest 處理。

GIF／動態 WebP 會安全拆成有限張已正規化的影格。資料庫不需要保存動畫欄位：動畫
manifest 以素材 digest 命名，Pi 只會在所有影格下載並驗證成功後才套用新版面。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
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
# 動態素材是給 800×480 等級的電子紙使用；限制影格數、邊長與總輸出量，避免使用者上傳
# 極短延遲的大 GIF 佔滿 Server/Pi 磁碟。播放速度仍會由 Pi compositor 的硬體下限節流。
MAX_ANIMATION_FRAMES = 24
MAX_ANIMATION_EDGE = 800
MAX_ANIMATION_BYTES = 30 * 1024 * 1024
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


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
    if not isinstance(filename, str) or Path(filename).name != filename or filename in {".", ".."}:
        raise ValueError("素材檔名不正確")
    return assets_dir() / filename


def _normalize_image(image: Image.Image, max_edge: int) -> Image.Image:
    """轉成白底 RGB 並限制長邊，回傳可安全保存的獨立像素資料。"""
    normalized = ImageOps.exif_transpose(image)
    if normalized.mode in {"RGBA", "LA"} or "transparency" in normalized.info:
        rgba = normalized.convert("RGBA")
        canvas = Image.new("RGBA", rgba.size, "white")
        canvas.alpha_composite(rgba)
        normalized = canvas.convert("RGB")
    else:
        normalized = normalized.convert("RGB")
    normalized.load()
    if max(normalized.size) > max_edge:
        ratio = max_edge / max(normalized.size)
        normalized = normalized.resize(
            (max(1, round(normalized.width * ratio)), max(1, round(normalized.height * ratio))),
            Image.Resampling.LANCZOS,
        )
    return normalized


def _decode_frames(original_filename: str, content: bytes) -> tuple[list[tuple[Image.Image, int]], bool]:
    """驗證來源並回傳首幀或有限動畫影格。

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
                frame_count = int(getattr(source, "n_frames", 1) or 1)
                animated = bool(getattr(source, "is_animated", False) and frame_count > 1)
                if animated and frame_count > MAX_ANIMATION_FRAMES:
                    raise ValueError(f"動畫最多只能有 {MAX_ANIMATION_FRAMES} 個影格")
                if animated and source.width * source.height * frame_count > MAX_SOURCE_PIXELS:
                    raise ValueError("圖片像素數過大，請縮小後再上傳")
                frames: list[tuple[Image.Image, int]] = []
                for index in range(frame_count if animated else 1):
                    source.seek(index)
                    # 0ms 在 GIF 很常見，不能讓它變成無限高頻刷新；保留原始意圖但至少
                    # 20ms。真正輸出仍由面板安全局刷下限控制。
                    duration = source.info.get("duration", 100)
                    try:
                        duration_ms = max(20, min(10_000, int(duration)))
                    except (TypeError, ValueError):
                        duration_ms = 100
                    frames.append((_normalize_image(source, MAX_ANIMATION_EDGE if animated else MAX_STORED_EDGE), duration_ms))
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("圖片像素數過大，請縮小後再上傳") from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        if isinstance(exc, ValueError) and ("圖片像素數過大" in str(exc) or "動畫最多" in str(exc)):
            raise
        raise ValueError("上傳內容不是有效圖片") from exc

    return frames, animated


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


def _manifest_path(digest: str) -> Path:
    if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
        raise ValueError("動畫素材識別碼不正確")
    return assets_dir() / f"animation_{digest}.json"


def _write_manifest(digest: str, manifest: dict) -> None:
    """在影格都落盤後才原子公布 manifest，避免 Pi 取得半套動畫。"""
    destination = _manifest_path(digest)
    body = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=assets_dir(), prefix=f".{destination.name}.", suffix=".tmp", delete=False) as temporary:
            temporary_name = temporary.name
            temporary.write(body)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, destination)
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def _animation_digest(frames: list[tuple[bytes, str, str, int]]) -> str:
    digest = hashlib.sha256()
    for body, extension, mime_type, duration_ms in frames:
        digest.update(duration_ms.to_bytes(4, "big"))
        digest.update(extension.encode("ascii"))
        digest.update(mime_type.encode("ascii"))
        digest.update(len(body).to_bytes(8, "big"))
        digest.update(body)
    return digest.hexdigest()


def _valid_animation_manifest(value: object, digest: str) -> dict | None:
    if not isinstance(value, dict) or value.get("version") != 1 or value.get("digest") != digest:
        return None
    frames = value.get("frames")
    if not isinstance(frames, list) or not 2 <= len(frames) <= MAX_ANIMATION_FRAMES:
        return None
    clean: list[dict] = []
    for frame in frames:
        if not isinstance(frame, dict):
            return None
        filename, duration = frame.get("filename"), frame.get("duration_ms")
        if not isinstance(filename, str) or Path(filename).name != filename or not filename.startswith(f"animation_{digest}_"):
            return None
        if not isinstance(duration, int) or not 20 <= duration <= 10_000:
            return None
        clean.append({"filename": filename, "duration_ms": duration})
    total_bytes = value.get("total_bytes")
    if not isinstance(total_bytes, int) or not 0 < total_bytes <= MAX_ANIMATION_BYTES:
        return None
    return {"animated": True, "frame_count": len(clean), "frames": clean, "total_bytes": total_bytes}


def animation_info(asset: dict) -> dict:
    """讀取素材的可驗證動畫 manifest；靜態素材或壞掉的 sidecar 一律安全退回首幀。"""
    digest = asset.get("digest", asset.get("hash")) if isinstance(asset, dict) else None
    if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
        return {"animated": False}
    try:
        value = json.loads(_manifest_path(digest).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {"animated": False}
    return _valid_animation_manifest(value, digest) or {"animated": False}


def animation_frame_path(asset: dict, frame_index: int) -> tuple[Path, str] | None:
    """取得已驗證動畫影格；傳回 None 時 route 必須回 404，絕不組合使用者路徑。"""
    info = animation_info(asset)
    if not info.get("animated") or isinstance(frame_index, bool) or not isinstance(frame_index, int):
        return None
    frames = info["frames"]
    if not 0 <= frame_index < len(frames):
        return None
    path = assets_dir() / frames[frame_index]["filename"]
    if not path.is_file():
        return None
    mime_type = "image/jpeg" if path.suffix.lower() == ".jpg" else "image/png"
    return path, mime_type


def prepare_asset(original_filename: str, content: bytes) -> dict:
    """正規化並保存實體檔，回傳尚未加入圖庫索引的 record。"""
    frames, animated = _decode_frames(original_filename, content)
    encoded = [(*_encode(image), duration_ms) for image, duration_ms in frames]
    first_body, first_extension, first_mime_type, _ = encoded[0]
    first_digest = hashlib.sha256(first_body).hexdigest()
    filename = f"image_{first_digest}{first_extension}"
    _write_canonical_file(filename, first_body)

    if animated:
        total_bytes = sum(len(body) for body, _, _, _ in encoded)
        if total_bytes > MAX_ANIMATION_BYTES:
            raise ValueError("動畫最佳化後不可超過 30MB，請減少影格或縮小圖片")
        digest = _animation_digest(encoded)
        manifest_frames = []
        for index, (body, extension, mime_type, duration_ms) in enumerate(encoded):
            frame_filename = f"animation_{digest}_{index:02d}{extension}"
            _write_canonical_file(frame_filename, body)
            manifest_frames.append({"filename": frame_filename, "duration_ms": duration_ms, "mime_type": mime_type})
        _write_manifest(digest, {"version": 1, "digest": digest, "frames": manifest_frames, "total_bytes": total_bytes})
        mime_type = first_mime_type
        size = total_bytes
    else:
        digest, mime_type, size = first_digest, first_mime_type, len(first_body)

    # id 是工作區圖庫項目的穩定識別碼；hash 是跨上傳去重、快取和檔名用的內容識別。
    asset_id = uuid.uuid4().hex[:12]
    record = {
        "id": asset_id,
        "filename": filename,
        "original_filename": Path(original_filename).name or "upload",
        "hash": digest,
        "size": size,
        "mime_type": mime_type,
        "uploaded_at": time.time(),
        "source_size": len(content),
        "width": frames[0][0].width,
        "height": frames[0][0].height,
        "animated": animated,
        "frame_count": len(frames) if animated else 1,
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


def remove_asset_files(record: dict, *, preview_is_referenced: bool, digest_is_referenced: bool) -> None:
    """清理已無資料庫引用的素材；所有路徑皆由已驗證 manifest／檔名取得。"""
    if not preview_is_referenced:
        try:
            asset_file_path(record).unlink(missing_ok=True)
        except ValueError:
            pass
    if digest_is_referenced:
        return
    digest = record.get("digest", record.get("hash"))
    if not isinstance(digest, str):
        return
    info = animation_info(record)
    if not info.get("animated"):
        return
    for frame in info["frames"]:
        (assets_dir() / frame["filename"]).unlink(missing_ok=True)
    _manifest_path(digest).unlink(missing_ok=True)

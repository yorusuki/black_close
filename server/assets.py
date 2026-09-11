"""圖片素材庫：上傳的檔案存在 DATA_DIR/assets/<asset_id>_<hash12>.<ext>，檔名本身帶內容雜湊。

版本判斷完全靠檔名裡的內容 hash，不用另外維護一份「目前最新版本」的狀態、也不用推播
機制：樹莓派端只要比對「這個 asset_id + hash 組成的檔名，本機存在嗎」，不存在才下載，
沿用既有的 poll 迴圈就好（見 device_agent/agent.py 的 sync_assets()）。

assets.json 純粹給編輯器的圖庫列表用（檔名/大小/上傳時間），不是版本判斷依據。

伺服器端（正本）跟樹莓派端（下載回來的快取）用的是同一份程式碼、不同的
EPAGERPI_DATA_DIR（各自的 repo 根目錄），所以路徑規則自動對齊，不用特別處理。
"""
from __future__ import annotations

import hashlib
import time
import uuid
from pathlib import Path

from . import config, store


def assets_dir() -> Path:
    d = config.DATA_DIR / "assets"
    d.mkdir(parents=True, exist_ok=True)
    return d


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
    return assets_dir() / asset["filename"]


def save_asset(original_filename: str, content: bytes) -> dict:
    """存一個新素材。回傳的 record 會被寫進 assets.json 索引。"""
    ext = Path(original_filename).suffix.lower() or ".bin"
    digest = hashlib.sha256(content).hexdigest()[:12]
    asset_id = uuid.uuid4().hex[:12]
    filename = f"{asset_id}_{digest}{ext}"

    asset_file_path({"filename": filename}).write_bytes(content)

    items = list_assets()
    record = {
        "id": asset_id,
        "filename": filename,
        "original_filename": original_filename,
        "hash": digest,
        "size": len(content),
        "uploaded_at": time.time(),
    }
    items.append(record)
    _save_index(items)
    return record


def delete_asset(asset_id: str) -> bool:
    items = list_assets()
    keep = [a for a in items if a["id"] != asset_id]
    if len(keep) == len(items):
        return False
    removed = next(a for a in items if a["id"] == asset_id)
    _save_index(keep)
    try:
        asset_file_path(removed).unlink(missing_ok=True)
    except OSError:
        pass
    return True

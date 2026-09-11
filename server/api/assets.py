"""圖片素材庫 API：上傳／列表／下載／刪除。

POST 上傳（multipart，欄位名 file）、GET 列表、GET /<id> 下載原始檔（樹莓派端
sync_assets() 下載素材也是打這支）、DELETE /<id> 刪除。
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request, send_file

from .. import assets

bp = Blueprint("assets", __name__, url_prefix="/api/assets")


@bp.get("")
def list_assets():
    return jsonify(assets.list_assets())


@bp.post("")
def upload_asset():
    file = request.files.get("file")
    if file is None:
        return jsonify({"error": "缺少檔案（multipart 欄位名須為 file）"}), 400
    content = file.read()
    if not content:
        return jsonify({"error": "檔案是空的"}), 400
    record = assets.save_asset(file.filename or "upload.bin", content)
    return jsonify(record), 201


@bp.get("/<asset_id>")
def download_asset(asset_id):
    record = assets.get_asset(asset_id)
    if record is None:
        return jsonify({"error": "not_found"}), 404
    path = assets.asset_file_path(record)
    if not path.exists():
        return jsonify({"error": "檔案遺失（索引存在但實體檔案不在，可能被手動刪除）"}), 404
    return send_file(path, download_name=record.get("original_filename") or record["filename"])


@bp.delete("/<asset_id>")
def remove_asset(asset_id):
    ok = assets.delete_asset(asset_id)
    if not ok:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"deleted": asset_id})

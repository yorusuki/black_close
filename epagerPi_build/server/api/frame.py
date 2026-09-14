"""渲染輸出端點：本機模式的排程器、以及線上拆分模式的裝置代理都打這支。"""
from __future__ import annotations

import io
import json
from urllib.parse import quote

from flask import Blueprint, jsonify, send_file

from .. import config
from ..render.compositor import render_device

bp = Blueprint("frame", __name__, url_prefix="/api/devices")


@bp.get("/<device_id>/frame.png")
def get_frame(device_id):
    try:
        image, meta = render_device(device_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404

    # 順手存一份到 data/preview/，方便本機開發時直接看檔案，不用另外寫工具。
    config.ensure_dirs()
    image.save(config.PREVIEW_DIR / f"{device_id}.png")

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    buf.seek(0)
    resp = send_file(buf, mimetype="image/png")
    # HTTP header 值只能是 latin-1，情境名稱/layout id 可能含中文，一律 URL-encode，
    # 用的人（device_agent/agent.py）要用 urllib.parse.unquote 解回來。
    resp.headers["X-Refresh-Mode"] = meta["refresh_mode"]
    resp.headers["X-Dirty-Boxes"] = json.dumps(meta["dirty_boxes"])
    resp.headers["X-Scene"] = quote(meta["scene"] or "")
    resp.headers["X-Layout-Id"] = quote(meta["layout_id"] or "")
    return resp


@bp.get("/<device_id>/frame-meta")
def get_frame_meta(device_id):
    """跟 frame.png 邏輯一致，但只回傳 JSON meta（不含圖），方便前端預覽頁 polling。"""
    try:
        _, meta = render_device(device_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify(meta)

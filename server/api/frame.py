"""渲染輸出端點：

- /frame.png、/frame-meta：本機 all-in-one 模式的排程器可以用（雖然它其實直接呼叫
  compositor，不用打自己的 API），主要是給編輯器預覽、以及舊版/簡單的裝置代理用。
- /layout-data：線上拆分模式的裝置代理打這支，只回傳「選好的 layout + 已解析的
  http 資料」，不含圖也不含刷新判斷——實際畫圖、dirty-box 比對、整幅/局部刷新節流
  由裝置代理在本機用 render_from_elements() 算，才能讓倒數計時/動畫類模組保持即時。
"""
from __future__ import annotations

import io
import json
from urllib.parse import quote

from flask import Blueprint, jsonify, send_file

from .. import config
from ..render.compositor import render_device, resolve_layout_elements

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


@bp.get("/<device_id>/layout-data")
def get_layout_data(device_id):
    """線上拆分模式的裝置代理輪詢這支：只回傳選好的 layout + 每個元素的 config +
    已解析的 http 資料（本地型別如 manual/battery/time_until/time_progress 完全
    不在這裡解析，留給裝置代理在本機 render_from_elements() 時才即時算）。"""
    try:
        resolved = resolve_layout_elements(device_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify(resolved)

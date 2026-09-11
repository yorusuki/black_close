from flask import Blueprint, jsonify, request

from .. import store

bp = Blueprint("layouts", __name__, url_prefix="/api/layouts")


@bp.get("")
def list_layouts():
    return jsonify(store.list_layout_ids())


@bp.get("/<layout_id>")
def get_layout(layout_id):
    layout = store.get_layout(layout_id)
    if layout is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(layout)


@bp.put("/<layout_id>")
def save_layout(layout_id):
    payload = request.get_json(force=True)
    store.save_layout(layout_id, payload)
    return jsonify(payload)

from flask import Blueprint, jsonify, request

from .. import store
from ..render import scenes as scene_engine

bp = Blueprint("scenes", __name__, url_prefix="/api/devices")


@bp.get("/<device_id>/scenes")
def list_scenes(device_id):
    return jsonify(store.get_scenes(device_id))


@bp.put("/<device_id>/scenes")
def save_scenes(device_id):
    payload = request.get_json(force=True)
    store.save_scenes(device_id, payload)
    return jsonify(payload)


@bp.get("/<device_id>/active-scene")
def active_scene(device_id):
    return jsonify({
        "scene": scene_engine.active_scene_name(device_id),
        "layout_id": scene_engine.select_layout_id(device_id),
    })

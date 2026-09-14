from __future__ import annotations

from flask import Blueprint, jsonify, request

from .. import store

bp = Blueprint("devices", __name__, url_prefix="/api/devices")


@bp.get("")
def list_devices():
    return jsonify(store.list_devices())


@bp.get("/<device_id>")
def get_device(device_id):
    device = store.get_device(device_id)
    if device is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(device)


@bp.put("/<device_id>")
def upsert_device(device_id):
    payload = request.get_json(force=True)
    payload["id"] = device_id
    devices = store.list_devices()
    devices = [d for d in devices if d["id"] != device_id]
    devices.append(payload)
    store.save_devices(devices)
    return jsonify(payload)

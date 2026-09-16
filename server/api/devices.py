from __future__ import annotations

from flask import Blueprint, jsonify, request

from .. import store

bp = Blueprint("devices", __name__, url_prefix="/api/devices")
_IMMUTABLE_HARDWARE_FIELDS = ("driver", "resolution", "color_mode", "partial_refresh")


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
    payload = request.get_json(force=False)
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid_device", "message": "設備資料必須是 JSON 物件"}), 400
    existing = store.get_device(device_id)
    if existing:
        changed = [field for field in _IMMUTABLE_HARDWARE_FIELDS if field in payload and payload[field] != existing.get(field)]
        if changed:
            return jsonify({
                "error": "immutable_hardware",
                "message": "既有設備不可變更硬體型號、解析度、色彩模式或局刷能力；請建立新的設備。",
                "fields": changed,
            }), 409
        # 舊 API 仍可調整既有非硬體欄位，但缺少的欄位不可意外被整筆覆寫刪除。
        payload = {**existing, **payload}
    payload["id"] = device_id
    devices = [d for d in store.list_devices() if d["id"] != device_id]
    devices.append(payload)
    store.save_devices(devices)
    return jsonify(payload)

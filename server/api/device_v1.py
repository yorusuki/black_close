"""The Pi-only v1 API. Identity comes exclusively from its bearer device token."""
from __future__ import annotations

from flask import Blueprint, jsonify, request, send_file

from .. import auth, config, workspace_store

bp = Blueprint("device_v1", __name__, url_prefix="/api/v1/device")


@bp.get("/layout")
@auth.require_device
def layout(device):
    return jsonify(workspace_store.device_layout(device))


@bp.get("/assets/<asset_id>")
@auth.require_device
def asset(device, asset_id):
    record = workspace_store.asset_for_device(device, asset_id)
    if not record:
        return jsonify({"error": "not_found"}), 404
    path = config.DATA_DIR / "assets" / record["filename"]
    if not path.is_file():
        return jsonify({"error": "asset_file_missing"}), 404
    return send_file(path, mimetype=record["mime_type"], conditional=True)


@bp.post("/telemetry")
@auth.require_device
def telemetry(device):
    try:
        payload = workspace_store.save_telemetry(device, request.get_json(force=False))
    except ValueError as exc:
        return jsonify({"error": "invalid_telemetry", "message": str(exc)}), 400
    return jsonify({"accepted": True, "reported_at": payload["reported_at"]}), 202

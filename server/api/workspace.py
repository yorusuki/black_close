"""Authenticated management API. All object lookups are owner-scoped."""
from __future__ import annotations

from io import BytesIO
import mimetypes

from flask import Blueprint, jsonify, request, send_file, session

from .. import assets, auth, config, workspace_store
from ..render.compositor import render_from_elements

bp = Blueprint("workspace", __name__, url_prefix="/api/workspace")


def _user_id() -> str:
    return auth.current_user()["id"]


@bp.get("/me")
@auth.require_user
def me():
    user = auth.current_user()
    return jsonify({"id": user["id"], "display_name": user["display_name"], "role": user["role"], "csrf_token": session["csrf"]})


@bp.get("/devices")
@auth.require_user
def list_devices():
    return jsonify(workspace_store.list_devices(_user_id()))


@bp.post("/devices")
@auth.require_user
def create_device():
    try:
        data = request.get_json(force=False)
        return jsonify(workspace_store.create_device(_user_id(), data.get("name"), data.get("model_id"))), 201
    except (AttributeError, ValueError) as exc:
        return jsonify({"error": "invalid_device", "message": str(exc)}), 400


@bp.patch("/devices/<device_id>")
@auth.require_user
def update_device(device_id):
    data = request.get_json(force=False) or {}
    if set(data) == {"hidden"} and isinstance(data["hidden"], bool):
        if not workspace_store.set_device_hidden(_user_id(), device_id, data["hidden"]):
            return jsonify({"error": "not_found"}), 404
        return jsonify(workspace_store.get_device(_user_id(), device_id))
    if set(data) == {"refresh"}:
        try:
            device = workspace_store.update_device_refresh(_user_id(), device_id, data["refresh"])
        except ValueError as exc:
            return jsonify({"error": "invalid_refresh", "message": str(exc)}), 400
        return jsonify(device) if device else (jsonify({"error": "not_found"}), 404)
    return jsonify({"error": "invalid_device", "message": "僅可更新 hidden 或 refresh"}), 400


@bp.post("/devices/<device_id>/token")
@auth.require_user
def rotate_token(device_id):
    token = workspace_store.rotate_device_token(_user_id(), device_id)
    if not token:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"device_id": device_id, "token": token, "warning": "此 token 僅顯示這一次。"})


@bp.get("/devices/<device_id>/preview")
@auth.require_user
def preview_device_page(device_id):
    page_id = request.args.get("page_id", "")
    if not page_id:
        return jsonify({"error": "missing_page_id"}), 400
    resolved = workspace_store.preview_layout(_user_id(), device_id, page_id)
    if not resolved:
        return jsonify({"error": "not_found"}), 404
    image, meta = render_from_elements(resolved)
    body = BytesIO()
    image.save(body, format="PNG")
    body.seek(0)
    response = send_file(body, mimetype="image/png", max_age=0)
    response.headers["X-Preview-Refresh-Mode"] = meta["refresh_mode"]
    return response


@bp.get("/devices/<device_id>/assignment")
@auth.require_user
def get_device_assignment(device_id):
    assignment = workspace_store.device_assignment(_user_id(), device_id)
    return jsonify(assignment) if assignment else (jsonify({"error": "not_found"}), 404)


@bp.get("/pages")
@auth.require_user
def list_pages():
    return jsonify(workspace_store.list_pages(_user_id()))


@bp.post("/pages")
@auth.require_user
def create_page():
    data = request.get_json(force=False) or {}
    try:
        return jsonify(workspace_store.create_page(_user_id(), data.get("name"), data.get("content"), data.get("model_id"))), 201
    except ValueError as exc:
        return jsonify({"error": "invalid_page", "message": str(exc)}), 400


@bp.get("/pages/<page_id>")
@auth.require_user
def get_page(page_id):
    page = workspace_store.get_page(_user_id(), page_id)
    return jsonify(page) if page else (jsonify({"error": "not_found"}), 404)


@bp.put("/pages/<page_id>")
@auth.require_user
def save_page(page_id):
    data = request.get_json(force=False) or {}
    try:
        page = workspace_store.save_page(_user_id(), page_id, data.get("name"), data.get("content"))
    except ValueError as exc:
        return jsonify({"error": "invalid_page", "message": str(exc)}), 400
    return jsonify(page) if page else (jsonify({"error": "not_found"}), 404)


@bp.get("/rules")
@auth.require_user
def list_rules():
    return jsonify(workspace_store.list_rules(_user_id()))


@bp.get("/rules/conflicts")
@auth.require_user
def list_rule_conflicts():
    return jsonify(workspace_store.list_rule_conflicts(_user_id()))


@bp.post("/rules")
@auth.require_user
def create_rule():
    try:
        return jsonify(workspace_store.create_rule(_user_id(), request.get_json(force=False))), 201
    except ValueError as exc:
        return jsonify({"error": "invalid_rule", "message": str(exc)}), 400


@bp.put("/rules/<rule_id>")
@auth.require_user
def update_rule(rule_id):
    try:
        rule = workspace_store.update_rule(_user_id(), rule_id, request.get_json(force=False))
    except ValueError as exc:
        return jsonify({"error": "invalid_rule", "message": str(exc)}), 400
    return jsonify(rule) if rule else (jsonify({"error": "not_found"}), 404)


@bp.delete("/rules/<rule_id>")
@auth.require_user
def delete_rule(rule_id):
    return ("", 204) if workspace_store.delete_rule(_user_id(), rule_id) else (jsonify({"error": "not_found"}), 404)


@bp.get("/attendance/today")
@auth.require_user
def get_attendance():
    return jsonify(workspace_store.attendance_snapshot(_user_id(), config.now_local().date()))


@bp.put("/attendance/today")
@auth.require_user
def save_attendance():
    try:
        return jsonify(workspace_store.save_attendance(_user_id(), config.now_local().date(), request.get_json(force=False)))
    except ValueError as exc:
        return jsonify({"error": "invalid_attendance", "message": str(exc)}), 400


@bp.get("/assets")
@auth.require_user
def list_assets():
    return jsonify(workspace_store.list_assets(_user_id()))


@bp.post("/assets")
@auth.require_user
def upload_asset():
    upload = request.files.get("file")
    if not upload:
        return jsonify({"error": "missing_file"}), 400
    try:
        record = assets.save_asset(upload.filename or "upload.bin", upload.read())
        mime_type = mimetypes.guess_type(record["filename"])[0] or "application/octet-stream"
        return jsonify(workspace_store.add_asset(_user_id(), record, mime_type)), 201
    except ValueError as exc:
        return jsonify({"error": "invalid_asset", "message": str(exc)}), 400


@bp.get("/assets/<asset_id>")
@auth.require_user
def get_asset(asset_id):
    record = workspace_store.get_asset(_user_id(), asset_id)
    if not record:
        return jsonify({"error": "not_found"}), 404
    path = config.DATA_DIR / "assets" / record["filename"]
    if not path.is_file():
        return jsonify({"error": "asset_file_missing"}), 404
    return send_file(path, mimetype=record["mime_type"], conditional=True)

"""Authenticated management API. All object lookups are owner-scoped."""
from __future__ import annotations

from io import BytesIO

from flask import Blueprint, jsonify, request, send_file, session

from .. import assets, auth, config, holiday_calendar, workspace_store
from ..render.compositor import render_from_elements

bp = Blueprint("workspace", __name__, url_prefix="/api/workspace")


def _user_id() -> str:
    return auth.current_user()["id"]


def _asset_view(record: dict) -> dict:
    """公開給 owner 的圖庫卡片資料；不透露實體 manifest 路徑以外的資訊。"""
    return {**record, **assets.animation_info(record)}


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
        device = workspace_store.create_device(_user_id(), data.get("name"), data.get("model_id"))
        # 新設備由管理台建立時，立即補上同型號週末頁的休假規則；資料層仍保持
        # create_device 純粹，方便既有匯入與測試明確控制預設建置時機。
        workspace_store.ensure_default_holiday_rules(device["id"])
        workspace_store.ensure_default_national_holiday_pages(device["id"])
        # 回傳補建預設頁後的最新 profile，讓管理台與下一次 Pi 請求立即看到專用頁 ID。
        return jsonify(workspace_store.get_device(_user_id(), device["id"])), 201
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
    if set(data) == {"national_holiday_page_id"}:
        try:
            device = workspace_store.update_device_national_holiday_page(
                _user_id(), device_id, data["national_holiday_page_id"]
            )
        except ValueError as exc:
            return jsonify({"error": "invalid_national_holiday_page", "message": str(exc)}), 400
        return jsonify(device) if device else (jsonify({"error": "not_found"}), 404)
    return jsonify({"error": "invalid_device", "message": "僅可更新 hidden、refresh 或國定假日專用頁"}), 400


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
    try:
        data = request.get_json(force=False)
        if not isinstance(data, dict):
            raise ValueError("頁面資料必須是 JSON 物件")
        model_id = data.get("model_id")
        preset = data.get("preset", "blank")
        if not isinstance(preset, str):
            raise ValueError("預設版面格式不正確")
        if preset != "blank" and "content" in data:
            raise ValueError("使用預設版面時不可同時傳入自訂內容")
        content = workspace_store.page_preset(model_id, preset) if preset != "blank" else data.get("content")
        return jsonify(workspace_store.create_page(_user_id(), data.get("name"), content, model_id)), 201
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


@bp.get("/holidays")
@auth.require_user
def list_holidays():
    return jsonify({
        "dates": holiday_calendar.list_holidays(_user_id()),
        "official_source": holiday_calendar.OFFICIAL_SOURCE_LABEL,
    })


@bp.post("/holidays/import")
@auth.require_user
def import_holidays():
    data = request.get_json(force=False) or {}
    try:
        if not isinstance(data, dict) or set(data) != {"year"}:
            raise holiday_calendar.HolidayCalendarError("請只提供要匯入的年份")
        return jsonify(holiday_calendar.import_official_holidays(_user_id(), data.get("year")))
    except holiday_calendar.HolidayCalendarError as exc:
        return jsonify({"error": "holiday_import_failed", "message": str(exc)}), 400


@bp.post("/holidays/manual")
@auth.require_user
def add_manual_holiday():
    data = request.get_json(force=False) or {}
    try:
        if not isinstance(data, dict) or set(data) - {"date", "name"} or "date" not in data:
            raise holiday_calendar.HolidayCalendarError("請提供日期與選填名稱")
        return jsonify(holiday_calendar.add_manual_holiday(_user_id(), data.get("date"), data.get("name"))), 201
    except holiday_calendar.HolidayCalendarError as exc:
        return jsonify({"error": "invalid_holiday", "message": str(exc)}), 400


@bp.delete("/holidays/manual/<date_value>")
@auth.require_user
def delete_manual_holiday(date_value):
    try:
        deleted = holiday_calendar.delete_manual_holiday(_user_id(), date_value)
    except holiday_calendar.HolidayCalendarError as exc:
        return jsonify({"error": "invalid_holiday", "message": str(exc)}), 400
    return ("", 204) if deleted else (jsonify({"error": "not_found"}), 404)


@bp.get("/assets")
@auth.require_user
def list_assets():
    return jsonify([_asset_view(record) for record in workspace_store.list_assets(_user_id())])


@bp.post("/assets")
@auth.require_user
def upload_asset():
    upload = request.files.get("file")
    if not upload:
        return jsonify({"error": "missing_file"}), 400
    try:
        record = assets.prepare_asset(upload.filename or "upload.bin", upload.read())
        existing = workspace_store.get_asset_by_digest(_user_id(), record["hash"])
        if existing:
            # 實體檔名由 digest 決定，已被安全保存；同一個人再次上傳相同圖不新增
            # 圖庫卡片，也避免要使用者猜哪個素材 ID 才是有效的。
            return jsonify({**_asset_view(existing), "deduplicated": True}), 200
        mime_type = record["mime_type"]
        saved = workspace_store.add_asset(_user_id(), record, mime_type)
        if saved["deduplicated"]:
            return jsonify(_asset_view(saved)), 200
        assets.register_asset(record)
        return jsonify(_asset_view(saved)), 201
    except ValueError as exc:
        return jsonify({"error": "invalid_asset", "message": str(exc)}), 400


@bp.get("/assets/<asset_id>")
@auth.require_user
def get_asset(asset_id):
    record = workspace_store.get_asset(_user_id(), asset_id)
    if not record:
        return jsonify({"error": "not_found"}), 404
    try:
        path = assets.asset_file_path(record)
    except ValueError:
        return jsonify({"error": "asset_file_invalid"}), 404
    if not path.is_file():
        return jsonify({"error": "asset_file_missing"}), 404
    return send_file(path, mimetype=record["mime_type"], conditional=True)


@bp.delete("/assets/<asset_id>")
@auth.require_user
def delete_asset(asset_id):
    try:
        record = workspace_store.delete_asset(_user_id(), asset_id)
    except ValueError as exc:
        return jsonify({"error": "asset_in_use", "message": str(exc)}), 409
    if not record:
        return jsonify({"error": "not_found"}), 404
    # 資料庫索引先成功刪除才清實體檔。檔案仍被其他帳號共用時保留，避免破壞對方的
    # 圖庫；清理不影響本次 API 回覆。
    assets.delete_asset(asset_id)
    assets.remove_asset_files(
        record,
        preview_is_referenced=workspace_store.asset_file_is_referenced(record["filename"]),
        digest_is_referenced=workspace_store.asset_digest_is_referenced(record["digest"]),
    )
    return ("", 204)

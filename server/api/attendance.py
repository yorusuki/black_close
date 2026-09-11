from __future__ import annotations

from flask import Blueprint, jsonify, request

from .. import attendance

bp = Blueprint("attendance", __name__, url_prefix="/api/attendance")


@bp.get("/today")
def get_today():
    return jsonify(attendance.get_today_snapshot())


@bp.put("/today")
def save_today():
    try:
        payload = request.get_json(force=False, silent=False)
        saved = attendance.save_today(payload)
    except (TypeError, ValueError) as exc:
        return jsonify({"error": "invalid_attendance", "message": str(exc)}), 400
    return jsonify(saved)

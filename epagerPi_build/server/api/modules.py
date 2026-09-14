from flask import Blueprint, jsonify

from ..modules.registry import list_manifests

bp = Blueprint("modules", __name__, url_prefix="/api/modules")


@bp.get("")
def list_modules():
    """給排版編輯器的模組面板用：新模組只要在 server/modules/registry.py 註冊，
    這個端點就會自動列出來，前端不用改任何程式碼。"""
    return jsonify(list_manifests())

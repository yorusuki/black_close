"""Browser session, LINE Login and device-token authorization boundaries."""
from __future__ import annotations

import base64
import hashlib
import secrets
from functools import wraps
from urllib.parse import urlencode

import requests
from flask import Response, abort, jsonify, redirect, request, session

from . import config, workspace_store

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _check_basic_auth() -> bool:
    value = request.authorization
    return bool(value and value.username == config.AUTH_USER and value.password == config.AUTH_PASS)


def _check_legacy_bearer() -> bool:
    header = request.headers.get("Authorization", "")
    return header.startswith("Bearer ") and bool(config.API_TOKEN) and secrets.compare_digest(header[7:].strip(), config.API_TOKEN)


def _legacy_device_read() -> bool:
    """Compatibility is intentionally limited to old agent GETs, never management APIs."""
    path = request.path
    return request.method == "GET" and (
        path.startswith("/api/devices/") or path.startswith("/api/assets/")
    )


def _unauthorized() -> Response:
    return Response("需要驗證才能存取", 401, {"WWW-Authenticate": 'Basic realm="epagerPi"'})


def current_user() -> dict | None:
    user_id = session.get("user_id")
    return workspace_store.user_by_id(user_id) if isinstance(user_id, str) else None


def _csrf_valid() -> bool:
    supplied = request.headers.get("X-CSRF-Token", "")
    expected = session.get("csrf")
    return isinstance(expected, str) and bool(supplied) and secrets.compare_digest(supplied, expected)


def require_user(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({"error": "authentication_required"}), 401
        if request.method not in _SAFE_METHODS and not _csrf_valid():
            return jsonify({"error": "csrf_failed"}), 403
        return view(*args, **kwargs)
    return wrapped


def _bearer_device():
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    return workspace_store.device_for_token(header[7:].strip())


def require_device(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        device = _bearer_device()
        if not device:
            return jsonify({"error": "device_authentication_required"}), 401
        return view(device, *args, **kwargs)
    return wrapped


def _pkce_verifier() -> str:
    return secrets.token_urlsafe(48)


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def line_start():
    if config.AUTH_MODE != "line":
        abort(404)
    state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), _pkce_verifier()
    session.clear()
    session["line_state"], session["line_nonce"], session["line_verifier"] = state, nonce, verifier
    query = urlencode({
        "response_type": "code", "client_id": config.LINE_CHANNEL_ID,
        "redirect_uri": config.LINE_REDIRECT_URI, "state": state, "scope": "profile openid",
        "nonce": nonce, "code_challenge": _pkce_challenge(verifier), "code_challenge_method": "S256",
    })
    return redirect(f"{config.LINE_AUTHORIZE_URL}?{query}")


def line_callback():
    if config.AUTH_MODE != "line":
        abort(404)
    expected_state = session.pop("line_state", None)
    verifier = session.pop("line_verifier", None)
    session.pop("line_nonce", None)
    if not expected_state or not verifier or not secrets.compare_digest(str(request.args.get("state", "")), expected_state):
        return Response("LINE 登入狀態已失效，請重新登入。", 400)
    code = request.args.get("code")
    if not code:
        return Response("LINE 未回傳授權碼。", 400)
    try:
        token_response = requests.post(config.LINE_TOKEN_URL, data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": config.LINE_REDIRECT_URI,
            "client_id": config.LINE_CHANNEL_ID, "client_secret": config.LINE_CHANNEL_SECRET, "code_verifier": verifier,
        }, timeout=10)
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]
        profile_response = requests.get(config.LINE_PROFILE_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
        profile_response.raise_for_status()
        profile = profile_response.json()
        line_sub = profile["userId"]
    except (requests.RequestException, KeyError, ValueError):
        return Response("LINE 身分驗證失敗，請稍後再試。", 502)
    user = workspace_store.user(line_sub)
    if not user and config.REGISTRATION_MODE == "first_login":
        user = workspace_store.ensure_first_owner(line_sub, str(profile.get("displayName") or "LINE 使用者"))
    if not user:
        return Response("此 LINE 帳號尚未獲授權。", 403)
    session.clear()  # session fixation protection; no LINE token is retained.
    session["user_id"], session["csrf"] = user["id"], secrets.token_urlsafe(32)
    return redirect("/")


def logout():
    if not current_user() or not _csrf_valid():
        return jsonify({"error": "csrf_failed"}), 403
    session.clear()
    return ("", 204)


def init_app(app) -> None:
    """Configure Flask sessions and install one explicit policy for each auth mode."""
    if config.AUTH_MODE not in {"legacy", "line"}:
        raise RuntimeError("EPAGERPI_AUTH_MODE 必須為 legacy 或 line")
    if config.AUTH_MODE == "line":
        missing = [name for name, value in {
            "EPAGERPI_LINE_CHANNEL_ID": config.LINE_CHANNEL_ID,
            "EPAGERPI_LINE_CHANNEL_SECRET": config.LINE_CHANNEL_SECRET,
            "EPAGERPI_LINE_REDIRECT_URI": config.LINE_REDIRECT_URI,
            "EPAGERPI_SESSION_SECRET": config.SESSION_SECRET,
            "EPAGERPI_DEVICE_TOKEN_PEPPER": config.DEVICE_TOKEN_PEPPER,
        }.items() if not value]
        if missing:
            raise RuntimeError("LINE 模式缺少必要設定：" + ", ".join(missing))
        app.secret_key = config.SESSION_SECRET
        app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=config.SESSION_COOKIE_SECURE)

    @app.before_request
    def _global_auth():
        path = request.path
        if path == "/healthz" or path.startswith("/auth/") or path in {"/style.css", "/editor.js"}:
            return None
        if path.startswith("/api/v1/device/"):
            return None  # route-level device decorator authenticates this namespace.
        if config.AUTH_MODE == "legacy":
            if not config.AUTH_ENABLED:
                return None
            return None if (_check_basic_auth() or _check_legacy_bearer()) else _unauthorized()
        # LINE mode: only the explicit read-only legacy agent compatibility path
        # can use the old global bearer token. Every management route uses session.
        if config.LEGACY_API_COMPAT and _legacy_device_read() and _check_legacy_bearer():
            return None
        if path.startswith("/api/"):
            user = current_user()
            if not user:
                return jsonify({"error": "authentication_required"}), 401
            if request.method not in _SAFE_METHODS and not _csrf_valid():
                return jsonify({"error": "csrf_failed"}), 403
            return None
        if not current_user():
            return redirect("/auth/line/start")
        return None

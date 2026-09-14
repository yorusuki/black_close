"""驗證中介層。

- Pi 本機模式（AUTH_ENABLED=0）：完全不驗證，符合「Pi 上不做帳號驗證」的需求。
- 線上 Docker 模式（AUTH_ENABLED=1）：
    - 瀏覽器打開網頁編輯器 → HTTP Basic Auth（AUTH_USER/AUTH_PASS）。
    - 裝置代理 / API 呼叫（帶 Authorization: Bearer <token>）→ 比對 API_TOKEN。
  兩者符合其一即放行。搭配反向代理（見 docker/Caddyfile）做 HTTPS，滿足「傳輸也要驗證」。
"""
from functools import wraps

from flask import request, Response

from . import config


def _check_basic_auth() -> bool:
    auth = request.authorization
    if not auth:
        return False
    return auth.username == config.AUTH_USER and auth.password == config.AUTH_PASS


def _check_bearer_token() -> bool:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return False
    token = header[len("Bearer "):].strip()
    return bool(config.API_TOKEN) and token == config.API_TOKEN


def _unauthorized() -> Response:
    resp = Response("需要驗證才能存取（線上版已啟用驗證）", 401)
    resp.headers["WWW-Authenticate"] = 'Basic realm="epagerPi"'
    return resp


def require_auth(view):
    """裝飾器：套用在每個路由，是否真的擋人依 AUTH_ENABLED 而定。"""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not config.AUTH_ENABLED:
            return view(*args, **kwargs)
        if _check_basic_auth() or _check_bearer_token():
            return view(*args, **kwargs)
        return _unauthorized()

    return wrapped


def init_app(app):
    """全域套用驗證（除了健康檢查端點）。"""

    @app.before_request
    def _global_auth():
        if not config.AUTH_ENABLED:
            return None
        if request.path == "/healthz":
            return None
        if _check_basic_auth() or _check_bearer_token():
            return None
        return _unauthorized()

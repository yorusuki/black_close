"""Flask app 進入點。

本機 Pi 模式：
    EPAGERPI_AUTH_ENABLED=0 python -m server.app
線上 Docker 模式：見 docker/docker-compose.yml（會設 AUTH_ENABLED=1 等變數）。
"""
from __future__ import annotations

from pathlib import Path

from flask import Flask, send_from_directory

from . import auth, config, workspace_store
from .api import BLUEPRINTS

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"


def create_app() -> Flask:
    config.ensure_dirs()
    app = Flask(__name__)

    workspace_store.init()
    workspace_store.migrate_legacy_json()
    workspace_store.upgrade_default_work_layout()
    workspace_store.upgrade_default_mascot_interval()
    workspace_store.upgrade_default_off_work_layout()
    workspace_store.upgrade_default_refresh_policy()

    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    auth.init_app(app)

    app.add_url_rule("/auth/line/start", "line_start", auth.line_start)
    app.add_url_rule(config.LINE_CALLBACK_PATH, "line_callback", auth.line_callback)
    app.add_url_rule("/auth/logout", "logout", auth.logout, methods=["POST"])

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/")
    def index():
        # 管理台的 HTML、CSS、JS 必須是同一版；不要讓瀏覽器把舊 HTML 留在快取中，
        # 否則新版 JS 會找不到新版 UI 的 DOM 節點。
        return send_from_directory(FRONTEND_DIR, "index.html", max_age=0)

    @app.get("/<path:filename>")
    def static_files(filename):
        # 排版編輯器的靜態檔（純 JS/CSS，不靠外部 CDN，離線也能用）
        return send_from_directory(FRONTEND_DIR, filename, max_age=0)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host=config.HOST, port=config.PORT, threaded=True)

"""Flask app 進入點。

本機 Pi 模式：
    EPAGERPI_AUTH_ENABLED=0 python -m server.app
線上 Docker 模式：見 docker/docker-compose.yml（會設 AUTH_ENABLED=1 等變數）。
"""
from __future__ import annotations

from pathlib import Path

from flask import Flask, send_from_directory

from . import auth, config
from .api import BLUEPRINTS

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"


def create_app() -> Flask:
    config.ensure_dirs()
    app = Flask(__name__)

    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    auth.init_app(app)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.get("/<path:filename>")
    def static_files(filename):
        # 排版編輯器的靜態檔（純 JS/CSS，不靠外部 CDN，離線也能用）
        return send_from_directory(FRONTEND_DIR, filename)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host=config.HOST, port=config.PORT, threaded=True)

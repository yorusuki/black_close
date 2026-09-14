# 線上 Docker 部署版：只跑 server/（排版介面 + API + 渲染引擎），不含任何硬體驅動
# （device_agent/ 的螢幕/UPS 驅動只在 Pi 上跑，這裡不需要，也裝不起來）。
FROM python:3.11-slim

# Noto CJK：畫面上的中文文字要靠這個字型，不裝會整段空白。
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY server/ ./server/

ENV PYTHONPATH=/app
ENV EPAGERPI_DATA_DIR=/app/data

EXPOSE 8080

# data/ 由 docker-compose 用 volume 掛進來（見 docker-compose.yml），不烘進 image，
# 這樣排版介面存的 layout/scene 修改才會留在 volume 裡，重建 image 不會遺失。
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "4", "server.app:app"]

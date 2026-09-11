## 2026-09-11

### Changed

- Docker 部署改為使用既有 external Docker network `cloudflared`。
- 移除 Caddy service 與 Caddyfile；Cloudflare Tunnel 現在以 Docker 內網位址 `http://epagerpi:8080` 連線至服務。
- 新增 `docker/README.md`，說明 Tunnel ingress、network 前置條件與啟動方式。
- 更新部署、實作與檢查文件以反映 Cloudflare Tunnel 架構。

### Verification

- `EPAGERPI_AUTH_PASS=<test> EPAGERPI_API_TOKEN=<test> docker compose -f docker/docker-compose.yml config --quiet`：通過。
- 使用專案 venv 的 PyYAML 驗證 Compose 結構：確認 `epagerpi` 僅加入 `cloudflared`、未發布 `ports`、驗證保持啟用，且 `cloudflared` 為 external network。
- Not run: 實際 Docker daemon、Cloudflare Tunnel、公開網域與 HTTPS；需要部署端的 Tunnel credentials 與網域設定。

### Notes

- Compose 不會建立 external `cloudflared` network；它和 Tunnel 容器必須由部署端先建立／加入。
- Cloudflare Tunnel 不取代應用程式驗證，仍須設定 `EPAGERPI_AUTH_PASS` 與 `EPAGERPI_API_TOKEN`。

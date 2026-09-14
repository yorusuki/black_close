# Server 建置與部署

本文件只處理管理／服務端：排版編輯器、API、版面儲存、網路型資料來源與出勤同步。它**不**安裝 GPIO、SPI、電子紙或 UPS 驅動；這些只屬於 [Pi 端](DEPLOY_PI.md)。

## 前置條件

- Docker Engine 與 Docker Compose plugin。
- 已有可供 Cloudflare Tunnel 使用的 Docker network `cloudflared`。
- 若使用 `attendance-sync`，需有可合法使用的 EIP 登入資訊。

## 建置與設定

從倉庫根目錄執行：

```bash
cp docker/.env.example docker/.env
```

在 `docker/.env` 設定下列值，該檔案不得提交：

- `EPAGERPI_AUTH_MODE=line`、`EPAGERPI_LINE_CHANNEL_ID`、`EPAGERPI_LINE_CHANNEL_SECRET`、`EPAGERPI_LINE_REDIRECT_URI`：LINE Login 必填設定；callback URL 必須與 LINE Developers Console 完全一致。
- `EPAGERPI_SESSION_SECRET` 與 `EPAGERPI_DEVICE_TOKEN_PEPPER`：高熵、僅保存於 Server 的秘密值。變更 session secret 會登出所有使用者；變更 pepper 會使所有 Pi token 失效。
- `EPAGERPI_SESSION_COOKIE_SECURE=1`：正式 HTTPS 部署必填；只有隔離的本機 HTTP 測試可改為 `0`。
- `EPAGERPI_REGISTRATION_MODE=first_login`：受控首次部署時，首位 LINE 使用者認領舊資料並成為 owner；完成後應改為 `closed`。
- `EPAGERPI_AUTH_PASS`、`EPAGERPI_API_TOKEN`、`EPAGERPI_LEGACY_API_COMPAT=1`：僅供舊 agent 相容期使用；新 Pi 不使用全域 token。所有 Pi 升級後改回 `EPAGERPI_LEGACY_API_COMPAT=0`。
- `EIP_LOGIN_URL`、`USER_NAME`、`LOGIN_USERNAME`、`LOGIN_PASSWORD`：出勤同步服務所需設定。
- `EPAGERPI_TIMEZONE` 與選用的 `EPAGERPI_FONT_PATH`。

先確認 Compose 展開正確且不顯示秘密值：

```bash
docker compose --env-file docker/.env -f docker/docker-compose.yml config --quiet
```

若尚未建立 Tunnel network，僅在部署主機執行一次：

```bash
docker network create cloudflared
```

## 啟動與驗證

```bash
docker compose --env-file docker/.env -f docker/docker-compose.yml up -d --build
docker compose --env-file docker/.env -f docker/docker-compose.yml ps
docker compose --env-file docker/.env -f docker/docker-compose.yml logs --tail=100 epagerpi
```

Tunnel 的 origin 設為 `http://epagerpi:8080`，而不是主機 IP 或公開網域。此 Compose 不公開 host port；Tunnel 與 `epagerpi` 必須都加入 `cloudflared` network。外層 Tunnel／Access 不能取代 LINE session、CSRF 與 per-device token。

服務健康檢查可從同一 Docker network 或容器內呼叫：

```bash
curl http://epagerpi:8080/healthz
```

預期回應為 `{"status":"ok"}`。

## 資料與更新

- Server 的持久資料位於根目錄 `data/`，Compose 掛載為容器內 `/app/data`。
- 更新程式後重新執行 `up -d --build`；不要刪除 `data/`，否則版面、素材與執行期資料可能遺失。
- Server 端不需 `requirements-hardware.txt`，Dockerfile 只安裝 `requirements-server.txt`。
- Pi 要改以此 Server 運作時，請接續 [Pi Split 模式](DEPLOY_PI.md#split-模式server--pi)。

## 2026-09-12

### Changed

- 排版編輯器新增編輯／預覽模式切換；預覽模式顯示伺服器實際合成與量化後的畫面，持續更新動畫、情境與刷新 metadata。
- 新增 `EPAGERPI_AUTO_OFF_WORK_TIME`（預設 `20:00`）：平日即使沒有下班打卡或網路，Pi 仍會以本機時間切到下班頁。
- Split 模式 agent 在連線到設定的 Server 前先檢查 DNS/TCP 可達性；Server 不可達時改用 Pi checkout 的本機 layout／scene 做合成，恢復連線後自動切回遠端資料。

- 新增根目錄 `README.md`，明確區分 Server 與 Raspberry Pi 的責任、目錄與部署模式。
- 新增 `docs/DEPLOY_SERVER.md` 與 `docs/DEPLOY_PI.md`，將 Docker Server、Pi all-in-one 與 Pi Split 模式的建立／部署步驟分開。
- 新增 `systemd/epagerpi-agent.service`，供 Pi Split 模式執行裝置代理；避免與 all-in-one 的 server／scheduler 同時啟動。
- 新增 `docker/.env.example` 與 `.gitignore`，提供不含真實秘密的設定範本，並忽略裝置 token、Python 快取與執行期資料。
- 將 `epagerPi_build/` 明確標示為過時重複快照，僅供比對，不能用來部署。

### Verification

- `docker compose --env-file docker/.env.example -f docker/docker-compose.yml config --quiet`：通過。
- Python AST 語法檢查：53 個目前正式 Python 檔案通過（排除 `epagerPi_build/` 舊快照）。
- `node --check server/frontend/editor.js` 與 `git diff --check`：通過。

### Notes

- Split 模式的 Pi 仍需要 `server/` 套件用於本機渲染；這是目前架構的必要條件，不代表需在 Pi 啟用 Flask Server。

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
## 2026-09-13

### Changed

- 更新 Docker `.env.example` 與 Pi `config.example.yaml`：明確區分新版 LINE 必填值、舊 agent 相容期值與選用調校值；新版 Pi 僅設定 `server_url` 與 `device_token`。
- 補充 Server／Pi 部署文件的參數用途、secret 輪替影響、Cookie HTTPS 限制與舊全域 token 停用步驟。

- 以下為本輪先前完成的功能：
- 新增 LINE Login（OAuth state + PKCE）、first-owner bootstrap、HttpOnly signed session 與管理 API CSRF 驗證；LINE access token 不會寫入 session 或資料庫。
- 新增 SQLite 正本與可重跑的 legacy JSON migration：使用者、Pi、頁面、規則、素材、出勤與 telemetry 皆納入資料庫；首次 owner 會原子認領舊資料。
- 新增表單式 Pi／頁面／規則建立器，移除管理頁的原始 JSON 編輯區；Pi token 僅在建立或重配發時顯示一次。
- 新增 `/api/v1/device/layout`、`/api/v1/device/assets/<id>` 與 `/api/v1/device/telemetry`；Pi agent 僅使用 `server_url + device_token`。
- 舊 `/api/*` 繼續存在；LINE 模式下 `EPAGERPI_LEGACY_API_COMPAT=1` 僅容許舊 agent 的唯讀 device／asset Bearer 路徑，不能用來操作管理 API。
- 素材上傳限制為經 Pillow 驗證的圖片、副檔名白名單與 10MB 上限。

### Verification

- `python -m unittest discover -s tests -v`：3 項 migration、LINE callback mock、CSRF、owner scope 與 v1 device token 測試通過。
- `python -m compileall -q server device_agent`、`node --check server/frontend/editor.js`、`git diff --check`：通過。

### Notes

- 真實 LINE Channel、EIP 與 Waveshare 4.26 吋硬體尚未在本次本機流程驗證，保留為外部驗證項。
- 管理 UI 尚未提供複合型模組欄位（例如 mascot frames）的視覺編輯器；它會保留既有頁面的預設值，但不再開放 JSON 編輯。

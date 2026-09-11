# 架設與維運報告

檢查日期：2026-09-10

## 執行需求

- Python：開發機現有 `.venv` 使用 Python 3.9；Docker image 使用 Python 3.11。
- 核心相依：Flask、Pillow、Requests、PyYAML（`requirements.txt`）。
- Pi 硬體相依：Inky、gpiozero、spidev、smbus2（`requirements-hardware.txt`）。
- Pi 顯示中文：需安裝 `fonts-noto-cjk`。
- 硬體：Inky pHAT 或 Waveshare 4.26 吋；UPS 功能另需 INA219／UPS HAT (C) 與 I2C。

## 三種部署方式

### 1. 開發機／Mock 驅動

用途是 API、前端和渲染開發，不操作真實面板。以 `EPAGERPI_AUTH_ENABLED=0` 啟動 `python -m server.app`，瀏覽器連到 port 8080；若要測整個 scheduler 流程，先把裝置 profile 的 driver 改為 `mock`，它會輸出 PNG。

注意：預設 host 是 `0.0.0.0` 且驗證預設關閉，僅能在受信任、隔離的開發網段使用。

### 2. Raspberry Pi all-in-one

`run_pi.sh <device-id>` 會同時啟動 Flask server、scheduler 和可選 UPS daemon。長期運行應改用三個 systemd unit：

- `epagerpi-server.service`：Flask editor/API，明確設定 `EPAGERPI_AUTH_ENABLED=0`。
- `epagerpi-scheduler.service`：每秒合成並將需要的畫面推到一個裝置。
- `epagerpi-ups.service`：INA219 監控與低電量關機。

部署前須把 unit 的 `WorkingDirectory`、`PYTHONPATH` 與 Python 路徑從範例 `/home/pi/epagerPi` 改為實際路徑。對多面板，scheduler 必須複製／參數化為每一面板一個 service。

`epagerpi-ups.service` 目前以 root 身分執行，因為它可呼叫 `systemctl poweroff`。這應改成低權限服務帳號搭配最小化的 polkit 或受限 helper，避免專案程式碼改動直接取得 root 執行權。

### 3. Docker server + Pi agent

Docker 執行網頁、API 與 server-side HTTP 資料解析；Pi 執行 `device_agent.agent`、本機渲染、素材同步與 UPS daemon。公開 HTTPS 與網域由外部 Cloudflare Tunnel 處理；Tunnel 容器透過 external `cloudflared` network 連線到 Docker 內網位址 `http://epagerpi:8080`。Docker 模式仍強制開啟 Basic Auth 與 Bearer token。

已驗證 `docker compose -f docker/docker-compose.yml config --quiet` 可通過（以測試用環境變數代入必填 secret）。

## 部署阻礙與設定問題

| 優先級 | 問題 | 影響與建議 |
| --- | --- | --- |
| High | 本機 Pi／開發模式以 `0.0.0.0` 對網段提供未驗證的讀寫 API | 改為 loopback、受信任 VPN 或至少啟用驗證與反向代理；不要把 port 8080 暴露到不可信網路。 |
| Medium | `cloudflared` network 是 external | 若 Tunnel 容器未加入、或 network 尚未建立，Compose 會無法啟動。部署前確認 `docker network inspect cloudflared` 與 Tunnel ingress 的 origin service 為 `http://epagerpi:8080`。 |
| Medium | 無健康檢查、backup、log rotation、metrics 或升級／回滾程序 | 至少加入 container healthcheck、資料目錄備份與服務日誌保存規則。 |
| Medium | 使用最低版本而不鎖版，且無 lockfile | 相依的未來版本可能改變行為。建立可重現的部署鎖定策略與定期更新流程。 |
| Medium | 多 worker Gunicorn 配合 JSON store | 避免同時寫入：短期改 1 worker，長期遷移到支援跨程序交易的儲存層。 |

## 上機前檢核清單

- 以實際網域、強密碼與高熵 API token 建立 `docker/.env`；不得沿用範例值。
- 將 `.env`、`device_agent/config.yaml` 保留在 `.gitignore`；目前已符合。
- 開啟 Pi 的 SPI／I2C，安裝字型與硬體依賴。
- 先執行 `python -m device_agent.detect_hardware --only <driver>`；`--show` 會真的刷新面板，須確認後使用。
- 以 MockDriver 跑過完整 layout，之後才接硬體。
- 針對低電量流程，以安全的模擬／受控測試確認「連續三次低於門檻」；不得在無人值守設備上直接測 poweroff。
- 修正程式碼審查報告中的 High 項目，特別是未驗證 API、上傳素材與 HTTP data source。

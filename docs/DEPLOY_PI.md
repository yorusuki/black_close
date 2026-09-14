# Raspberry Pi 建置與部署

本文件只處理實體裝置端：電子紙驅動、在地渲染、圖片快取與 UPS 低電量保護。Pi 端不使用 Docker，也不應在 Server 主機安裝硬體相依套件。

## 前置條件

- Raspberry Pi OS、Python 3 與可用的 SPI／I2C；先在 `raspi-config` 開啟介面並重新開機。
- 完整倉庫 checkout 放在 `/home/pi/epagerPi`；Split 模式也必須保留 `server/`，因為本機需要渲染與刷新判斷程式碼。
- 管理端建立 Pi 並選擇硬體型號後，取得一次性的 device token；Pi 不再設定 device id。

在倉庫根目錄建立虛擬環境並安裝 Pi 所需套件：

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt -r requirements-hardware.txt
```

若系統 Python 不允許 pip 寫入系統套件，請使用上述 virtualenv；不要為了省事將 Pi 硬體套件裝到 Server 或 Docker 映像中。

## All-in-one 模式（單機／離線）

此模式在同一台 Pi 執行網頁、排程器與 UPS：

```bash
export PYTHONPATH="$PWD"
cp device_agent/config.example.yaml device_agent/config.yaml
./run_pi.sh phat-01
```

All-in-one 舊模式仍使用既有 JSON／排程器。新版受管 Pi agent 則使用下方 Split 模式的 `server_url + device_token`；兩種模式不可混用。

```bash
sudo cp systemd/epagerpi-server.service /etc/systemd/system/
sudo cp systemd/epagerpi-scheduler.service /etc/systemd/system/
sudo cp systemd/epagerpi-ups.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now epagerpi-server epagerpi-scheduler epagerpi-ups
sudo systemctl status epagerpi-server epagerpi-scheduler epagerpi-ups
```

這些範例 unit 預設使用 `/home/pi/epagerPi`、使用者 `pi` 與系統 Python。若你使用 virtualenv、不同帳號或不同路徑，先修改 unit 的 `User`、`WorkingDirectory`、`PYTHONPATH` 與 `ExecStart`，再安裝。UPS 服務目前以 root 執行以觸發安全關機；上線前應依實際環境改為最小權限的 polkit 規則。

## Split 模式（Server + Pi）

先完成 [Server 建置與部署](DEPLOY_SERVER.md)，再在 Pi 建立裝置設定：

```bash
cp device_agent/config.example.yaml device_agent/config.yaml
```

設定至少包含：

```yaml
server_url: https://your-server.example.com
device_token: replace-with-token-shown-once-in-management-ui
poll_interval_seconds: 30
tick_seconds: 1
```

`device_token` 僅能讀取這台 Pi 的 layout、素材與 telemetry 接口；請以 `chmod 600 device_agent/config.yaml` 保護，且不得提交。先以目前終端執行驗證：

```bash
export PYTHONPATH="$PWD"
python -m device_agent.agent
```

agent 會自動呼叫 `/api/v1/device/layout`、所需的素材下載端點與 telemetry；**不要**在 Pi 設定 `device_id`、`render_endpoint`、`api_token`、LINE Channel secret 或 Docker `.env`。若 token 遺失，請由管理端重配發，而不是自行重用舊全域 token。

Server 暫時無法連線時，agent 會保留最後一份有效畫面並在下一個輪詢週期重試；它不會退回讀取本機 JSON，以避免繞過 token 與 owner 規則。

確認能取得資料並刷新後，使用 Split 模式的 agent 與 UPS 服務；此模式**不可**同時啟動 `epagerpi-server.service` 或 `epagerpi-scheduler.service`：

```bash
sudo cp systemd/epagerpi-agent.service /etc/systemd/system/
sudo cp systemd/epagerpi-ups.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now epagerpi-agent epagerpi-ups
sudo systemctl status epagerpi-agent epagerpi-ups
```

## 硬體驗證與維運

部署前以診斷工具檢查實體面板與 UPS：

```bash
export PYTHONPATH="$PWD"
python -m device_agent.detect_hardware
```

僅在可安全實際刷新面板時才使用 `--show`。日常排錯請看：

```bash
journalctl -u epagerpi-agent -u epagerpi-ups -n 100 --no-pager
```

目前 Waveshare 4.26 吋驅動、UPS 充放電方向與 systemd 實機行為尚需目標硬體驗證；詳細限制見 [實作說明](IMPLEMENTATION_NOTES.md)。

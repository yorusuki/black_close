# epagerPi

以 Raspberry Pi 與電子紙面板顯示資訊看板的系統。它提供瀏覽器排版編輯器、可重用的資訊模組、依情境切換的畫面、電子紙刷新策略，以及 UPS 低電量保護。

## 功能

- 排版編輯器與 REST API：管理裝置、版面、情境與素材。
- 模組化渲染：時鐘、進度、統計數字、吉祥物、圖片與出勤資訊可組合到版面中。
- 兩種面板：Pimoroni Inky pHAT 與 Waveshare 4.26 吋；依面板能力選擇整幅或局部刷新。
- 情境與排程：依時間、星期、假日與出勤狀態切換版面。
- Raspberry Pi 裝置端：直接驅動面板、同步圖片素材、讀取 UPS 電量並在低電量時保護關機。

## 兩端責任與部署模式

| 角色 | 程式位置 | 職責 | 部署文件 |
| --- | --- | --- | --- |
| Server | `server/`、`docker/` | 編輯器、API、版面與網路資料解析 | [Server 建置與部署](docs/DEPLOY_SERVER.md) |
| Pi | `device_agent/`、`systemd/` | 本機渲染、面板驅動、素材快取、UPS 保護 | [Pi 建置與部署](docs/DEPLOY_PI.md) |

Pi 可選擇兩種模式：

1. **All-in-one**：Pi 同時執行網站、排程器與 UPS 服務；適合離線或單機使用。
2. **Split**：Server 部署於 Docker 主機，Pi 只輪詢版面資料並在本機渲染、刷新面板與監控 UPS；適合把管理介面與硬體端分開。

Split 模式的 Pi 仍須保留 `server/` 套件，因為畫面合成與電子紙刷新判斷刻意在 Pi 本機執行；它不需要 Flask 或 Docker。

## 目錄說明

```text
server/             Server API、排版前端、模組與渲染核心
device_agent/       Pi 的面板驅動、遠端代理與 UPS 守護程式
systemd/            Pi 專用服務單元
docker/             Server 專用容器部署設定
data/               受版本控制的裝置、版面與情境範例資料
docs/               架構、部署、變更與檢查報告
epagerPi_build/     舊版重複快照；僅供比對，禁止當成部署來源
```

## 快速選擇

- 要架設網頁管理端：從 [Server 建置與部署](docs/DEPLOY_SERVER.md) 開始。
- 要接實體電子紙與 UPS：從 [Pi 建置與部署](docs/DEPLOY_PI.md) 開始。
- 要逐項確認 `.env` 與 Pi 設定：閱讀[設定參數總覽](docs/CONFIGURATION.md)。
- 要使用登入後的管理台：閱讀[管理台操作說明](docs/MANAGEMENT_UI.md)。
- 要理解資料流與模組架構：閱讀 [架構文件](docs/ARCHITECTURE.md)。

## 已知限制

實體面板、UPS 與 systemd 尚須在目標 Pi 硬體實測。`epagerPi_build/` 為過時副本，請勿修改或由該目錄啟動服務。

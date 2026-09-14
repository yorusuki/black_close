# 功能與流程報告

檢查日期：2026-09-10

## 專案目的

epagerPi 是一套以 Raspberry Pi 驅動電子紙面板的看板系統。使用者可透過網頁編輯器配置畫面模組、儲存版面與情境規則；系統會依裝置能力產生量化後的點陣圖，並透過本機排程器或遠端裝置代理刷新螢幕。

目前的資料持久化是 `data/` 下的 JSON 檔，不是資料庫。

## 已實作功能

| 類別 | 功能 | 主要實作 |
| --- | --- | --- |
| 裝置 | 兩個範例 profile：Inky pHAT 2.13 吋三色與 Waveshare 4.26 吋黑白 | `data/devices.json`、`device_agent/drivers/` |
| 畫面編輯 | 選擇裝置、加入模組、拖曳、縮放、層級、儲存版面、即時 PNG 預覽 | `server/frontend/` |
| 模組 | 日期時間列、進度條、標籤/數值列表、AA 吉祥物輪播、圖片 | `server/modules/` |
| 資料來源 | 手動值、HTTP JSON、UPS 電池快取、當日倒數、當日時間進度 | `server/modules/datasource.py` |
| 情境 | 依星期、時段、假日與 priority 選擇 layout | `server/render/scenes.py` |
| 渲染 | 模組合成、1bit／3 色／4 灰階量化、dirty box、整幅或局部刷新策略 | `server/render/compositor.py` |
| 素材 | 上傳、列出、下載、刪除素材；裝置代理可依檔名雜湊同步 | `server/api/assets.py`、`server/assets.py` |
| UPS | INA219 讀值、JSON 快取、連續低電量才關機 | `device_agent/ups/` |
| 部署 | Pi 本機 all-in-one、雲端 server + Pi 本機渲染兩種模式 | `run_pi.sh`、`device_agent/agent.py`、`docker/` |

模組並非真正自動掃描；新增模組後仍須在 `server/modules/registry.py` 加入 class。這是合理的顯式註冊設計，但文件中「自動出現」應理解為註冊後 API／前端自動列出。

## 主要使用流程

```text
瀏覽器編輯器
  → PUT /api/layouts 或 /api/devices/{id}/scenes
  → data/layouts/*.json 或 data/scenes/*.json
  → 情境選擇目前 layout
  → 模組取資料與繪製
  → compositor 量化、比較變更區域、決定刷新模式
  → scheduler（本機）或 agent（Pi）
  → 實體電子紙 / MockDriver PNG
```

### 本機模式

`server.scheduler` 每個 tick 直接呼叫 `render_device()`；若 refresh mode 不是 `none`，即交給對應 display driver。網頁伺服器與排程器是不同程序，UPS daemon 也獨立執行。

### 拆分模式

裝置代理定期向 server 取得 `/api/devices/{id}/layout-data`。HTTP 資料在 server 端解析並快取；倒數、時間進度與電池快取則保留在 Pi 本機渲染，以避免網路輪詢影響即時性。圖片素材會按需下載到 Pi 的 `data/assets/`。

## 目前資料與功能限制

- 範例「特休」資料是 `/api/mock/leave-balance`，不是實際人資系統整合。
- 國定假日 JSON 明確只是示範，沒有包含完整的調整放假與移動式假日。
- Waveshare profile 雖已設定，但文件與診斷工具都表示硬體尚未到貨／未做實機驗證。
- 4gray 模式刻意不做局部更新；目前 Waveshare profile 是 1bit，才能使用局部刷新。
- 模組設定可由 API 任意寫入，未驗證尺寸、座標、資料來源或 schema；這是目前最重要的功能完整性缺口。

## 功能判定

開發機上的「管理 API + 範例資料 + 軟體渲染」可用；實體設備呈現、長時間刷新品質、UPS 關機與前端手勢尚未以自動化或實機證明。上線判定見 [測試與驗證報告](TEST_REPORT.md)。

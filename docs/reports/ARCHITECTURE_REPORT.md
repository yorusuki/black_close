# 系統架構報告

檢查日期：2026-09-10

## 架構總覽

```text
                        ┌─────────────────────────┐
                        │ Browser editor           │
                        │ vanilla JS / CSS / HTML  │
                        └───────────┬─────────────┘
                                    │ REST / PNG
┌─────────────────────┐   ┌─────────▼───────────┐
│ JSON data store     │◀──│ Flask server         │
│ devices/layouts/    │──▶│ APIs + static UI     │
│ scenes/assets       │   └─────────┬───────────┘
└─────────────────────┘             │
                          ┌──────────▼───────────┐
                          │ Render engine         │
                          │ scenes + modules +    │
                          │ compositor/quantize   │
                          └───────┬────────┬──────┘
                                  │        │
                 all-in-one      │        │ split mode
                                  │        │ layout-data HTTP
                          ┌───────▼───┐ ┌──▼─────────────────┐
                          │ Scheduler │ │ Device agent       │
                          │ (Pi)      │ │ local render+sync  │
                          └───────┬───┘ └──┬─────────────────┘
                                  │        │
                           ┌──────▼────────▼──────┐
                           │ display drivers        │
                           │ Inky / Waveshare/mock  │
                           └────────────────────────┘

UPS daemon ── INA219/I2C ──> data/runtime/battery.json ──> battery data source
```

## 元件責任與邊界

| 元件 | 責任 | 輸入／輸出 | 觀察 |
| --- | --- | --- | --- |
| Flask app/API | 提供 editor、資料 CRUD、預覽與裝置輪詢資料 | HTTP JSON/PNG | 路由完整，但 mutation 沒有 schema 驗證 |
| Store | 讀寫 JSON、同程序 lock、暫存檔 replace | JSON 檔 | 簡單適合小規模；不安全於多程序同時寫入 |
| Modules | 取得資料與繪製自己的 element 圖像 | config、data → PIL image | I/O 與繪圖大致分開，容易擴充 |
| Render | 選情境、節流抓取、合成、量化、dirty 判斷 | profile/layout → image + meta | 核心邊界清楚，狀態只存在程序記憶體 |
| Scheduler/agent | 控制 tick、重試、呼叫 display driver | render result → panel | 例外不會停止無限迴圈 |
| Drivers | 將 PIL image 轉成面板協定 | image/mode → hardware | Inky、Waveshare、Mock 三種實作 |
| UPS daemon | 量測、快取、低電量關機 | I2C → JSON/systemctl | 保護措施是連續 N 次低於門檻 |

## 正向架構特性

- 模組介面定義資料抓取與繪圖責任，可在不改 renderer 的情況加入顯示功能。
- 全幅／局部刷新策略位於 compositor，未滲透到 UI 或資料來源。
- 拆分模式仍在 Pi 本機完成時間、電量、dirty-state 與顯示決策，避免把硬體狀態錯放到 server。
- MockDriver 讓無硬體的渲染流程可被驗證。
- JSON 寫入採先寫 temporary file 再 replace，能降低單一程序中斷時留下半份 JSON 的機率。

## 架構偏差與技術債

1. `docker/Dockerfile` 以 Gunicorn 兩個 worker 執行，但 store 的 lock、renderer cache 與刷新歷史都是 process-local。兩個 worker 同時寫同一 JSON 時會共用固定 `.tmp` 檔名，無法保證跨程序原子性；預覽的 refresh metadata 也不具一致性。
2. `epagerPi_build/` 重複保存了一份較舊的 server/device_agent，且與正式根目錄已有多處差異。它容易造成錯誤部署與錯誤修補。
3. JSON 檔案儲存沒有 revision、鎖檔或備份機制；版面更新是最後寫入者覆蓋，無衝突偵測。
4. 版面中 HTTP value source 是伺服器與 Pi 對外呼叫的通道，現行設計未將其視為受控整合點。
5. 首次 Waveshare render 在軟體測試中產生 `partial`，非 `full`。雖然 driver 會先清畫面，但是否建立正確的面板基準畫面仍需以實機確認。

## 建議的演進順序

1. 先在 API 邊界加入資料 model／schema 驗證、ID 規則與元素尺寸界限。
2. 收斂 HTTP data source 至 allowlist 或明確 integration 設定，並封鎖私有／loopback 位址。
3. 單機版維持單 worker；若要多 worker，改用 SQLite（WAL）或具檔案鎖與唯一 temp file 的儲存層。
4. 將正式來源與 `epagerPi_build/` 明確區分；確認後移除或以版本化 release artifact 取代。
5. 加入測試與實機驗收後，再評估資料庫、作業佇列或多裝置管理；現階段不需要過早拆成更多服務。

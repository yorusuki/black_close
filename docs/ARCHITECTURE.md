# epagerPi 架構設計文件

版本：v0.1（初版規劃）
日期：2026-09-07

## 0. 現況盤點（已讀取 official/ 內程式碼後的結論）

| 硬體 | 驅動來源 | 解析度 | 色彩模式 | 是否支援局部刷新 | 關鍵 API |
|---|---|---|---|---|---|
| Pimoroni Inky pHAT 2.13" | `official/inky-main`（可直接 `pip install inky`，不需整包搬進專案） | 212×104 | 黑/白 + 紅或黃（三色，非灰階） | 官方驅動未實作，視為僅整幅刷新 | `Inky(colour).set_image(img)` → `.show()` |
| Waveshare 4.26" | `official/ep_python/lib/waveshare_epd/epd4in26.py` | 800×480 | 1bit 黑白，另有 `display_4Gray` 四階灰階模式 | **有**：`display_Partial()`（另有 `init_Fast` 快速整幅刷新） | `EPD().init()` → `getbuffer(img)` → `display(buf)` / `display_Partial(buf)` |
| UPS HAT (C) | `official/UPS_HAT_C/INA219.py` | — | — | — | `INA219(addr=0x43).getBusVoltage_V()`，電量% = `(V-3.0)/1.2*100`（官方範例既有公式） |

腳位提醒：Inky 的 `BUSY_PIN=17` 與 Waveshare 的 `RST_PIN=17` 剛好相同（兩者腳位定義各自獨立，不是同一顆晶片共用）。只要兩塊面板分別接在不同的 Pi（或不同時接在同一顆 Pi 上）就不會衝突；**不建議**未來把兩塊螢幕同時接在同一顆 Pi Zero 上，會有腳位規劃上的額外工作。

**整合原則**：`official/` 底下的三包程式碼定位是「參考原始碼」，不整包搬進專案：
- Inky → 直接 `pip install inky` 當相依套件。
- Waveshare → 只抽出目前用得到的 `epd4in26.py` + `epdconfig.py` 兩支檔案（ep_python 裡有 60 幾種面板的驅動，其餘不需要）。
- UPS → 只抽 `INA219.py`，把檔尾的 `__main__` demo 邏輯改寫成可重用的 `Battery` 類別。

---

## 1. 系統目標

1. 網頁版「自由排版」介面：使用者在瀏覽器上以拖曳/縮放方式，把「模組」自由排入畫布，畫布尺寸/色彩即對應實際螢幕（2.13" 或 4.26"）。
2. 功能以「模組」為單位擴充：未來新增功能 = 新增一個模組，不需要動核心架構；排版介面會自動出現新模組可供拖曳與設定。
3. 各模組可各自設定刷新頻率，系統依模組需求排程刷新（而非全部同頻率刷新，避免電子紙不必要的耗損與省電）。
4. UPS 電量 < 35% 時，Pi 自動關機。
5. 執行環境彈性：預設整套（設計伺服器 + 排版渲染 + 螢幕驅動）跑在 Pi Zero 2 W 上；若效能不足，設計/渲染搬到雲端主機，Pi 只做「輪詢拿圖 → 推到螢幕」的輕量端點。

---

## 2. 整體架構

系統切成三個邏輯角色，可以合而為一個行程（預設方案），也可以拆成兩台機器（備援方案）：

```
┌─────────────────────────────┐
│   Config / Layout Service    │  網頁排版介面 + REST API + 模組設定儲存
│   （Flask + SQLite）          │
└───────────────┬───────────────┘
                │ layout JSON + 模組資料
┌───────────────▼───────────────┐
│        Render Engine          │  依 layout + 模組資料合成畫面（Pillow）
│  （依裝置 profile 產生點陣圖）  │
└───────────────┬───────────────┘
                │ 本機函式呼叫（方案A）／HTTP 輪詢（方案B）
┌───────────────▼───────────────┐
│         Device Agent           │  跑在每顆 Pi 上：驅動螢幕、決定整幅/局部
│  （驅動螢幕 + UPS 電量看門狗）  │  刷新、UPS 監控與自動關機
└─────────────────────────────┘
```

### 方案 A（預設）：All-in-one，單顆 Pi Zero 2 W 全包
Config/Layout Service、Render Engine、Device Agent 是同一個 Python 行程/venv，排程器 tick 時直接呼叫合成函式，不經過網路，離線也能跑，延遲最低。使用者從同網段的電腦/手機瀏覽器連到 Pi 的網頁做排版。

### 方案 B（備援）：Pi 效能不足時的雲端拆分
Config/Layout Service + Render Engine 部署到一台常駐的雲端小主機（VPS）。Device Agent 改成極輕量的輪詢客戶端：

- `GET /api/devices/{id}/frame` → 回傳已合成好、已依面板格式量化好的點陣圖，以及 `refresh_mode`（full/partial）與 `next_poll_seconds`。
- Agent 只需要 `pillow`、`spidev`/`gpiozero`、`requests`，CPU/RAM 需求極低。
- UPS 監控**永遠在本機跑**（關機決策不能依賴網路）。

**關鍵設計原則：Device Agent 從第一天就寫成「呼叫一個 render API」的形式**，方案 A 只是把這個 API 用直接函式呼叫短路掉，不真的過網路。之後要切換方案 B，Agent 程式碼不用改，只改一個設定值（`render_endpoint: local` → `https://...`）。這樣就滿足「效能不足再把伺服器架到線上」的需求，同時預設用最簡單的本機方案起步。

---

## 3. 模組（Module）系統

這是滿足「依功能新增模組、再依模組排入介面」需求的核心機制。

### 3.1 模組介面（後端）
```python
class BaseModule:
    module_id: str                # 唯一識別，如 "clock", "weather"
    display_name: str
    default_size: tuple[int, int] # 畫布上預設寬高（px）
    min_refresh_interval: int     # 秒，模組允許的最短刷新間隔（防止使用者設太頻繁）
    config_schema: dict           # JSON schema，給排版介面自動產生設定表單

    def fetch_data(self, config: dict) -> dict: ...
        # 抓資料（API 呼叫、讀檔等），與畫圖分離，方便獨立快取/排程

    def render(self, data: dict, size: tuple[int,int], color_mode: str) -> PIL.Image: ...
        # 純畫圖，不做 I/O
```

- 新增模組 = 在 `server/modules/` 新增一個檔案並繼承 `BaseModule`，系統啟動時自動掃描註冊（不用改核心程式碼、不用改排版介面前端）。
- 排版介面的「模組面板」直接呼叫 `GET /api/modules` 取得所有已註冊模組的 manifest（含 icon、預設尺寸、config_schema），前端據此渲染可拖曳的模組清單與屬性表單 — 前端本身也不用因新模組而改程式碼。
- 初期建議模組：時鐘/日期、天氣、文字/RSS、圖片、電量顯示（讀 UPS daemon 的快取值，不重複去戳 I2C）、系統資訊。

### 3.2 刷新排程
- 每個「畫布上的模組實例」有自己的刷新間隔設定（不可低於該模組宣告的 `min_refresh_interval`）。
- 排程器（APScheduler 或簡單 loop）每次 tick：只對「間隔已到」的模組呼叫 `fetch_data()`（資料層快取），永遠重新合成整張畫面，再依面板能力決定刷新方式：
  - **支援局部刷新的面板**（Waveshare 4.26"）：只刷新有變動模組的 bounding box；但局部刷新次數過多會殘影，需設定「每 N 次局部刷新強制做一次整幅刷新」（vendor code 的標準做法）。
  - **僅整幅刷新的面板**（Inky pHAT）：多個模組短時間內都變動時，用「去抖動視窗」（例如 2 秒內的變動合併成一次）避免連續觸發整幅刷新。

---

## 4. UPS 電量模組

- 獨立 systemd 服務（`ups_daemon.py`），用 `INA219(addr=0x43)` 每 30–60 秒讀一次匯流排電壓，套用 `(V-3.0)/1.2*100` 換算成百分比並夾在 0–100 之間。
- **關機規則**：電量 < 35% 時觸發關機；為避免單次雜訊誤判，要求「連續 3 次讀值 < 35%」才動作。
- 關機前流程：記錄事件 → （可選）把「低電量」畫面推到螢幕做最後一次整幅刷新 → `systemctl poweroff`（需設定 polkit 規則讓執行帳號免密碼觸發，不要整支程式跑 sudo）。
- daemon 把最新讀值寫進一個本機共用檔（或小型 socket），「電量顯示模組」直接讀這個快取，不要自己再開一次 I2C 連線，避免匯流排搶用。

---

## 5. 裝置設定檔（Device Profile）

同一套系統要同時支援兩種面板，靠「裝置 profile」把解析度/色彩模式/是否支援局部刷新等差異參數化，layout 資料結構共用，但**畫布尺寸與可用色彩跟著 profile 走**（兩塊螢幕排版不共用同一份，每個裝置各自設計）：

```yaml
devices:
  - id: phat-01
    driver: inky_phat
    resolution: [212, 104]
    color_mode: 3color        # 黑/白/紅(或黃)
    partial_refresh: false
    min_full_refresh_interval_minutes: 5
  - id: waveshare426-01
    driver: waveshare_4in26
    resolution: [800, 480]
    color_mode: 4gray
    partial_refresh: true
    force_full_refresh_every: 10   # 每 10 次局部刷新強制整幅一次
```

---

## 6. 專案目錄規劃

```
epagerPi/
  official/                 # 現有的廠商參考程式碼，維持原樣不修改，只做「唯讀參考」
  server/                   # Config/Layout Service + Render Engine
    app.py
    api/                     # devices / layouts / modules 等 REST 端點
    modules/                 # 模組實作（BaseModule 子類別，自動掃描註冊）
    render/
      compositor.py           # layout JSON -> PIL Image
      device_profiles.py
    scheduler.py
    frontend/                 # 排版編輯器 SPA（純 JS + 拖曳套件）
    data/                     # SQLite / layout JSON
  device_agent/              # 跑在每顆 Pi 上
    drivers/
      inky_driver.py          # 包一層 pip 裝的 inky 套件
      waveshare_driver.py     # 包從 ep_python 抽出的 epd4in26.py + epdconfig.py
    ups_daemon.py             # 從 UPS_HAT_C/INA219.py 改寫
    agent.py                  # 呼叫 render（本機函式或 HTTP）→ 判斷刷新方式 → 驅動螢幕
    config.yaml
  docs/
    ARCHITECTURE.md           # 本文件
```

---

## 7. 排版編輯器（前端）重點

- 畫布 = 裝置實際像素解析度（依 zoom 顯示，2.13" 螢幕很小建議放大 3–4 倍），配色限制在該裝置實際可用色彩（含電子紙紅色偏暗的還原色），做到「所見即所得」。
- 左側：模組面板（從 `/api/modules` 動態產生，拖曳新增實例）。
- 右側：選取元件的屬性面板（依模組 `config_schema` 自動產生表單）+ 共通屬性（x/y/寬高/圖層順序/刷新間隔，下限鎖在模組宣告值）。
- 工具列：儲存草稿 / 發布（發布=立即重新合成並推播到裝置）/ 預覽（伺服器端先算好量化後的 PNG 給使用者看實際輸出效果，含網點/灰階模擬）。
- 技術選型建議：純 JS + GridStack.js 或 interact.js 做拖曳縮放，不上 React 這類重框架 — 前端跑在使用者電腦瀏覽器，不吃 Pi 效能，但輕量框架能加快開發、減少建置流程複雜度。

---

## 8. 開發流程計畫

| 階段 | 內容 | 產出／驗收方式 | 預估工期 |
|---|---|---|---|
| P0 環境與原始碼整理 | 建 venv，`pip install inky`，抽出 Waveshare 兩支檔案與 UPS INA219.py | 在實機 Pi Zero 2 W + Inky pHAT 上跑通官方 example | 0.5 週 |
| P1 核心骨架（單裝置、無編輯器） | 定義 `BaseDisplayDriver.show(image, mode)`，先實作 `InkyDriver`；寫死一份 layout + 1–2 個模組（時鐘、純文字）跑通合成→推播；UPS daemon 獨立跑通 <35% 關機（可先調高門檻測試） | 實機顯示正確、關機邏輯以模擬電量驗證 | 1–1.5 週 |
| P2 模組系統與排程器 | 落實 `BaseModule` 介面與自動註冊，加上刷新排程；新增天氣、圖片、電量顯示模組 | 多模組各自不同刷新頻率、正確合成 | 1 週 |
| P3 Config/Layout 後端 API | Flask + SQLite，devices/layouts/modules CRUD，模組 manifest 端點 | API 可用 Postman/curl 驗證 CRUD | 1–1.5 週 |
| P4 排版編輯器前端 | 拖曳/縮放畫布、屬性表單、儲存/發布/預覽 | 不確定性最高的階段，先做無吸附/無 undo 的最小版本再迭代 | 1.5–2 週 |
| P5 雲端拆分備援（視 P1–P4 實測效能決定是否需要） | Config+Render 搬 VPS，Agent 改輪詢 `/frame`，加裝置 token 驗證與心跳/電量回報 | 拆分後 Pi 端 CPU/RAM 使用量下降可驗證 | 0.5–1 週 |
| P6 Waveshare 4.26" 支援（硬體到貨後） | 新增 `waveshare_4in26` driver、裝置 profile（4gray + 局部刷新），驗證殘影抑制邏輯 | 實機驗證局部刷新與定期強制整幅刷新 | 0.5–1 週 |
| P7 維運強化（持續進行） | 各服務 systemd 化（開機自動啟動、崩潰自動重啟）、SPI/BUSY pin 掛住的逾時重試、編輯器基本驗證機制（帳密或 token） | — | 持續 |

---

## 9. 待確認事項（會影響 P3/P4 的實作細節）

1. Web 後端框架：建議 **Flask**（簡單、符合 Pi Zero 規模），或要用 FastAPI（非同步、schema 驗證較完整）？
2. 前端技術：建議純 JS + GridStack.js/interact.js（開發快、依賴少），或偏好 React/Vue？
3. 排版編輯器要不要基本登入驗證（尤其方案 B 上雲端後，網址可能對外可見）？
4. 是否需要「多套排版」（例如日/夜情境切換）？目前規劃 MVP 先做「每裝置一份現用 layout」，多情境留到之後。

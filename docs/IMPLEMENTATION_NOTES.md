# 初版實作說明

對應 `docs/ARCHITECTURE.md` 的規劃，這是第一個可以真的跑起來的版本。這份文件記錄
「做了什麼、怎麼跑、還缺什麼」，之後接續開發前建議先看一遍。

## 這一版做了什麼

- **模組系統**（`server/modules/`）：`BaseModule` 介面 + 4 個模組（`clock_bar` 頂部日期時間列、
  `progress_bar` 進度條/量表、`stat_pair` 標籤數值列表、`mascot` AA 表情吉祥物動畫），
  在 `registry.py` 註冊即可用，排版編輯器的模組面板會自動列出來。
  這 4 個模組靠 config 組合，已經能拼出你畫的那張「生存進度」dashboard（見
  `data/layouts/waveshare426-01_dashboard.json`）。
- **通用資料來源**（`server/modules/datasource.py`）：任何模組的任何數值欄位都能設定
  `manual`（手動填值）、`http`（打 API，支援相對路徑 `/api/...` 會自動補上本機網址）、
  `battery`（讀 UPS daemon 的電量快取）、`time_until` / `time_progress`（不用外部資料，
  直接算「離某個時間還剩多久／經過百分比」，生存進度條跟倒數計時就是用這個，會真的動）。
- **渲染引擎 + 刷新策略**（`server/render/compositor.py`）：合成畫面、依裝置色彩模式量化
  （3 色/1bit/4 階灰階），並且用「每個元件畫出來的內容有沒有變」自動判斷 dirty 區域 →
  動畫類模組自然只在真的變化時才觸發刷新；裝置不支援局部刷新時會節流成最短整幅刷新間隔，
  已經過測試（見下方「測試過的東西」）。
- **情境系統**（`server/render/scenes.py`）：依星期/時間區間/是否假日挑選要用哪份 layout，
  兩個裝置各自預設 4 種情境（平日上班／平日下班後／週末／假日），示範「同一個裝置在不同
  情境顯示不同內容」（微雪 4.26" 的假日/週末/下班後都會切到 `_offhours` 那份 layout）。
- **UPS 低電量關機**（`device_agent/ups/`）：`INA219.py` 改寫自官方範例，`Battery` 類別
  加上「連續 N 次都低於門檻才關機」的防雜訊判斷，`ups_daemon.py` 是可以直接用 systemd
  跑的獨立服務，讀值同時寫進共用快取檔給「電量顯示」用的 `battery` 資料來源讀。
- **兩套部署模式**：
  - Pi 本機（`run_pi.sh` / `systemd/*.service`）：`AUTH_ENABLED=0`，不驗證，JSON 檔案儲存，
    排程器直接呼叫合成函式（同行程，無網路開銷）。
  - 線上 Docker（`docker/`）：`docker compose up`，`AUTH_ENABLED=1`，網頁編輯器用 Basic
    Auth、API/裝置輪詢用 Bearer token；公開 HTTPS 與網域由外部 Cloudflare Tunnel 處理。
    兩種模式共用同一份 `server/` 程式碼，device_agent 從一開始就是「呼叫 render API」
    的形狀，要從 all-in-one 切到線上拆分只要改 `device_agent/config.yaml` 的
    `render_endpoint`，不用改程式碼。

## 怎麼跑

### 開發機（沒有電子紙，純測試排版/API）
```bash
cd epagerPi
pip install -r requirements.txt --break-system-packages
EPAGERPI_AUTH_ENABLED=0 python3 -m server.app
# 開瀏覽器 http://localhost:8080 進排版編輯器
# 或直接打 http://localhost:8080/api/devices/waveshare426-01/frame.png 看合成結果
```
沒有真的接電子紙的裝置，`data/devices.json` 可以先把 `driver` 改成 `"mock"`（見
`device_agent/drivers/mock_driver.py`），排程器會把畫面存成 PNG 而不是真的去操作硬體。

### Pi Zero 2 W（接了 Inky pHAT）
```bash
pip install -r requirements.txt --break-system-packages
pip install -r requirements-hardware.txt --break-system-packages   # inky/gpiozero/spidev/smbus2
sudo apt install fonts-noto-cjk      # 畫面上的中文字要靠這個，不裝會空白
raspi-config   # 開 SPI（Inky）/I2C（UPS）
cp device_agent/config.example.yaml device_agent/config.yaml   # 依需要調整
./run_pi.sh phat-01
```
長期跑建議改用 `systemd/` 底下三個 unit（把裡面的 `/home/pi/epagerPi` 換成實際路徑，
`cp` 到 `/etc/systemd/system/` 後 `systemctl enable --now`）。

### 線上 Docker 版
```bash
cd docker
cp .env.example .env   # 填 AUTH_PASS / API_TOKEN
# cloudflared Tunnel 容器必須已加入 external Docker network「cloudflared」。
# Tunnel 的 origin service 設為 http://epagerpi:8080（Docker 內網名稱，不是公開網域）。
docker compose up -d --build
```
完整 Tunnel 前置條件與範例見 `docker/README.md`。本 Compose 不發布 host port，也不再包含
Caddy；公開網域與 HTTPS 由 Cloudflare Tunnel 管理。
Pi 上改用 `device_agent/agent.py`（`render_endpoint` 設成這台線上主機網址 + `api_token`）
輪詢拿圖、驅動螢幕；UPS daemon 一樣獨立在 Pi 上跑，不受這個模式影響。

## 測試過的東西（在沒有實體螢幕的開發機上）

- 模組 render + compositor 合成，輸出的 PNG 目視比對跟原本畫的 mockup 排版一致。
- `waveshare426-01`（支援局部刷新）：連續打兩次 `/frame.png`，第二次只有動畫模組
  （吉祥物）在 dirty 清單裡；同一個 6 秒動畫區間內第三次打則整個 `none`，證明「只有真
  的變化才觸發刷新」有效。
- `phat-01`（只能整幅刷新，`min_full_refresh_interval_seconds=300`）：第一次 `full`，
  1 秒後再打雖然吉祥物想動但被節流成 `none`——確認不會因為動畫去頻繁整幅刷新面板。
- `value_source` 的 `http`（相對路徑自動補本機網址）、`time_progress`/`time_until`
  （真的會隨時間變化）、3 色/1bit 量化後的實際輸出色票都正常。
- Auth：`AUTH_ENABLED=0` 完全不擋；`=1` 時沒帶驗證回 401，Basic Auth 跟 Bearer token
  都能各自通過。
- 一個模組 config 寫錯（如 progress_bar 的 min==max）不會讓整張畫面壞掉，只有那個元件
  顯示錯誤框。
- 硬體驅動（`inky_driver.py` / `waveshare_driver.py`）在非 Pi 機器上會拋出清楚的
  `RuntimeError` 中文訊息，而不是匯入階段直接 crash（因為 `epdconfig.py` 在非 Pi
  硬體上 import 就會失敗，這是官方程式碼本身的行為）。

**沒有測試到的**（沒有實體硬體/瀏覽器環境）：
- Inky pHAT / 微雪 4.26" 真的接上去的顯示效果、局部刷新殘影狀況、UPS 電量讀值準確度。
- 排版編輯器前端（`server/frontend/`）的拖曳/縮放操作是純 vanilla JS 手刻，邏輯上跑過
  一遍但沒有在真的瀏覽器裡點過，上機後如果拖曳手感怪怪的再回報。

## 更新記錄：拆分模式改成樹莓派本機渲染

原本拆分模式（`device_agent/agent.py`）是打 `/frame.png` 拿「伺服器已經畫好、也已經
判斷完刷新方式」的圖，樹莓派只負責推到螢幕。這樣有兩個問題：倒數計時/生存進度這類
「本地就能算」的數值其實是在伺服器端解析後當成固定資料快取起來，要等下次
`poll_interval_seconds`（預設 30 秒）才會更新，畫面上的動態感很卡；而 dirty-box
比對、整幅/局部刷新節流這些「跟這台特定螢幕的刷新歷史綁在一起」的判斷也放在伺服器端，
邏輯上比較繞。

現在改成：

- `server/modules/datasource.py` 新增 `is_network_source()`：資料來源只分「要打網路
  的（`http`）」跟「本地就能算的（`manual`/`time_until`/`time_progress`/`battery`）」。
  `progress_bar`/`stat_pair` 的 `fetch_data()` 只解析 `http` 型別並依
  `refresh_interval` 節流快取；其餘型別一律留到 `render()` 當下即時解析。
- `server/render/compositor.py` 拆成兩段：`resolve_layout_elements()`（選 layout、
  只解析 http 資料，可在雲端跑）跟 `render_from_elements()`（畫圖＋雜湊比對 dirty
  區塊＋整幅/局部刷新節流，純本機運算，一定要在驅動螢幕的那台機器上跑）；
  `render_device()` 是兩段的合併版，`/frame.png`、`/frame-meta`、all-in-one 模式
  的行為完全沒變。
- 新增 `GET /api/devices/<id>/layout-data`：只回傳 profile + layout + 每個元件的
  config + 已解析的 http 資料，不含圖也不含刷新判斷。
- `device_agent/agent.py` 改成定期抓這支 `layout-data`（頻率仍是
  `poll_interval_seconds`），但用獨立的 `tick_seconds`（預設 1 秒）在本機重複呼叫
  `render_from_elements()` 合成畫面、判斷刷新、推到螢幕——倒數計時/吉祥物動畫因此
  在拆分模式下也能保持即時，不受 30 秒輪詢間隔限制。

**副作用（順手修的一個既有 bug）**：`render_from_elements()` 現在會依元件的 `z`
欄位排序再合成（原本 `_render_elements()` 完全沒排序，`z-index` 欄位其實沒被
compositor 用到，只有編輯器畫布的 CSS 疊層順序有效）。如果既有 layout 有刻意疊放的
元件、且 `z` 沒設對，合成結果的疊層順序現在會跟以前不一樣，請檢查一下。

**注意**：`battery` 型別本來就只能在樹莓派本機正確運作（讀本機的
`data/runtime/battery.json`），拆分模式下如果 `fetch_data()` 在伺服器端誤解析這個
型別會直接讀不到檔案、整組回傳 fallback；這次改完之後 `battery` 已經跟其他本地型別
一起留到 `render()`（本機端）才解析，行為才是正確的——這其實是這次順便補上的一個
潛在問題，先前拆分模式如果用到電量顯示，理論上會一直顯示 fallback 值。

## 更新記錄：排版編輯器改成格線貼齊

`server/frontend/editor.js` 拖曳/縮放元件時，x/y/w/h 現在會貼齊一個固定間距的格線
（右上角新增「格線貼齊」開關 + 「格線(px)」輸入框，預設開啟、4px），並限制縮放不能
小於 `MIN_ELEMENT_W`/`MIN_ELEMENT_H`（16px），避免全自由拖曳出太細碎、對不齊的區塊。
畫布背景會顯示淡淡的格線提示。存進 layout 的座標格式完全沒變，仍然是實際像素整數，
格線只影響「拖曳時怎麼取整數」。

## 更新記錄：圖片素材庫 + 樹莓派自動同步

新增「上傳圖片、雲端存正本、樹莓派自動偵測沒有就下載」這條路徑，設計原則：**版本判斷
完全靠檔名裡的內容 hash，不用另外維護一份「目前最新版本」的狀態、也不用推播機制**——
沿用既有的 poll 迴圈就好。

- `server/assets.py`（新）：素材庫本體。上傳的檔案存在
  `config.DATA_DIR/assets/<id>_<hash12>.<ext>`，檔名本身帶內容雜湊；另外維護一份
  `assets.json` 純粹給編輯器圖庫列表用（檔名/大小/上傳時間），不是版本判斷依據。
  伺服器端（正本）跟樹莓派端（下載回來的快取）用的是**同一份程式碼、不同的
  `EPAGERPI_DATA_DIR`**（各自的 repo 根目錄），所以路徑規則自動對齊，不用特別處理。
- `server/api/assets.py`（新）：`POST /api/assets`（上傳，multipart）、
  `GET /api/assets`（列表）、`GET /api/assets/<id>`（下載原始檔，Pi 端下載也是打
  這支）、`DELETE /api/assets/<id>`。
- `server/modules/image.py`（新）：`image` 模組，config 存 `asset_id` + `fit`
  （cover/contain/stretch）。`fetch_data()` 只查本機 `assets.json` 拿目前的 hash
  （這一步不是網路請求，但因為 `assets.json` 只存在伺服器端，所以在拆分模式下這步
  驟自然會在 `resolve_layout_elements()` 那個「伺服器端」階段執行，把一小段 hash
  字串透過 `layout-data` 帶給樹莓派）；`render()` 一律讀本機檔案，圖片還沒同步到時
  顯示「圖片下載中…」佔位框，不會讓整個模組壞掉。
- `device_agent/agent.py` 新增 `sync_assets()`：每次拿到新的 `layout-data` 後，
  掃一遍裡面用到的 `image` 模組，比對「這個 asset_id + hash 組成的檔名，本機存在
  嗎」，不存在才打 `GET /api/assets/<id>` 下載存進本機同樣的路徑規則。單一素材下載
  失敗不影響其他素材/其他模組，下一輪 poll 自動重試。
- 編輯器（`server/frontend/`）新增「圖片素材庫」面板：上傳檔案＋縮圖清單，點縮圖
  直接套用到目前選取的圖片元件（自動帶入 `asset_id`）。

已測試：上傳→下載→在模擬的「樹莓派本機空白環境」（獨立 `EPAGERPI_DATA_DIR`）跑
`sync_assets()`，確認第一次真的下載、第二次因為檔案已存在而跳過不重複下載；
`image` 模組在量化前後的畫面輸出也都確認正常。

**已知限制**：`assets.json` 索引檔案跟既有的 `store.py` 一樣是單一行程內用
`threading.Lock` 保護，沒有做跨行程/跨機器的併發控管——這種個人專案規模（上傳頻率低）
不會是問題；素材目前也沒有「有沒有被任何 layout 使用」的清理機制，刪除功能有做
（`DELETE /api/assets/<id>`）但要自己記得手動清不再用的素材，沒有自動回收。

## 更新記錄：可換自訂字型

新增環境變數 `EPAGERPI_FONT_PATH`（見 `server/config.py`），指到一個 `.ttf`/`.ttc`/
`.otf` 檔案，所有模組共用的 `load_font()`（`server/modules/drawing.py`）就會優先用
這個字型，找不到檔案或字型本身壞掉會自動退回內建的 Noto Sans CJK 候選清單，不會
crash。目前是**全域換字型**（所有模組共用同一套），不是每個模組各自選字型——如果之後
真的需要模組各自指定字型，要另外在各模組的 `config_schema` 加欄位。線上 Docker 版
的 `docker-compose.yml`／`.env.example` 也一併接了這個變數，字型檔放
`data/fonts/` 底下（跟著既有的 volume 掛載）就會被拿到。已用「沒設定／指到真的字型
檔／指到不存在的路徑」三種情況測過，都符合預期。

## 更新記錄：補齊上面四項功能的實作（先前只有筆記、程式碼沒真的落地）

盤點時發現上面「拆分模式改成樹莓派本機渲染」「排版編輯器格線貼齊」「圖片素材庫」
「可換自訂字型」這四段筆記寫了，但實際檔案裡完全找不到對應程式碼（`compositor.py`
只有舊版的 `render_device()`、`editor.js` 沒有 snap 邏輯、`server/assets.py` 等檔案
不存在、`config.py` 沒有 `FONT_PATH`），這次照著上面的設計把程式碼真的寫出來，並
補上筆記裡提過但也沒做的 `detect_hardware.py` 診斷工具：

- `server/render/compositor.py`：拆成 `resolve_layout_elements()` /
  `render_from_elements()` / `render_device()`（合併版，內部呼叫前兩者，`/frame.png`、
  `/frame-meta`、all-in-one 模式行為不變）。
- `server/api/frame.py`：新增 `GET /api/devices/<id>/layout-data`。
- `server/modules/datasource.py`：新增 `is_network_source()`。
- `server/modules/progress_bar.py` / `stat_pair.py`：`fetch_data()` 改成只解析/
  快取 http 型別，manual/battery/time_until/time_progress 留到 `render()` 當下
  即時呼叫 `resolve_value()`。
- `device_agent/agent.py`：改成輪詢 `layout-data`（`poll_interval_seconds`），
  再用獨立的 `tick_seconds`（設定檔新增此欄位，預設 1 秒）在本機重複呼叫
  `render_from_elements()`；新增 `sync_assets()`。
- `server/assets.py`、`server/api/assets.py`、`server/modules/image.py`：圖片素材庫
  三件套，行為如上面「圖片素材庫」那段筆記所述。`registry.py` 已註冊 `image` 模組。
- `server/frontend/index.html` / `editor.js` / `style.css`：格線貼齊控制項 + 邏輯、
  圖片素材庫面板（上傳/縮圖列表/套用到選取元件/刪除）。
- `server/config.py` / `server/modules/drawing.py`：`EPAGERPI_FONT_PATH`。
- `docker/docker-compose.yml` / `.env.example`：帶入 `EPAGERPI_FONT_PATH`。
- `device_agent/detect_hardware.py`（新）：`python -m device_agent.detect_hardware`
  依序嘗試初始化 Inky pHAT / 微雪 4.26" / 讀 UPS 電量，回報成功或原始錯誤訊息；
  `--show` 可以額外推一張測試圖到能初始化成功的螢幕；`--only inky|waveshare|ups`
  只測其中一項。

**這次測試過的東西**（一樣是沒有實體硬體的開發機，且這個工作環境沒有網路可以
`pip install flask`，所以 Flask route 這層是用既有寫法比對＋人工檢查，其餘都是
實際跑過）：

- `resolve_layout_elements()` 回傳的 dict 確認可以 `json.dumps()`（`/layout-data`
  一定要能序列化）。
- 用一份涵蓋 `clock_bar` / `progress_bar`（`time_progress` 型別）/ `stat_pair`
  （`manual` 型別）/ `image` 四種模組的假 layout，實際跑 `render_from_elements()`
  和 `render_device()`，畫面合成成功，dirty-box 判斷正常（第一次全部算 dirty，
  局部刷新裝置回傳 `partial`）。
- 確認 `server.render.compositor` 整條匯入鏈不會拉進 `flask`（檢查
  `sys.modules`），代表拆分模式的 Pi 上跑 `device_agent/agent.py` 不需要額外裝
  flask（只要不去跑 `server/app.py`）。
- `server/assets.py` 存檔/列表/刪除、`server/modules/image.py` 的
  `fetch_data()`/`render()` 都實測跑過，包含：假的（非法）圖片內容會顯示「圖片
  讀取失敗」佔位框、真的 PNG 的 cover/contain 縮放裁切都正常、`asset_id` 沒填
  或素材已被刪除時分別顯示對應的佔位框文字。
- `datasource.is_network_source()` 對 manual/http/battery/None 都測過。
- `server/frontend/editor.js` 用 `node --check` 過語法檢查；沒有瀏覽器環境可以
  實際點，跟原本「拖曳/縮放沒在真瀏覽器測過」的已知限制一樣，上機後如果格線貼齊/
  素材庫面板手感怪怪的再回報。
- `server/api/assets.py`、`/layout-data` 端點本身（Flask route）沒有實機跑過（這個
  工作環境裝不了 flask），寫法完全比照現有的 `layouts.py`/`devices.py`，邏輯上
  檢查過但建議你在真正能跑 flask 的機器上第一次啟動時，順手 curl 一下這兩支端點
  （例如 `curl localhost:8080/api/devices/waveshare426-01/layout-data`）。

## 已知限制／下一步

1. **微雪驅動是重新實作的，不是官方檔案，init() 命令序列還沒上機驗證**：
   `device_agent/vendor/epd4in26.py` + `epdconfig.py` 現在有內容了，但因為這個工作
   環境拿不到 `official/ep_python/lib/waveshare_epd/` 原始檔，是依公開接線方式跟
   SSD1677 系列控制器的通用命令格式重新寫的（見該檔案開頭的風險說明）。控制流程已經
   用假的 epdconfig 測過沒有邏輯錯誤，但實際 SPI 命令位元組完全沒有實體面板驗證過。
   上機後如果畫面沒反應/亂碼，先看 `epd4in26.py` 裡 `init()` 的命令序列；拿到官方
   檔案的話整支覆蓋掉即可，`waveshare_driver.py` 呼叫的介面不用改。4 階灰階
   （4gray）故意沒實作（需要面板專屬 LUT，猜測填入風險太高），呼叫會丟
   `NotImplementedError`；目前 `waveshare426-01` 的 `color_mode` 是 `1bit`，不受影響。
   新增了 `python -m device_agent.detect_hardware` 診斷小工具（見上面更新記錄），
   上機後可以跑跑看哪塊面板真的初始化成功。
2. **UPS 充放電方向未上機驗證**：`device_agent/ups/battery.py` 裡 `current_ma < 0` 判斷
   「正在充電」是先假設的極性，上機後如果方向相反，把那行的 `<` 改成 `>` 即可。
3. **國定假日清單只填了固定日期**：`data/holidays_tw.json` 只放年年不變的幾個（元旦、
   228、勞動節、國慶），春節/端午/中秋這類移動式假期沒有把握年份對照，故意留空避免填錯
   反而讓情境判斷失準；請對照人事行政局官方行事曆補齊，或改接行事曆 API（`is_holiday`
   判斷邏輯支援直接把 `get_holidays()` 換成打 API）。
4. **emoji/特殊符號字型涵蓋不全**：Noto Sans CJK 沒有大部分 emoji（如 ☄），config 裡用
   到會變空白方塊，範例 layout 已經避開；真的要用可以另外裝 emoji 字型並擴充
   `server/modules/drawing.py` 的字型清單，或用 `EPAGERPI_FONT_PATH` 換一套涵蓋更廣的
   字型。
5. **屬性面板目前是「原始 JSON 編輯」**：新增元件時會照 `config_schema` 的預設值建立
   config，但編輯時是直接改 JSON textarea，還沒有做成每個欄位各自一個輸入框的表單
   （config_schema 裡已經有欄位型別/label 資訊，之後要做成真正的表單只是前端工作）。
6. **今日出勤／本月統計目前是手動填值**：沒有串真的出勤系統，示範時用 `manual` 值。
   要串真的資料只要把對應欄位的 `value_source` 換成 `http` 類型指到你的出勤系統 API，
   不用改模組程式碼。
7. **多裝置/多程序共享狀態**：`compositor.py` 的 dirty-box 快取、`store.py` 的檔案鎖都
   是單一 Python 行程內有效；Docker 用 gunicorn 多 worker 時，同一裝置被不同 worker
   處理可能會讓「只有變化才刷新」的判斷偶爾多算一次 dirty（不影響正確性，只是偶爾多刷一
   次），單一裝置固定綁一顆 Pi 排程器的情況下不受影響。
8. **時區**：情境判斷用系統本地時間，Pi 要記得 `sudo timedatectl set-timezone Asia/Taipei`
   （或用 raspi-config 設定），不然平日上班/下班後的時間區間會全部跟著系統時區跑掉。
9. **圖片素材沒有使用中檢查**：`server/assets.py` 沒有「這個素材有沒有被任何 layout
   引用」的清理機制，`DELETE /api/assets/<id>` 刪掉之後，還在用它的 `image` 元件會
   變成「找不到素材」佔位框，要自己對照 layout JSON 手動清不再用的素材。
10. **拆分模式下 Pi 端現在需要一份完整的 `server/` 套件**：`device_agent/agent.py`
    會 import `server.render.compositor` / `server.modules.*` 來做本機渲染，所以
    Pi 上要有完整的 repo checkout（不能只複製 `device_agent/` 資料夾），但確認過
    不需要額外裝 flask（見上面「這次測試過的東西」）。
11. **格線貼齊只在前端擋，不會回頭改舊 layout**：既有 layout 裡沒對齊格線的元件不會
    被自動「吸過去」，只有之後拖曳/縮放它時才會套用格線。

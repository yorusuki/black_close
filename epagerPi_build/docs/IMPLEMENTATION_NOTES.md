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
    Auth、API/裝置輪詢用 Bearer token，搭配 Caddy 反向代理自動 HTTPS。
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
# Caddyfile 裡的網域換成你自己的（需要 DNS 已指過去），沒有網域先只開 epagerpi service 測
docker compose up -d
```
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

## 已知限制／下一步

1. **微雪驅動檔案還沒放進 repo**：`device_agent/vendor/epd4in26.py` + `epdconfig.py`
   需要從 `official/ep_python/lib/waveshare_epd/` 複製過來（只抽這兩支，其餘 60 幾種
   面板不需要）。程式碼裡的 import 路徑已經預留好，複製過去就能用。
2. **UPS 充放電方向未上機驗證**：`device_agent/ups/battery.py` 裡 `current_ma < 0` 判斷
   「正在充電」是先假設的極性，上機後如果方向相反，把那行的 `<` 改成 `>` 即可。
3. **國定假日清單只填了固定日期**：`data/holidays_tw.json` 只放年年不變的幾個（元旦、
   228、勞動節、國慶），春節/端午/中秋這類移動式假期沒有把握年份對照，故意留空避免填錯
   反而讓情境判斷失準；請對照人事行政局官方行事曆補齊，或改接行事曆 API（`is_holiday`
   判斷邏輯支援直接把 `get_holidays()` 換成打 API）。
4. **emoji/特殊符號字型涵蓋不全**：Noto Sans CJK 沒有大部分 emoji（如 ☄），config 裡用
   到會變空白方塊，範例 layout 已經避開；真的要用可以另外裝 emoji 字型並擴充
   `server/modules/drawing.py` 的字型清單。
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

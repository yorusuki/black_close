# 程式碼審查與風險報告

檢查日期：2026-09-10

## 摘要

程式碼的模組邊界、失敗後持續排程與硬體抽象是優點；主要風險集中在「把 API payload、素材檔與 HTTP URL 視為可信任資料」。這與可公開部署、低權限運行及長期維護不相容。

## 優點

- 裝置 driver、渲染、資料來源與網頁 API 分層清楚。
- 模組渲染失敗時用 placeholder，scheduler／agent 單次失敗會記錄並於下一輪重試。
- UPS 關機要連續多次低於門檻才觸發，降低雜訊造成誤關機。
- 設定檔與本機 secret 檔已列入 `.gitignore`，沒有發現硬編碼 token。
- 以 image hash 同步素材，避免每次輪詢重複下載。

## 發現事項

| 嚴重度 | 發現 | 證據 | 影響與建議 |
| --- | --- | --- | --- |
| High | HTTP data source 可向任意 URL 發 GET | `server/modules/datasource.py:78-88`；layout API 可任意寫 config | 可被用來掃描 server／Pi 可達的內網或雲端 metadata endpoint，也可設定過長 timeout 消耗 worker。改成受控 integration、allowlist、DNS/IP 解析後封鎖 loopback/link-local/private ranges、限制 timeout/redirect/回應大小。 |
| High | 素材上傳沒有大小、MIME、影像解碼或副檔名限制 | `server/api/assets.py:20-29`、`server/assets.py:51-70` | 任意檔可一次讀入記憶體並永久占用磁碟；HTML/SVG 等內容經下載端點可造成同源內容風險。只接受驗證過的 raster image，限制 request/檔案大小，使用安全解碼，下載設 attachment／固定安全 MIME。 |
| High | 前端將 API／素材資料直接插入 `innerHTML` | `server/frontend/editor.js:60, 286, 475-490` | 裝置 ID、layout 的 `module_id`、原始檔名可形成 stored XSS；未驗證 API 又讓風險擴大。以 `textContent`、DOM node 與 attribute setter 取代字串 HTML；所有 API 資料先驗證。 |
| High | Pi／開發模式預設未驗證且 listen all interfaces | `server/config.py:15,25`、`run_pi.sh:15`、systemd server unit | 同網段任一人可讀寫裝置、layout、scene 和素材，並結合上述問題。預設 bind 127.0.0.1 或啟用驗證；公開／跨網段只允許 TLS 反向代理後存取。 |
| High | API mutation 無 schema、型別、範圍或 ID 驗證 | `server/api/devices.py:23-30`、`layouts.py:23-27`、`scenes.py:16-20` | 實測 device PUT 接收 JSON array 回 500；無效尺寸／情境／URL 會在稍後的渲染階段失敗。建立 Pydantic/JSON Schema 或明確手寫 validator；一律回 400／422，限制元素尺寸、座標、refresh interval、module id 與 scene 格式。 |
| Medium | root UPS service 直接從可變的專案目錄載入 Python | `systemd/epagerpi-ups.service:7-12` | 任一可修改該目錄的人都可能在 root service restart 時執行程式。以專用低權限帳號運行並使用受限 poweroff helper/polkit；部署檔案應由 root 擁有且唯讀。 |
| Medium | 多程序 JSON 寫入沒有跨程序鎖 | `server/store.py:17-25` 與 Docker 的 2 workers | 兩個 process 共享固定 `.tmp` 路徑，可能互相覆蓋／replace，造成 500 或遺失更新。短期單 worker；長期 SQLite 或檔案鎖與唯一 temp file。 |
| Medium | Cloudflare Tunnel 的 Docker network 是外部依賴 | `docker/docker-compose.yml` | Tunnel 容器必須加入同一個 `cloudflared` network，且 ingress origin 要指向 `http://epagerpi:8080`；否則服務會不可達。保留內層 Basic Auth／Bearer token。 |
| Medium | Waveshare 首次刷新不是 full | `server/render/compositor.py:136-144`；本次 smoke test header 為 `partial` | 初次上電是否能正確建立面板基準狀態未證實。初始化時強制 full，並用實機驗證局部刷新與殘影策略。 |
| Low | auth 比較使用一般 `==` | `server/auth.py:18-30` | 網路時序風險小但可避免；用 `hmac.compare_digest`。同時為 login 加 rate limit。 |
| Low | 過寬例外處理降低可觀測性 | `datasource.py:84-88`、`compositor.py:94-98` 等 | 設計上保服務可用合理，但失敗缺少來源／錯誤分類紀錄。保留 fallback，同時記錄受控且不含 secret 的 warning/metric。 |

## 修正優先序

1. 先修 API schema 驗證、前端輸出編碼、素材型別／大小限制與 HTTP destination policy。
2. 取消未驗證的對外 bind，將 UPS 自 root 收斂為最小權限。
3. 補 API、renderer 和 security regression tests，再處理 JSON 多程序一致性與 Docker 連線文件。
4. 在實機確認 Waveshare first-full、partial refresh、sleep/recovery 後才調整刷新策略。

## 風險結論

若只在完全隔離的開發網段使用，核心功能可做展示；若要讓使用者上傳素材、設 HTTP 資料來源或透過網路操作，High 項目必須先處理。這不是單純的 hardening，而是目前 API 接受不可信輸入時的正確性與安全邊界缺失。

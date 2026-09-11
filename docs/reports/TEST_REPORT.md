# 測試與驗證報告

檢查日期：2026-09-10  
結果判定：**Not Ready（不適合宣稱為正式上線版）**

理由不是核心 smoke test 失敗，而是沒有專案自有自動化測試、硬體與 systemd 無法在目前 macOS 開發機驗證，且存在上線前必須修正的安全與輸入驗證問題。

## 已執行與通過的檢查

| 檢查 | 結果 | 證據／範圍 |
| --- | --- | --- |
| Python 語法編譯 | 通過 | 45 個自有 Python 檔以 `compile()` 檢查，0 syntax error。 |
| JSON 語法 | 通過 | `data/` 下所有 JSON 以 `python -m json.tool` 驗證。 |
| Compose 設定 | 通過 | 以非機密測試值執行 `docker compose ... config --quiet`，exit 0。 |
| Flask smoke test | 通過 | `/healthz`、modules、devices、layouts、scenes、兩個裝置的 frame/frame-meta 與 unknown device 404。 |
| PNG render | 通過 | Waveshare `frame.png` 回傳 `image/png`，4,154 bytes。 |
| Auth smoke test | 通過 | auth enabled 時 API 未驗證為 401，Basic Auth 與 Bearer token 均為 200，`/healthz` 保持 200。 |
| 錯誤處理抽測 | 發現問題 | 裝置 PUT 收到 JSON array 回 500，非預期 4xx。 |
| 素材安全行為抽測 | 發現問題 | 上傳 `review.html` 後，下載回應為 `text/html` 且 `Content-Disposition: inline`；證實任意檔案處理問題。 |

所有 Flask 測試都使用隔離的暫存 `EPAGERPI_DATA_DIR`，未寫入專案正式 `data/`。測試期間出現 urllib3 對本機 LibreSSL 的警告；未影響目前本機 loopback smoke test，但正式環境應使用受支援的 OpenSSL 版本。

## 自動化測試現況

- `unittest discover -v`：exit 0，但執行 **0 tests**。
- `pytest -q`：pytest 未安裝，exit 1。
- 專案自有路徑沒有 `tests/`、`test_*.py`、`pytest.ini`、coverage 設定或 CI workflow。
- `official/inky-main/tests/` 屬於廠商參考程式碼，不能當成 epagerPi 的測試覆蓋率。

因此，現有文件所稱的測試是手動／探索式驗證，不是可重複的專案測試流程。

## 無法在此環境完成的驗證

| 項目 | 原因 | 正確驗收方式 |
| --- | --- | --- |
| Inky pHAT 顯示與刷新壽命 | 無 Raspberry Pi 和面板 | 實機執行硬體診斷、full refresh、連續排程測試。 |
| Waveshare 4.26 局部刷新／殘影 | 硬體未驗證 | 首次畫面、20 次 partial 後 full refresh、斷電恢復、1bit／4gray 都要驗收。 |
| UPS INA219 電壓、充放電方向、關機 | 無 I2C 與 UPS | 用已校正電壓源或對照儀表，安全地模擬連續低電量。 |
| systemd unit | macOS 沒有 `systemd-analyze` | 在目標 Raspberry Pi 執行 `systemd-analyze verify`、enable/restart/reboot test。 |
| Docker image build／Cloudflare Tunnel | 未執行 image build 與真實 Tunnel／公開網域 | CI build image；在 staging 以 Tunnel 測試 HTTPS、Access 與 `http://epagerpi:8080` origin 連線。 |
| 前端拖曳縮放與素材操作 | 無瀏覽器 E2E 測試 | Playwright/Cypress 以真實瀏覽器驗收。 |

## 建議建立的測試流程

1. **Unit tests**：情境跨午夜／priority、JSON schema validator、data source path/fallback、電量百分比與低電量連續計數、量化與 refresh decision。
2. **API integration tests**：每個 mutation 的合法／非法 JSON、auth、404、素材大小與類型、資料不被錯誤請求寫入。
3. **Renderer regression tests**：固定時間輸入、固定字型，對範例 layout 比對 PNG 雜湊或像素容許差異。
4. **Browser E2E**：選裝置、增刪拖拉模組、儲存、預覽、上傳圖片、錯誤提示與 XSS 回歸案例。
5. **Hardware-in-loop**：MockDriver 先跑，再用真實 Inky／Waveshare／UPS 分別做手動與長時間測試。
6. **CI**：至少執行語法、單元、API integration、Docker build 和依賴安全掃描；硬體測試可標成需實體 runner 的手動 gate。

## 耦合面驗證

| 耦合面 | 狀態 |
| --- | --- |
| Layout → renderer → PNG | 已以兩個範例裝置 smoke test 驗證。 |
| API auth → browser/device API | 已以 Flask test client 驗證基本拒絕與兩種授權。 |
| Asset upload → download | 已驗證上傳／下載基本路徑；也確認目前會 inline 提供 HTML，屬 High 安全問題。 |
| Asset upload → renderer → Pi sync | 本次未完整驗證；已有既有文件宣稱探索式測試，但沒有可重跑的測試程式。 |
| Scheduler → driver → physical display | 未驗證；無硬體。 |
| UPS daemon → cache → display／poweroff | 未驗證；無 I2C，且不可在此環境執行關機。 |
| Docker/Cloudflare Tunnel → 公網 HTTPS | Compose 靜態設定曾驗證；本次網路變更後仍需驗證 image、Tunnel、DNS 與 HTTPS。 |
| 多 worker → JSON writes | 未驗證，且程式碼檢查指出競態風險。 |

## 最低放行條件

在修正 High 問題、加入至少 API／renderer／UPS 的單元測試、完成兩款面板和 UPS 的上機驗收前，狀態維持 **Not Ready**。若只在隔離開發機展示 MockDriver，則可視為「開發展示可用」。

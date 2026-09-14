# 登入、Pi Token 與通訊安全流程

本文件描述新版流程。LINE Channel 尚未設定前，`EPAGERPI_AUTH_MODE=line` 必須拒絕啟動；不得改以無驗證模式繼續提供管理頁。

## 瀏覽器管理頁

```text
Browser → /auth/line/start → LINE authorization endpoint
        ← callback (code + verified state + PKCE)
Server  → LINE token/profile verification
        → first_login: create the first owner only
        → clear old session, set signed HttpOnly session cookie
Browser → same-origin management API + CSRF header
```

- session cookie 必須是 HttpOnly、SameSite=Lax；HTTPS 部署時必須加 Secure。
- session 只保存本機 user id 與 CSRF 值，不保存 LINE access token、channel secret 或 Pi token。
- 所有 POST／PUT／PATCH／DELETE 管理 API 必須驗證登入 user、CSRF header 與資源 owner。
- `first_login` 僅適用受控開發環境：第一個 LINE 帳號成為 owner 後，後續新帳號一律拒絕。

## Pi 單一接口

```text
Pi → GET /api/v1/device/layout
     Authorization: Bearer <device token>
Server → hash(token + pepper) → find one active Pi → find owner + rules → return layout data
```

- 每一台 Pi 有不同 token；token 僅在建立或重配發時顯示一次。
- 資料庫僅保存 token 雜湊；log、URL、browser storage 與 API 清單不可出現 token。
- Pi token 不可存取管理 API、其他 Pi、其他使用者資料或素材管理端點。
- 所有 API 以 HTTPS 傳輸；開發期 HTTP 僅限受信任的本機網路。

## LINE 路徑

- `EPAGERPI_LINE_CALLBACK_PATH`：LINE Login OAuth callback path。
- `EPAGERPI_LINE_WEBHOOK_PATH`：僅預留給未來 Messaging API；LINE Login 不會呼叫 webhook。端點未實作前必須回應 404，不可接受未驗證請求。

# Cloudflare Tunnel 部署

本目錄的 Compose 設定不再包含 Caddy，也不發布 host port。Cloudflare Tunnel 已在外部處理使用者端 HTTPS 與公開網域；epagerPi 只在既有 Docker network `cloudflared` 中接受 HTTP 連線。

## Docker 內網位址

Tunnel 容器的 origin service 請設定為：

```text
http://epagerpi:8080
```

`epagerpi` 是 Compose service name，也是 Docker DNS 名稱；不是公開網域。Cloudflare 的公開 hostname 請在你自己的 Tunnel ingress 設定中指定。

範例（僅供 Tunnel 設定參考，將公開網域替換為你的實際網域）：

```yaml
ingress:
  - hostname: epagerpi.example.com
    service: http://epagerpi:8080
  - service: http_status:404
```

## 啟動前置條件

1. `cloudflared` Tunnel 容器必須已經加入 Docker network `cloudflared`。
2. 該 network 必須存在；因為 Compose 把它標示為 external，專案不會建立它。需要時由管理端執行一次：`docker network create cloudflared`。
3. 從 `docker/.env.example` 建立 `docker/.env`，並設定強密碼與高熵 API token。

## 啟動

```bash
cd docker
cp .env.example .env
docker compose up -d --build
```

確認服務加入正確網路：

```bash
docker compose ps
docker network inspect cloudflared
```

Cloudflare Access 只能作為外層存取控制；應保留本服務的 Basic Auth 與 Bearer token，避免 Tunnel 或 Access 規則設定錯誤時直接放行 API。

# 部署安全说明

本文说明生产环境推荐部署方式。核心原则：

- 后端只监听 `127.0.0.1:9527`。
- 浏览器只访问前端同源 `/api/*`。
- `X-Proxy-Secret` 只由 Cloudflare Worker 或受控反向代理注入，绝不输出给浏览器。
- 生产环境不推荐 Cloudflare 到源站使用明文 HTTP。

## 推荐方案：Cloudflare Tunnel

```text
浏览器
  -> Cloudflare Pages / Worker
  -> Cloudflare Tunnel
  -> 127.0.0.1:9527 Python 后端
```

后端启动示例：

```bash
export BIND_HOST=127.0.0.1
export PORT=9527
export ADMIN_TOKEN="$(python scripts/generate_secrets.py | awk -F= '/ADMIN_TOKEN/{print $2}')"
export PROXY_SECRET="$(python scripts/generate_secrets.py | awk -F= '/PROXY_SECRET/{print $2}')"
export FRONTEND_ORIGIN="https://your-pages-domain.example"
export COOKIE_SECURE=true
export ALLOW_LOCAL_FILE_API=false
python server.py
```

Cloudflare Pages/Worker 环境变量：

```text
BACKEND_BASE_URL=https://your-tunnel-or-origin.example
PROXY_SECRET=与后端完全一致的长随机密钥
```

## 备选方案：HTTPS 源站

```text
浏览器
  -> Cloudflare Pages / Worker
  -> HTTPS 源站
  -> Nginx
  -> 127.0.0.1:9527 Python 后端
```

Nginx 只负责把 HTTPS 请求转发到本机后端，不应把 Python 端口暴露到公网：

```nginx
server {
    listen 443 ssl http2;
    server_name your-origin.example;

    client_max_body_size 50m;

    location / {
        proxy_pass http://127.0.0.1:9527;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 300;
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
    }
}
```

## 密钥生成

使用仓库脚本生成长随机密钥：

```bash
python scripts/generate_secrets.py
```

把 `ADMIN_TOKEN` 配到后端环境，把同一个 `PROXY_SECRET` 同时配到后端和 Cloudflare Worker 环境。不要把真实密钥提交到 Git，也不要写进前端 HTML、JavaScript 或公开文档。

## 验证

无密钥请求必须返回 403：

```bash
curl -i -X PUT "https://your-public-domain.example/api/upload" \
  -H "Content-Type: application/octet-stream" \
  --data-binary @test.docx
```

带正确 Worker 密钥的代理请求应成功进入上传流程。可在受控环境中直接验证后端：

```bash
curl -i -X PUT "http://127.0.0.1:9527/upload" \
  -H "Content-Type: application/octet-stream" \
  -H "X-Proxy-Secret: $PROXY_SECRET" \
  --data-binary @test.docx
```

错误密钥必须返回 403：

```bash
curl -i "http://127.0.0.1:9527/status/example-task-id" \
  -H "X-Proxy-Secret: wrong-secret"
```

## 防止代理头伪造

Worker 转发时会删除浏览器请求中的 `X-Proxy-Secret`、`X-Forwarded-*`、`CF-Connecting-IP`、`X-Real-IP`、`Cookie`、`Authorization` 等敏感或可伪造头，再由 Worker 重新注入受控头。

后端生产环境必须保持：

```text
ALLOW_LOCAL_FILE_API=false
TRUST_PROXY_HEADERS=true
TRUSTED_PROXY_IPS=127.0.0.1,::1
```

`ALLOW_LOCAL_FILE_API=true` 只用于本地开发，并且只对真实 loopback TCP 连接生效；生产配置下即使请求来自本机 Nginx，没有正确 `X-Proxy-Secret` 也会被拒绝。

## 源站访问限制

- 不开放 Python 后端端口 `9527` 到公网。
- 使用 Cloudflare Tunnel 时，源站无需开放 HTTP 端口给公网。
- 使用 HTTPS 源站时，只开放 `443`，并在防火墙或 Nginx 中限制非 Cloudflare 来源访问。
- 不把公网 HTTP 80 作为正式生产入口传输 `X-Proxy-Secret`。

# 腾讯云海外服务器 + Cloudflare Pages 部署说明

本文档说明推荐生产部署方式。核心原则是：浏览器只访问 Cloudflare Pages 同源 `/api/*`，后端只信任 Cloudflare Pages Worker 注入的 `X-Proxy-Secret`，不再使用会变化的 trycloudflare 临时 Tunnel 地址。

## 部署结构

```text
用户浏览器
  ↓
Cloudflare Pages 前端
  ↓
/api/*
  ↓
pages_dist/_worker.js
  ↓
BACKEND_BASE_URL=http://43.133.167.18
  ↓
Nginx 监听 80
  ↓
127.0.0.1:9527 Python 后端服务
```

服务器公网 IP 示例：`43.133.167.18`。该 IP 只用于部署文档和 Cloudflare Pages 环境变量，不要写死到前端或后端代码。

## Cloudflare Pages 环境变量

在 Cloudflare Pages 项目中配置：

```text
BACKEND_BASE_URL=http://43.133.167.18
PROXY_SECRET=替换为和服务器一致的长随机代理密钥
```

说明：

- 浏览器端仍然只请求同源 `/api/upload`、`/api/status/{task_id}`、`/api/download/{task_id}`。
- `BACKEND_BASE_URL` 只允许在 `pages_dist/_worker.js` 代理层使用。
- 不要在前端页面里写后端 IP。
- `PROXY_SECRET` 必须是足够长的随机字符串，并与服务器环境变量完全一致。
- 前端只需要同源 `/api/*`，不要把后端 IP 写进浏览器代码。

## Python 后端环境变量

服务器上启动后端前设置：

```bash
export BIND_HOST=127.0.0.1
export PORT=9527
export ADMIN_TOKEN="替换为长随机管理密钥"
export PROXY_SECRET="替换为和 Cloudflare Pages 一致的长随机代理密钥"
export TASK_RETENTION_HOURS=24
export MAX_CACHED_TASKS=500
export CLEANUP_INTERVAL_MINUTES=30
export TRUST_PROXY_HEADERS=true
export TRUSTED_PROXY_IPS=127.0.0.1,::1
export FRONTEND_ORIGIN="https://你的Pages域名"
python3 server.py
```

说明：

- `ADMIN_TOKEN` 和 `PROXY_SECRET` 都是必需项，缺失或弱口令时后端会启动失败。
- 不要把真实 `ADMIN_TOKEN`、`PROXY_SECRET` 写入 GitHub。
- Python 后端只监听 `127.0.0.1:9527`，不直接暴露到公网。

## Nginx 示例配置

```nginx
server {
    listen 80;
    server_name _;

    client_max_body_size 50m;

    location / {
        proxy_pass http://127.0.0.1:9527;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header CF-Connecting-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 300;
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
    }
}
```

Nginx 监听公网 80，转发到本机 `127.0.0.1:9527`。

## 腾讯云安全组建议

- `80`: 允许全部 IPv4，用于 Cloudflare Pages Worker 访问 Nginx。
- `9527`: 不要开放。
- `3389`: 不要允许全部 IPv4，建议只允许自己的公网 IP。
- `Ping`: 可开可不开。
- 如需直接从本机管理后台访问，登录会话使用 `HttpOnly`、`SameSite=Strict` 和独立 `csrf_token`。

## 验证命令

后端缺少密钥时应启动失败：

```bash
env -u ADMIN_TOKEN -u PROXY_SECRET python3 server.py
```

直接访问服务器接口且不带 `X-Proxy-Secret` 应返回 403：

```bash
curl -i -X PUT "http://43.133.167.18/upload" \
  -H "Content-Type: application/octet-stream" \
  --data-binary @test.docx
```

通过 Cloudflare Pages 前端上传时，浏览器开发者工具中应只看到同源 `/api/*` 请求，看不到直接请求 `http://43.133.167.18`。

如果 Cloudflare Pages 没有配置 `PROXY_SECRET`，`/api/*` 应返回清晰的 500 错误。

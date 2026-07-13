# 生产部署说明

推荐部署结构：

```text
用户浏览器
  ↓
Cloudflare Pages
  ↓ 同源 /api/*
resources/frontend/pages/_worker.js
  ↓
BACKEND_BASE_URL=http://<SERVER_PUBLIC_IP>
  ↓
Nginx 80
  ↓
127.0.0.1:9527 Python 后端
```

浏览器端只访问 Cloudflare Pages 同源 `/api/*`。后端只信任 Pages Worker 注入的 `X-Proxy-Secret`，不要在前端页面里写后端 IP 或真实密钥。

## 发布文件

生产部署需要的项目文件以 `docs/UPLOAD_MANIFEST.md` 和 `scripts/publish_to_github.ps1` 为准。当前前端源入口和 Cloudflare Pages 部署文件统一位于：

```text
resources/frontend/pages/index.html
resources/frontend/pages/_worker.js
```

`index1.html` 已退役，不再部署。旧 PyQt 桌面端 `main.py`、`untitled.py`、`untitled.ui` 不属于默认 Web 发布范围。

## 安装依赖

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Python 后端环境变量

服务器启动后端前设置：

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
export PRODUCTION_MODE=true
export DATABASE_PATH=var/data/stats.db
./run.sh
```

说明：

- `ADMIN_TOKEN` 和 `PROXY_SECRET` 都是必需项，缺失、弱口令或仍为示例值时后端应启动失败。
- 不要把真实 `ADMIN_TOKEN`、`PROXY_SECRET` 写入 GitHub。
- Python 后端只监听 `127.0.0.1:9527`，不直接暴露到公网。
- `FRONTEND_ORIGIN` 必须是精确 Origin，例如 `https://example.pages.dev`，不要带路径、查询参数或末尾多余斜杠。
- `COOKIE_SECURE` 未设置时会根据 `FRONTEND_ORIGIN` 自动推导。
- 如果根目录仍有旧版 `stats.db` 且未设置 `DATABASE_PATH`，程序会继续使用旧库，避免生成第二份空数据库。迁移前先停服务、备份并执行 SQLite `integrity_check`。

## Cloudflare Pages 环境变量

在 Cloudflare Pages 项目中配置：

```text
BACKEND_BASE_URL=http://<SERVER_PUBLIC_IP>
PROXY_SECRET=替换为和服务器一致的长随机代理密钥
```

说明：

- 浏览器端仍然只请求同源 `/api/upload`、`/api/status/{task_id}`、`/api/download/{task_id}`。
- `BACKEND_BASE_URL` 只允许在 `resources/frontend/pages/_worker.js` 代理层使用。
- `PROXY_SECRET` 必须与服务器环境变量完全一致。

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

## 安全组建议

- `80`：允许 Cloudflare Pages Worker 访问。
- `9527`：不要开放。
- 远程管理端口：不要允许全部 IPv4，建议只允许自己的公网 IP。

## 验证命令

后端缺少密钥时应启动失败：

```bash
env -u ADMIN_TOKEN -u PROXY_SECRET python3 server.py
```

直接访问服务器接口且不带 `X-Proxy-Secret` 应返回 403：

```bash
curl -i -X PUT "http://<SERVER_PUBLIC_IP>/upload" \
  -H "Content-Type: application/octet-stream" \
  --data-binary @test.docx
```

通过 Cloudflare Pages 前端上传时，浏览器开发者工具中应只看到同源 `/api/*` 请求。

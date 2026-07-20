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

重构前的根目录前端、旧构建产物、legacy 页面和旧 PyQt 桌面端文件已移除，不再部署。当前唯一前端发布目录是 `resources/frontend/pages/`。

## 安装依赖

### Windows 服务器

把整个项目目录复制到服务器任意位置。启动脚本始终以自身所在目录作为项目根，
不依赖盘符、当前工作目录或固定部署路径：

```pwsh
Copy-Item .env.example .env
# 编辑 .env，设置生产密钥、FRONTEND_ORIGIN 和 PRODUCTION_MODE=true
pwsh -NoProfile -File .\run.ps1 -InstallDependencies
```

后续启动：

```pwsh
pwsh -NoProfile -File .\run.ps1
```

脚本每次启动前都会通过项目虚拟环境核对`requirements.txt`。已满足的依赖会被
直接复用，缺失或版本不满足的依赖会自动下载安装；因此服务器首次启动和依赖补齐时
需要能够访问Python软件包源。

将后端注册为开机启动、退出远程桌面后仍保持运行的Windows计划任务：

```pwsh
pwsh -NoProfile -File .\run.ps1 -InstallService
```

该任务使用`SYSTEM`账户启动，异常退出后自动重启。服务输出追加到
`var/logs/service-console.log`，排版日志仍写入`var/logs`。

卸载计划任务：

```pwsh
pwsh -NoProfile -File .\run.ps1 -UninstallService
```

仅检查入口和虚拟环境，不启动服务：

```pwsh
pwsh -NoProfile -File .\run.ps1 -CheckOnly
```

`.env`中的相对路径统一相对于项目根目录解析，移动整个项目目录后仍然有效。

### Linux 服务器

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
- 如果根目录仍有旧版 `stats.db` 且未设置 `DATABASE_PATH`，程序会继续使用旧库，避免生成第二份空数据库。迁移前先停服务，运行 `scripts/migrate_legacy_database.ps1` 做 dry run；加 `-Execute` 时脚本会先备份旧库，再复制到目标位置，并在复制前后执行 SQLite `integrity_check`。
- wheel 安装后默认运行数据根不在 `site-packages`。如需固定生产数据位置，显式设置 `DATABASE_PATH`、`LOG_DIR`、`OUTPUT_DIR` 和 `RUNTIME_DIR`。

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

仓库提供不包含服务器IP或磁盘路径的模板：

```text
deploy/nginx-docxtool.conf
```

模板只代理到服务器本机`127.0.0.1:9527`，不要将9527开放到公网。

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

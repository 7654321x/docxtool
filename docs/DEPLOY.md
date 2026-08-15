# 生产部署说明

推荐部署结构：

```text
用户浏览器
  ↓
Cloudflare Pages
  ↓ 同源 /api/*
resources/frontend/pages/_worker.js
  ↓
BACKEND_BASE_URL=http://<SERVER_PUBLIC_IP>:8080
  ↓
Nginx 8080
  ↓
127.0.0.1:9527 Python 后端

管理员浏览器
  ↓
http://<SERVER_PUBLIC_IP>:8080/admin/login
  ↓
Nginx 8080 → 127.0.0.1:9527 Python 后端
```

浏览器端只访问 Cloudflare Pages 同源 `/api/*`。文件与用户 API 只信任 Pages Worker 注入的 `X-Proxy-Secret`，不要在前端页面里写后端 IP 或真实密钥。

## 发布文件

生产部署需要的项目文件以 `docs/RELEASE.md` 和 `scripts/publish_to_github.ps1` 为准。当前前端源入口和 Cloudflare Pages 部署文件统一位于：

```text
resources/frontend/pages/index.html
resources/frontend/pages/_worker.js
```

重构前的根目录前端、旧构建产物、legacy 页面和旧 PyQt5 桌面配置界面已移除，
不再部署。WPS 插件源码和客户端构建规格仍属于独立交付范围；Web 的唯一前端
发布目录是 `resources/frontend/pages/`。

## 安装依赖

### Windows 服务器

把整个项目目录复制到服务器任意位置。启动脚本始终以自身所在目录作为项目根，
不依赖盘符、当前工作目录或固定部署路径：

- Windows 7 SP1 使用 Python 3.8，并安装 Windows Management Framework 5.1；
- Windows 8.1 及以上支持 Python 3.8、3.9、3.10；
- 面向最终用户的安装包应内置 Python 运行时，不要求用户手工安装依赖。

```pwsh
Copy-Item .env.example .env
# 编辑 .env，设置生产密钥、FRONTEND_ORIGIN 和 PRODUCTION_MODE=true
pwsh -NoProfile -File .\run.ps1 -InstallDependencies
```

后续启动：

```pwsh
pwsh -NoProfile -File .\run.ps1
```

脚本每次启动前都会通过项目虚拟环境核对`requirements.lock`。已满足的依赖会被
直接复用，缺失或版本不满足的依赖会自动下载安装；因此服务器首次启动和依赖补齐时
需要能够访问Python软件包源。

将后端注册为开机启动、退出远程桌面后仍保持运行的Windows计划任务：

```pwsh
pwsh -NoProfile -File .\run.ps1 -InstallService
```

新式计划任务使用`SYSTEM`账户启动并配置异常重启。排版日志写入`var/logs`。

Windows 7 缺少新式计划任务 PowerShell 命令时，`run.ps1`自动使用系统
`schtasks.exe`完成安装、启动和卸载，并保证开机重新启动后端；该回退任务不提供
新式任务的分钟级异常重启策略。Windows 7 上可使用：

```pwsh
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -InstallService
```

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
pip install --require-hashes -r requirements.lock
```

开发环境可继续使用 `requirements.txt`。生产环境固定使用 `requirements.lock`；该文件由
Python 3.8 根据`pyproject.toml`通过以下命令生成，禁止手工编造或修改包哈希，且发布前
必须在 Python 3.8 和 3.10 中分别验证安装：

```bash
python -m piptools compile pyproject.toml --generate-hashes --no-emit-index-url --no-emit-trusted-host --output-file requirements.lock
```

本地测试和 CI 使用 `requirements-dev.lock`，其中固定了 `pytest`、`ruff`、`build` 与
`pip-tools` 的版本。需要更新开发依赖时使用：

```bash
python -m piptools compile --extra dev pyproject.toml --generate-hashes --no-emit-index-url --no-emit-trusted-host --output-file requirements-dev.lock
```

## Python 后端环境变量

服务器启动后端前设置：

```bash
export BIND_HOST=127.0.0.1
export PORT=9527
export ADMIN_TOKEN="替换为长随机管理密钥"
export PROXY_SECRET="替换为和 Cloudflare Pages 一致的长随机代理密钥"
export MAX_CACHED_TASKS=500
export CLEANUP_INTERVAL_MINUTES=30
export TRUST_PROXY_HEADERS=true
export TRUSTED_PROXY_IPS=127.0.0.1,::1
export FRONTEND_ORIGIN="https://你的Pages域名"
export PRODUCTION_MODE=true
# 仅在需要独立 HTTP 管理入口时设置；不要把真实服务器 IP 写入仓库。
export ADMIN_CONSOLE_ORIGIN="http://<SERVER_PUBLIC_IP>:8080"
# 仅影响管理员会话；普通用户的 Pages HTTPS Cookie 仍由 COOKIE_SECURE 控制。
export ADMIN_COOKIE_SECURE=false
export DATABASE_PATH=var/data/stats.db
export WPS_DATABASE_PATH=var/data/wps_plugin.db
# 首次部署保持关闭；确认已发布支持重新认证和 outbox 保留的 WPS 客户端后才显式开启。
export WPS_ADMIN_MUTATIONS_ENABLED=false
./run.sh
```

上传原件、排版结果、任务日志和任务记录永久保留。服务不会按时间自动删除这些文件；请自行监控磁盘空间并安排服务器级备份或归档。旧版 `FILE_RETENTION_HOURS`、`TASK_RETENTION_HOURS` 和 `DOCXTOOL_KEEP_FAILED_INPUTS` 配置已不再参与清理策略。

说明：

- `ADMIN_TOKEN` 和 `PROXY_SECRET` 都是必需项，缺失、弱口令或仍为示例值时后端应启动失败。
- 不要把真实 `ADMIN_TOKEN`、`PROXY_SECRET` 写入 GitHub。
- Python 后端只监听 `127.0.0.1:9527`，不直接暴露到公网。
- `FRONTEND_ORIGIN` 必须是精确 Origin，例如 `https://example.pages.dev`，不要带路径、查询参数或末尾多余斜杠。
- `COOKIE_SECURE` 未设置时会根据 `FRONTEND_ORIGIN` 自动推导。
- `ADMIN_CONSOLE_ORIGIN` 为空时，启动日志显示 Pages 管理入口；当前 `80` 被占用时填写与 Pages 回源相同的根 Origin，例如 `http://<SERVER_PUBLIC_IP>:8080`，不要填写 `/admin/login` 路径。
- HTTP 管理入口必须显式设置 `ADMIN_COOKIE_SECURE=false`，否则浏览器会拒绝保存管理员会话 Cookie。该设置只影响管理员会话，不能通过把全局 `COOKIE_SECURE=false` 来解决。
- 如果根目录仍有旧版 `stats.db` 且未设置 `DATABASE_PATH`，程序会继续使用旧库，避免生成第二份空数据库。迁移前先停服务，运行 `scripts/migrate_legacy_database.ps1` 做 dry run；加 `-Execute` 时脚本会先备份旧库，再复制到目标位置，并在复制前后执行 SQLite `integrity_check`。
- `WPS_DATABASE_PATH` 必须指向独立于 `DATABASE_PATH` 的 SQLite 文件；默认值为 `var/data/wps_plugin.db`。
- `WPS_ADMIN_MUTATIONS_ENABLED` 是默认关闭的服务端 WPS 管理写操作门禁。仅在已完成 v2 审计、客户端重新认证和 outbox 保留验证后，才将其显式设为 `true`；非法值会使服务启动失败。
- wheel 安装后默认运行数据根不在 `site-packages`。如需固定生产数据位置，显式设置 `DATABASE_PATH`、`LOG_DIR`、`OUTPUT_DIR` 和 `RUNTIME_DIR`。

## Cloudflare Pages 环境变量

在 Cloudflare Pages 项目中配置：

```text
BACKEND_BASE_URL=http://<SERVER_PUBLIC_IP>:8080
PROXY_SECRET=替换为和服务器一致的长随机代理密钥
```

说明：

- 浏览器端仍然只请求同源 `/api/upload`、`/api/status/{task_id}`、`/api/download/{task_id}`。
- `BACKEND_BASE_URL` 只允许在 `resources/frontend/pages/_worker.js` 代理层使用。
- 当前服务器 `80` 被其他应用占用时，`BACKEND_BASE_URL` 必须与服务器 `.env` 中的 `ADMIN_CONSOLE_ORIGIN` 保持同一 `http://<SERVER_PUBLIC_IP>:8080` 根地址。
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

## 8080 公网后端与管理入口（80 已被其他应用占用时）

如果同一服务器的 `80` 已被其他应用占用，保留该应用的 `80` 配置，不要修改通用
`deploy/nginx-docxtool.conf` 的默认端口。为 DocxTool 另建一个供 Cloudflare Pages 回源和
直接管理后台共同使用的 Nginx server block：

```nginx
server {
    listen 8080;
    server_name _;

    client_max_body_size 50m;

    location / {
        proxy_pass http://127.0.0.1:9527;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300;
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
    }
}
```

服务器 `.env` 同时保持 `BIND_HOST=127.0.0.1`、`PORT=9527`，并设置：

```bash
export ADMIN_CONSOLE_ORIGIN="http://<SERVER_PUBLIC_IP>:8080"
export ADMIN_COOKIE_SECURE=false
```

不要开放 `9527`。因为 Cloudflare Pages Worker 也需要访问 TCP `8080`，不能把整个
`8080` 端口只限制为管理员自己的 IP；应使用强 `ADMIN_TOKEN`、现有登录限流和最小权限。
如需额外的来源限制，只能在确认不再经 Pages 管理后台后，对 Nginx 的管理路径单独设置。
然后重载 Nginx、重启后端，并通过
`http://<SERVER_PUBLIC_IP>:8080/admin/login` 验证登录。该入口是裸 HTTP，管理员密钥和
会话可能被同一网络链路上的第三方读取；如需来源限制，应对管理路径单独配置，具备条件时
应迁移到 HTTPS 域名入口。

## WPS 客户端构建

WPS 客户端与公网服务器分开交付。服务器继续通过根目录 `server.py` 启动；用户端运行无控制台 GUI 单文件 `DocxToolWps.exe`。生产构建必须把可直接访问 `/wps-api/v1/*` 的 HTTPS Origin 写入客户端：

```pwsh
pwsh -NoProfile -File .\apps\wps\scripts\build-exe.ps1 -ServerOrigin https://wps.example.com
```

构建脚本固定 PyInstaller 6.22.0，输出 `dist/wps/DocxToolWps.exe`，随后从仓库外目录执行 `DocxToolWps.exe verify`。源码中的 `apps/wps/client-config.json` 保持本机开发地址；正式地址只在构建时注入。公网服务器只接收账号、设备、心跳、命令授权和结果统计，不接收 DOCX 内容。

## 安全组建议

- `80`：由另一个应用占用时不用于 DocxTool。
- `8080`：DocxTool 公网后端和直接管理入口；必须允许 Cloudflare Pages Worker 回源访问，不能对整个端口仅按管理员 IP 白名单。
- `9527`：不要开放。
- 管理后台：使用强 `ADMIN_TOKEN`；若以后能提供 HTTPS 域名，应优先迁移并恢复 Secure Cookie。

## 验证命令

后端缺少密钥时应启动失败：

```bash
env -u ADMIN_TOKEN -u PROXY_SECRET python3 server.py
```

直接访问服务器接口且不带 `X-Proxy-Secret` 应返回 403：

```bash
curl -i -X PUT "http://<SERVER_PUBLIC_IP>:8080/upload" \
  -H "Content-Type: application/octet-stream" \
  --data-binary @test.docx
```

通过 Cloudflare Pages 前端上传时，浏览器开发者工具中应只看到同源 `/api/*` 请求。

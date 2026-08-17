# DocxTool 后端部署包

此目录是可上传到服务器的后端运行包。它只包含 Python 后端、运行资源、依赖锁、启动脚本和脱敏配置模板。

不包含 WPS 客户端 EXE、`apps/wps`、Node 依赖、数据库、上传文件、日志、`.env` 或 Pages Secret。

## 上传内容

将整个 `server` 目录上传到服务器的固定位置，例如 `D:\DocxTool`。上传后目录应直接包含：

- `server.py`：后端入口；
- `run.ps1`：安装依赖、检查和注册 Windows 开机任务；
- `src\docxtool`：后端源码、内置配置和 WPS API；
- `resources\frontend\pages\index.html`：后端本地页面资源；
- `requirements.lock`：已锁定的生产依赖；
- `.env.example`：配置模板；
- `scripts\generate_secrets.py`：生成两个独立的随机 Secret；
- `var\`：运行时数据目录的空占位。

## Windows 首次部署

1. 在服务器安装 64 位 Python `3.8`、`3.9` 或 `3.10`；不要使用 Python 3.11 及更新版本。
2. 以管理员身份打开 PowerShell 7，进入上传后的目录：

   ```pwsh
   Set-Location D:\DocxTool
   ```

3. 创建生产配置并生成随机 Secret：

   ```pwsh
   Copy-Item .env.example .env
   python .\scripts\generate_secrets.py
   notepad .env
   ```

   把命令输出的两个值分别填入 `.env` 的 `ADMIN_TOKEN` 与 `PROXY_SECRET`，两者必须不同。生产环境至少确认以下配置：

   ```text
   BIND_HOST=127.0.0.1
   PORT=9527
   PRODUCTION_MODE=true
   FRONTEND_ORIGIN=https://docxtool.pages.dev
   ADMIN_CONSOLE_ORIGIN=https://docxtool.pages.dev
   COOKIE_SECURE=true
   ADMIN_COOKIE_SECURE=true
   TRUST_PROXY_HEADERS=true
   TRUSTED_PROXY_IPS=127.0.0.1,::1
   ```

4. 先验证运行包，再注册为开机自动启动的 Windows 计划任务：

   ```pwsh
   pwsh -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -CheckOnly
   pwsh -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -InstallService
   ```

   `-InstallService` 会创建并启动 `DocxtoolBackend` 计划任务。它仅监听本机 `127.0.0.1:9527`，不应对公网开放该端口。

## Ubuntu 22.04 首次部署

Ubuntu 使用 Python 3.10、systemd 和 Caddy。解压后进入 `server` 目录，以 root 权限运行：

```bash
chmod +x linux/install.sh
sudo ./linux/install.sh --origin-host origin.example.com --replace-caddyfile
```

该脚本会把服务安装到 `/opt/docxtool`，但不会写入真实密钥。它首次创建
`/opt/docxtool/.env` 后会停止，由部署者填写以下生产配置：

```text
BIND_HOST=127.0.0.1
PORT=9527
PRODUCTION_MODE=true
FRONTEND_ORIGIN=https://docx.example.com
ADMIN_CONSOLE_ORIGIN=https://docx.example.com
COOKIE_SECURE=true
ADMIN_COOKIE_SECURE=true
TRUST_PROXY_HEADERS=true
TRUSTED_PROXY_IPS=127.0.0.1,::1
ADMIN_TOKEN=<different-long-random-secret>
PROXY_SECRET=<different-long-random-secret>
```

随后将同一个 `PROXY_SECRET` 填入 Pages 的 Production Secret，执行：

```bash
sudo systemctl enable --now docxtool
curl http://127.0.0.1:9527/health
curl https://origin.example.com/health
```

安全组仅开放 TCP 80、443；不得开放 9527。`--replace-caddyfile` 会替换现有 Caddy
配置，因此服务器已有其他 Caddy 站点时先停止，改为合并站点块后再安装。

## Cloudflare Pages

浏览器和 WPS 客户端只访问 Pages 的自定义域名，例如 `https://docx.example.com`。
Pages Worker 回源到 Caddy 的 HTTPS Origin，例如 `https://origin.example.com`；不要公开
或使用服务器 IP、`8080` 或 `9527`。不使用 Quick Tunnel 或 `trycloudflare.com`。

Pages 只配置两个 Secret：

```text
BACKEND_BASE_URL=https://origin.example.com
PROXY_SECRET=<与服务器 .env 中 PROXY_SECRET 完全一致的值>
```

当前 Worker 继续要求无路径、无凭据、非 IP 字面量的 HTTPS hostname。不要启用 Cloudflare Access，也不要创建 Access Service Token。

## 更新与维护

更新时替换代码、`requirements.lock` 和启动脚本，保留服务器已有的 `.env` 与整个 `var` 目录。不要把本机新生成的空数据库、日志或上传文件覆盖到服务器。Ubuntu 使用同一 `linux/install.sh` 更新，它会保留这些数据。

可通过以下命令检查服务：

```pwsh
Invoke-WebRequest http://127.0.0.1:9527/health -UseBasicParsing
Get-ScheduledTask -TaskName DocxtoolBackend
```

如需停止并移除开机任务：

```pwsh
pwsh -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -UninstallService
```

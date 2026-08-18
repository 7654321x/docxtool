# DocxTool Ubuntu 上传包（Nginx + 托管会话）

此目录可整体上传到 Ubuntu 22.04 服务器。它不包含数据库、日志、上传文件、`.env`、证书或任何真实密钥。

运行拓扑：

```text
https://docx.toolpp.cn -> Cloudflare Pages Worker -> https://origin.toolpp.cn
-> Nginx :443 -> 127.0.0.1:9527 -> DocxTool
```

## 1. 初始化依赖、配置和 Nginx

```bash
sudo apt update
sudo apt install -y nginx python3.10 python3.10-venv python3-pip certbot python3-certbot-nginx
cd ~/docxtool
chmod +x setup.sh start.sh
./setup.sh --certbot-email ops@example.com
```

首次运行会复制 `.env.example` 为 `.env` 并停止。替换两个不同的随机密钥后再次运行 setup。
脚本会安装或确认 Nginx、Certbot，校验 `BIND_HOST=127.0.0.1`、`PORT=9527` 和
`MAX_UPLOAD_SIZE_MB`，并用 Certbot 配置 HTTPS。更新前必须先停止已有托管会话。

## 2. 配置 Nginx 与 HTTPS

先确认 `origin.toolpp.cn` 的 A 记录已指向此服务器，并在安全组开放 TCP `80`、`443`。不要开放 `9527`。

`origin.toolpp.cn` 仅配置 A 记录 `43.130.232.115`，不配置 AAAA；安全组只开放 TCP `80`、`443`。
Nginx 反向代理到 `127.0.0.1:9527`，不开放 `9527`。`MAX_UPLOAD_SIZE_MB` 是唯一上传限制配置，
setup 会把它渲染进 Nginx 配置。

## 3. 初始化 DocxTool

```bash
cd ~/docxtool
./.venv/bin/python scripts/generate_secrets.py
nano .env
```

把生成的两个不同值填到 `.env` 的 `ADMIN_TOKEN`、`PROXY_SECRET`。不要把 `.env` 上传到仓库。

Pages Production 配置：

```text
BACKEND_BASE_URL=https://origin.toolpp.cn
PROXY_SECRET=<与 ~/docxtool/.env 完全相同的值>
```

## 4. 在腾讯云托管会话启动

```bash
cd ~/docxtool
./start.sh
```

此命令在当前托管会话前台运行；托管会话保持时服务持续运行。Nginx 仍由 systemd 常驻监听 `80/443`。
同一包已有活动 PID 时，脚本会拒绝再次启动。

验证：

```bash
curl -i http://127.0.0.1:9527/health
curl -i https://origin.toolpp.cn/health
```

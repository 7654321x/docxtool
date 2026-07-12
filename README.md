# 公文排版 Web 服务部署包

这是一个公文排版 Web 服务，支持常见格式自动排版、任务队列、管理后台和 Cloudflare Pages 代理。

运行时会生成 `logs/`、`outputs/`、`runtime/` 和 `stats.db`。

## 文件说明

- `server.py`: Web 服务入口，上传 `.docx` 后生成排版文件。
- `pages_dist/index.html`: 当前实际服务使用的前端页面。
- `index.html`: 旧版浏览器访问页面，保留兼容。
- `index1.html`: 兼容副本，保留给旧流程参考。
- `pages_dist/`: Cloudflare Pages 前端与 Worker 代理文件。
- `importer.py`, `style_config.py`, `engine/`: 文档识别与排版核心代码。
- `config.json`: 默认排版规则。
- `docxtool/requirements.txt`: Python 依赖。
- `.env.example`: 环境变量示例，不包含真实密钥。
- `DEPLOY.md`: 腾讯云海外服务器 + Cloudflare Pages 直连部署说明。
- `UPLOAD_MANIFEST.md`: 让 AI 修改项目前应上传的核心文件清单。
- `hermes_skills/official-document-formatting/`: 给 Hermes 使用的公文格式排版 skill。
- `logs/`, `outputs/`: 运行时目录，服务会写入日志和生成文件。

详细 HTTP 接口、鉴权方式、错误码和调用示例见 `API.md`。

新版前端会把当前排版设置编码到 `X-Format-Config` 请求头，后端只在当前上传任务内转换为样式规则和页面设置，不覆盖全局 `config.json`。
任务文件按 `task_id` 存到独立目录，避免同名覆盖。

## 快速启动

```bash
cd /mnt/d/PycharmProjects/project8
python3 -m venv .venv
source .venv/bin/activate
pip install -r docxtool/requirements.txt
export ADMIN_TOKEN='换成你的长随机管理密钥'
export PROXY_SECRET='换成你的长随机代理密钥'
python3 server.py
```

默认监听 `127.0.0.1:9527`，适合配合 Nginx 反向代理。

如果需要直接监听公网网卡：

```bash
BIND_HOST=0.0.0.0 PORT=9527 python3 server.py
```

后台监控和文件接口都必须显式配置密钥。`ADMIN_TOKEN` 和 `PROXY_SECRET` 未设置或仍是示例值时，后端会启动失败。
可选环境变量包括 `TASK_RETENTION_HOURS`、`MAX_CACHED_TASKS`、`CLEANUP_INTERVAL_MINUTES`、`TRUST_PROXY_HEADERS`、`TRUSTED_PROXY_IPS`、`FRONTEND_ORIGIN`、`COOKIE_SECURE`。

生产推荐部署方式见 `DEPLOY.md`：Cloudflare Pages 前端同源 `/api/*` → `_worker.js` → 腾讯云 Nginx 80 → `127.0.0.1:9527` Python 后端。

## 可选 systemd 示例

把路径 `/opt/docxtool` 替换成你实际上传后的目录：

```ini
[Unit]
Description=Docx Tool
After=network.target

[Service]
WorkingDirectory=/opt/docxtool
ExecStart=/opt/docxtool/.venv/bin/python /opt/docxtool/server.py
Environment=BIND_HOST=127.0.0.1
Environment=PORT=9527
Environment=ADMIN_TOKEN=换成你的长随机管理密钥
Environment=PROXY_SECRET=换成和 Cloudflare Pages 一致的长随机代理密钥
Environment=TASK_RETENTION_HOURS=24
Environment=MAX_CACHED_TASKS=500
Environment=CLEANUP_INTERVAL_MINUTES=30
Environment=TRUST_PROXY_HEADERS=true
Environment=TRUSTED_PROXY_IPS=127.0.0.1,::1
Environment=FRONTEND_ORIGIN=https://你的Pages域名
Restart=always

[Install]
WantedBy=multi-user.target
```

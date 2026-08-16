# 生产部署说明

## 唯一公网入口

DocxTool 的网页、管理后台和 WPS 公网接口统一通过 Cloudflare Pages 暴露：

```text
浏览器 / WPS 客户端
        ↓ HTTPS
https://docxtool.pages.dev
        ↓
Cloudflare Pages Worker
        ↓ HTTPS + Cloudflare Access Service Token + X-Proxy-Secret
https://<PRIVATE_ORIGIN_HOST>
        ↓
Cloudflare Access → Cloudflare Tunnel → http://127.0.0.1:9527
        ↓
DocxTool Python
```

`<PRIVATE_ORIGIN_HOST>` 只是占位符。不要把真实服务器 IP、Origin 域名、Token 或密钥写入仓库、构建参数或浏览器代码。

正式浏览器入口只有：

- Web：`https://docxtool.pages.dev/`
- 管理后台：`https://docxtool.pages.dev/admin/login`
- WPS 公网 API：`https://docxtool.pages.dev/wps-api/v1/*`

不要为 DocxTool 开放公网 `8080` 或 `9527`，也不要保留服务器 IP、HTTP 管理入口或 Pages 失败后直连 Origin 的 fallback。Cloudflare Tunnel 是服务器与 Private Origin 的唯一回源链路；Nginx 不是本项目的标准生产组件。

## 后端运行

Python 服务始终只监听 loopback：

```text
BIND_HOST=127.0.0.1
PORT=9527
```

Windows 服务器首次安装依赖：

```pwsh
Copy-Item .env.example .env
pwsh -NoProfile -File .\run.ps1 -InstallDependencies
```

后续启动或注册开机服务：

```pwsh
pwsh -NoProfile -File .\run.ps1
pwsh -NoProfile -File .\run.ps1 -InstallService
```

Linux 服务器使用项目锁文件安装：

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install --require-hashes -r requirements.lock
./run.sh
```

## 后端生产环境变量

服务器 `.env` 或等价的安全注入配置至少应包含：

```text
BIND_HOST=127.0.0.1
PORT=9527
PRODUCTION_MODE=true
FRONTEND_ORIGIN=https://docxtool.pages.dev
ADMIN_CONSOLE_ORIGIN=https://docxtool.pages.dev
COOKIE_SECURE=true
ADMIN_COOKIE_SECURE=true
ADMIN_TOKEN=<different-long-random-secret>
PROXY_SECRET=<different-long-random-secret>
TRUST_PROXY_HEADERS=true
TRUSTED_PROXY_IPS=127.0.0.1,::1
DATABASE_PATH=var/data/stats.db
WPS_DATABASE_PATH=var/data/wps_plugin.db
WPS_ADMIN_MUTATIONS_ENABLED=false
```

`ADMIN_TOKEN` 与 `PROXY_SECRET` 必须是不同的随机密钥；示例值、弱密钥、缺失值或两者相同都会使服务拒绝启动。

以下安全边界布尔值只接受 `1/true/yes/on` 或 `0/false/no/off`：

- `PRODUCTION_MODE`
- `TRUST_PROXY_HEADERS`
- `COOKIE_SECURE`
- `ADMIN_COOKIE_SECURE`

拼写错误会以配置错误中止启动，不会静默回退。生产模式要求 HTTPS `FRONTEND_ORIGIN`，且 `ADMIN_CONSOLE_ORIGIN` 必须与其一致；管理员和普通用户 Cookie 都必须使用 `Secure`。

上传原件、排版结果、任务记录和日志按当前项目策略永久保留。请在服务器层单独安排磁盘监控与备份。`WPS_DATABASE_PATH` 必须与网页数据库不同；首次部署时保持 `WPS_ADMIN_MUTATIONS_ENABLED=false`，仅在已完成相关客户端验收后再显式开启。

## Cloudflare Tunnel 与 Access

1. 将命名 Cloudflare Tunnel 的服务目标配置为 `http://127.0.0.1:9527`。
2. 为 Tunnel 对应的 HTTPS Private Origin 配置 Cloudflare Access，并要求 Service Auth / Service Token。
3. Private Origin 不接受匿名互联网浏览器访问；浏览器始终只访问 Pages 域名。
4. Tunnel、Access 和服务器防火墙由部署人员配置。本仓库不保存 Tunnel 凭据、Access Application 标识或服务器网络规则。

Tunnel 已经接管回源后，关闭仅为旧 DocxTool Nginx/`8080` 路径设置的公网入站规则和进程映射；不要通过保留旧端口来“方便排障”。

## Cloudflare Pages Secrets

在 Pages 项目中把以下值设置为环境变量/Secret，而不是提交到 `_worker.js`：

```text
BACKEND_BASE_URL=https://<PRIVATE_ORIGIN_HOST>
PROXY_SECRET=<same-as-backend>
CF_ACCESS_CLIENT_ID=<Cloudflare Access service token id>
CF_ACCESS_CLIENT_SECRET=<Cloudflare Access service token secret>
```

`BACKEND_BASE_URL` 必须是无路径、无凭据、非 IP 字面量的 HTTPS hostname Origin。Worker 对所有实际回源请求注入 `CF-Access-Client-Id`、`CF-Access-Client-Secret`、`X-Proxy-Secret` 与 `X-Docxtool-Proxy`；客户端伪造的同名头会被删除。缺少任一值或 Origin 不符合要求时，Worker 返回明确的 5xx 配置错误，不回退到裸 IP。

Worker 只代理 allowlist 中的 Web、管理后台和 WPS 路由。普通页面 API 会过滤浏览器提交的 `Authorization`；WPS 固定路由保留其 Bearer 会话令牌，但不转发浏览器 Cookie。管理登录 Cookie、CSRF、`Set-Cookie` 和相对跳转均通过 Worker 原样保持在 Pages 域名下。

## WPS 客户端

源码中的 `apps/wps/client-config.json` 保留 loopback 开发地址。正式 EXE 在构建时注入唯一 Pages Origin：

```pwsh
pwsh -NoProfile -File .\apps\wps\scripts\build-exe.ps1 -ServerOrigin https://docxtool.pages.dev
```

WPS 使用 `/wps-api/v1/*` 的 HTTPS 调用和既有 Bearer 会话认证；它不上传 DOCX 正文，也不需要独立 WPS 域名或服务器 IP fallback。

## 迁移顺序

1. 先完成后端生产变量、Tunnel 和 Access 配置，但不要立刻关闭旧路径。
2. 在 Pages 中配置四个 Secret，并发布包含 Worker 变更的 Pages 构建。
3. 仅使用 Pages HTTPS 路径验证用户 Web、管理员登录/登出、session、管理写操作和 WPS 登录/心跳/授权/结果回传。
4. 验证成功后关闭旧 DocxTool `8080` 公网规则及其专用 Nginx 配置；不要长期并行两条入口。
5. 若 Pages、Access 或 Tunnel 未验证成功，保留部署状态并修复配置；不把客户端改回直连服务器 IP。

## 验证

代码与配置契约验证：

```pwsh
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m pytest"
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m ruff check src tests scripts"
pwsh -NoProfile -Command "node --test tests/worker-routing.test.mjs"
pwsh -NoProfile -Command "node --test apps/wps/tests/run-node-tests.mjs"
pwsh -NoProfile -Command "node --test tests/frontend-format-config.test.mjs"
```

上线后由有权限的部署人员额外核实：

- `https://docxtool.pages.dev/` 与 `https://docxtool.pages.dev/admin/login` 均通过 HTTPS 正常工作；
- 管理员登录、登出、session、CSRF 与管理写操作始终停留在 Pages 域名；
- WPS 正式客户端只连接 `https://docxtool.pages.dev/wps-api/v1/*`；
- Private Origin 未携带有效 Cloudflare Access Service Token 时不可访问；
- 服务器没有对公网开放 DocxTool `8080` 或 `9527`。

本地自动化通过不代表真实 Cloudflare Tunnel、Access 或 Pages 线上联通已经验证；未执行线上操作时必须明确标记为 `NOT_RUN`。

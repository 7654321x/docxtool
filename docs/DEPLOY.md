# 生产部署说明

## 唯一公网入口

DocxTool 的网页、管理后台和 WPS 公网接口统一通过 Cloudflare Pages 暴露：

```text
浏览器 / WPS 客户端
        ↓ HTTPS
https://docx.example.com
        ↓
Cloudflare Pages Worker
        ↓ HTTPS + X-Proxy-Secret
BACKEND_BASE_URL（Caddy 的 HTTPS Origin hostname）
        ↓
Caddy → http://127.0.0.1:9527
        ↓
DocxTool Python
```

`BACKEND_BASE_URL` 是 Pages Worker 唯一的后端 Origin 配置。它必须是实际可用的 HTTPS hostname；推荐使用用户域名下的专用 Origin 子域名，例如 `origin.example.com`。不要把真实服务器 IP、Origin 域名、Token 或密钥写入仓库、构建参数或浏览器代码。

正式浏览器入口使用 Pages 绑定的自定义域名，例如：

- Web：`https://docx.example.com/`
- 管理后台：`https://docx.example.com/admin/login`
- WPS 公网 API：`https://docx.example.com/wps-api/v1/*`

不要为 DocxTool 开放公网 `8080` 或 `9527`，也不要保留服务器 IP、HTTP 管理入口或 Pages 失败后直连 Origin 的 fallback。Caddy 是标准 HTTPS Origin 组件；不使用 Quick Tunnel、`trycloudflare.com` 或 Cloudflare Access。

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

Ubuntu 22.04 使用部署包的 systemd/Caddy 安装器：

```bash
sudo ./linux/install.sh --origin-host origin.example.com --replace-caddyfile
```

## 后端生产环境变量

服务器 `.env` 或等价的安全注入配置至少应包含：

```text
BIND_HOST=127.0.0.1
PORT=9527
PRODUCTION_MODE=true
FRONTEND_ORIGIN=https://docx.example.com
ADMIN_CONSOLE_ORIGIN=https://docx.example.com
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

## Caddy HTTPS Origin

1. DNS 为 Pages 用户入口设置 `docx.example.com CNAME <project>.pages.dev`，并先在 Pages 的 Custom domains 中关联该子域名。
2. DNS 为服务器 Origin 设置 `origin.example.com A <server-ip>`；Caddy 将该 HTTPS hostname 反向代理到 `http://127.0.0.1:9527` 并自动管理证书。
3. 浏览器和 WPS 始终只访问 Pages 域名；后端仅监听 loopback，并用 Pages 注入的 `X-Proxy-Secret` 验证受信任回源。
4. 安全组只开放 Caddy 所需的 TCP 80、443；不开放 9527。本仓库不保存服务器 IP、网络规则或任何 Pages Secret。

## Cloudflare Pages Secrets

在 Pages 项目中把以下值设置为环境变量/Secret，而不是提交到 `_worker.js`：

```text
BACKEND_BASE_URL=https://origin.example.com
PROXY_SECRET=<same-as-backend>
```

`BACKEND_BASE_URL` 必须是无路径、无凭据、非 IP 字面量的 HTTPS hostname Origin。Worker 对所有实际回源请求只注入 `X-Proxy-Secret` 与 `X-Docxtool-Proxy`；客户端伪造的这两个 Header 会被删除并重写。`CF-Access-Client-Id` 与 `CF-Access-Client-Secret` 如由客户端伪造也会被删除，但 Worker 不生成、不读取、也不依赖它们。缺少两个 Pages Secret 中任一值或 Origin 不符合要求时，Worker 返回明确的 5xx 配置错误，不回退到裸 IP。

Worker 只代理 allowlist 中的 Web、管理后台和 WPS 路由。普通页面 API 会过滤浏览器提交的 `Authorization`；WPS 固定路由保留其 Bearer 会话令牌，但不转发浏览器 Cookie。管理登录 Cookie、CSRF、`Set-Cookie` 和相对跳转均通过 Worker 原样保持在 Pages 域名下。

## WPS 客户端

源码中的 `apps/wps/client-config.json` 保留 loopback 开发地址。正式 EXE 在构建时注入唯一 Pages 自定义域名：

```pwsh
pwsh -NoProfile -File .\apps\wps\scripts\build-exe.ps1 -ServerOrigin https://docx.example.com
```

WPS 使用 `/wps-api/v1/*` 的 HTTPS 调用和既有 Bearer 会话认证；它不上传 DOCX 正文，也不需要独立 WPS 域名或服务器 IP fallback。

## WPS 协议受控压测

`scripts/wps_protocol_load_test.py` 用于在已获授权的维护窗口内，验证 Pages 公网 WPS 协议的并发一致性；它不是网页 DOCX 上传压测，也不启动真实 WPS、Word 或文档自动化。

该工具会并发创建测试账号，并逐个验证：注册写入、账号/设备身份与响应关联 ID、会话读取、心跳、排版授权与结果回传、同一 `request_id` 重试幂等、跨账号请求编号隔离、登出后 Token 失效，以及运行期间格式配置版本是否一致。结果只保存在本地 JSON 报告中，不包含密码或 Bearer Token。

生产环境的注册接口按来源 IP 限制为每小时 5 次，因此一次公网测试最多使用 4 个账号；不要提高这个上限或连续重复运行来规避限流。推荐命令：

```pwsh
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe .\scripts\wps_protocol_load_test.py --base-url https://docxtool.pages.dev --users 4 --concurrency 4 --format-requests-per-user 3 --confirm-production-load --confirm-test-account-creation --report-json .\var\runtime\wps-protocol-load-report.json"
```

测试会留下带本次随机前缀的账号、设备，以及 `WPS_LOAD_TEST_SYNTHETIC` 标记的失败格式请求；脚本会登出，但不会自动删除账号。完成后应在后台按输出的测试账号前缀清理这些测试数据。若结果为 `RATE_LIMITED`，应等待限流窗口结束后再测，不能将其当作服务承载能力不足。

该受控测试只能证明同一公网来源在既有限流范围内的协议正确性，不能证明超过 4 个并发注册、真实多地域用户、Cloudflare 故障恢复或本机 WPS 排版性能。需要验证真实宿主时，应另行安排少量真实 WPS 客户端的人工冒烟与日志核对。

## 迁移顺序

1. 先完成后端生产变量、DNS、Caddy Origin 配置，但不要为 DocxTool 配置 Access。
2. 在 Pages 中只配置 `BACKEND_BASE_URL` 与 `PROXY_SECRET` 两个 Secret，并发布包含 Worker 变更的 Pages 构建。
3. 仅使用 Pages HTTPS 路径验证用户 Web、管理员登录/登出、session、管理写操作和 WPS 登录/心跳/授权/结果回传。
4. 验证成功后关闭旧 DocxTool `8080` 公网规则及其专用 Nginx 配置；不要长期并行两条入口。
5. 若 Pages 或 Caddy Origin 未验证成功，保留部署状态并修复配置；不把客户端改回直连服务器 IP。

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

- `https://docx.example.com/` 与 `https://docx.example.com/admin/login` 均通过 HTTPS 正常工作；
- 管理员登录、登出、session、CSRF 与管理写操作始终停留在 Pages 域名；
- WPS 正式客户端只连接 `https://docx.example.com/wps-api/v1/*`；
- 后端未携带有效 `X-Proxy-Secret` 时拒绝文件 API 等受保护请求；
- 服务器没有对公网开放 DocxTool `8080` 或 `9527`。

本地自动化通过不代表真实 Caddy Origin 或 Pages 线上联通已经验证；未执行线上操作时必须明确标记为 `NOT_RUN`。

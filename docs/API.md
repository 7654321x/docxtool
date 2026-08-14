# 公文排版 Web 服务接口说明

本文档说明 `server.py` 暴露的 HTTP 接口，适用于本地部署、Nginx 反向代理或 Cloudflare Pages Worker 代理接入。

维护约定：后续只要修改 `server.py` 中的接口路径、请求方法、鉴权方式、请求头、请求体、响应字段、状态码或错误码，必须同步更新本文档，并与代码一起提交推送。

默认服务地址：

```text
http://127.0.0.1:9527
```

可通过环境变量修改：

```bash
BIND_HOST=0.0.0.0 PORT=9527 python3 server.py
```

## 1. 鉴权与访问约定

### 1.1 普通文件接口鉴权

上传、查询状态、下载文件接口属于“文件接口”，包括：

- `PUT /upload`
- `PUT /api/upload`
- `GET /status/{task_id}`
- `GET /api/status/{task_id}`
- `GET /download/{task_id}`
- `GET /api/download/{task_id}`

文件接口始终要求请求头携带 `X-Proxy-Secret`，值必须等于服务端环境变量 `PROXY_SECRET`。不要依赖 `Host`、`localhost`、服务器本机地址或来源 IP 作为鉴权依据。

后端启动前必须显式设置：

```bash
export PROXY_SECRET='换成足够长的随机字符串'
```

### 1.2 管理接口鉴权

监控、统计、封禁、日志等管理接口需要管理员权限。优先使用请求头或 Cookie，兼容 URL 参数：

- 请求头：`X-Admin-Token: 你的_ADMIN_TOKEN`
- Cookie：`admin_token=你的_ADMIN_TOKEN`
- URL 参数：`?token=你的_ADMIN_TOKEN`

后端启动前必须显式设置：

```bash
export ADMIN_TOKEN='换成后台管理密码或随机 token'
```

管理接口鉴权失败时返回：

```json
{
  "error": "需要管理员权限",
  "code": "UNAUTHORIZED"
}
```

HTTP 状态码为 `403`。

### 1.3 CORS

服务会返回跨域响应头：

- `Access-Control-Allow-Origin`
- `Access-Control-Allow-Credentials: true`
- `Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS`
- `Access-Control-Allow-Headers: Content-Type, X-Filename, X-Proxy-Secret, X-Docxtool-Proxy, X-Preset-Id, X-Preset-Name, X-Template-Type, X-Processing-Mode, X-Format-Config, X-Format-Config-Encoding, X-CSRF-Token`

`OPTIONS` 预检请求固定返回 `204`。

## 1.4 普通用户账号

普通用户与管理员会话相互独立。用户登录成功后，服务设置 `docxtool_user_session` HttpOnly Cookie；数据库只保存 Session Token 的 SHA-256 摘要。密码使用 Argon2id 保存。

```http
GET  /api/auth/me
POST /api/auth/register
POST /api/auth/login
POST /api/auth/logout
```

注册和登录请求必须使用 `application/json`，并通过配置的 `FRONTEND_ORIGIN` 来源校验。退出以及已登录用户的模板写操作还必须携带 `/api/auth/me` 返回的 `X-CSRF-Token`。CSRF Token 仅保存在页面内存中。

用户登录后，个人模板、任务状态和下载文件按账号隔离；未登录用户继续使用签名匿名 Cookie。公共模板和系统模板仍可被所有用户读取。

生产环境建议配置：

```text
DOCXTOOL_USER_SESSION_DAYS=30
COOKIE_SECURE=1
FRONTEND_ORIGIN=https://docxtool.pages.dev
```

## 2. 健康检查与页面接口

### 2.1 首页

```http
GET /
GET /index.html
```

返回上传页面 HTML。

### 2.2 健康检查

```http
GET /health
```

返回服务进程是否存活。

响应示例：

```json
{
  "ok": true,
  "status": "ok"
}
```

### 2.3 就绪检查

```http
GET /ready
```

检查数据库、输出目录、日志目录是否可用。

成功时 HTTP 状态码为 `200`，失败时为 `503`。

响应示例：

```json
{
  "ok": true,
  "checks": {
    "database": true,
    "output_dir": true,
    "log_dir": true
  }
}
```

### 2.4 版本与运行信息

```http
GET /version
```

响应字段：

- `version`: 对外发布包版本，与 `pyproject.toml` / wheel 元数据一致。
- `package_version`: 与 `version` 相同的显式包版本字段，供监控和宿主集成避免误读。
- `build_version`: 可选构建标识；未配置时为 `null`，不得当作包版本。
- `git_revision`: 可选 Git revision；未配置时为 `null`，不得当作包版本。
- `started_at`: 服务启动时间。
- `bind_host`: 当前绑定地址。
- `file_retention_policy`: 用户文件保留策略，当前固定为 `permanent`。
- `file_ttl_seconds`: 兼容字段；永久保留时为 `null`。
- `max_upload_mb`: 单文件最大上传大小，默认 10 MB。
- `max_workers`: 后台处理线程数。
- `max_queue`: 最大排队容量。
- `proxy_secret_required`: 文件接口是否要求代理密钥。
- `proxy_secret_configured`: 是否已配置 `PROXY_SECRET`。
- `queued`: 当前排队任务数。
- `processing`: 当前处理中任务数。

## 3. 文件排版接口

### 3.1 上传 docx 并创建任务

```http
PUT /upload
PUT /api/upload
```

请求体是 `.docx` 文件的原始二进制内容，不是 `multipart/form-data`。

请求头：

- `Content-Type: application/octet-stream`
- `Content-Length: 文件字节数`
- `X-Filename: URL 编码后的原始文件名`
- `X-Proxy-Secret: 必填，必须等于服务端环境变量 PROXY_SECRET`
- `X-Preset-Id: 可选，当前模板 ID`
- `X-Preset-Name: 可选，URL 编码后的当前模板名称`
- `X-Template-Type: 可选，`builtin` 或 `custom`
- `X-Processing-Mode: 可选，处理模式：`smart`、`structural`、`strict` 或 `normalize`。若同时提供配置中的处理模式，二者必须一致。
- `X-Format-Config-Encoding: 可选；传入前端设置时必须为 `base64url-json`
- `X-Format-Config: 可选，base64url 编码后的 JSON 配置`

`X-Format-Config` 用于把前端“排版设置”随本次上传传入后端，不新增接口、不改变请求体格式。后端只把它作为当前任务的临时配置使用，不会覆盖随包安装的 `src/docxtool/resources/config/default-format.json`。

可选顶层 `letterhead` 使用 `schema_version: 1`。`enabled` 默认为 `false`；启用且机关、文号均为空时自动读取源文档的机关标志、发文字号、签发人和分割线并重建，部分填写时按完整手工配置校验。当前 Web 界面固定提交单机关；Core 为历史配置保留联合发文结构，但自动识别到联合源版头时明确停止。机关标志按版心自适应，`separator_style` 支持 `straight` 和 `star`，红线至首个标题为正文行距 × 2。

WPS 任务窗格的 `/v1/letterhead/inspect`、`/v1/letterhead/prepare` 是本机回环 Control 路由，不属于公网 HTTP API。它们只用于“添加版头”的检查和事务准备，不改变公网请求、Token 或数据库协议。

配置 JSON 结构示例：

```json
{
  "styles": [
    {
      "name": "正文",
      "font": "仿宋_GB2312",
      "size": "三号",
      "bold": false,
      "pattern": "",
      "lang": "",
      "indent": 2,
      "align": "左对齐"
    }
  ],
  "page": {
    "width_cm": 21,
    "height_cm": 29.7,
    "margin_top_cm": 3.7,
    "margin_bottom_cm": 3.5,
    "margin_left_cm": 2.8,
    "margin_right_cm": 2.6,
    "lines_per_page": 22,
    "chars_per_line": 28,
    "line_spacing_pt": 28,
    "space_before_line": 0,
    "space_after_line": 0,
    "grid_alignment": true
  },
  "features": {
    "numbered_bold_enabled": true,
    "punctuation_enabled": true,
    "page_number_enabled": true
  }
}
```

限制：

- 文件必须是 `.docx` 格式，内容需要以 ZIP 文件头 `PK` 开始。
- 单文件大小默认不超过 10 MB。
- 同一 IP 默认 2 秒内只能发起一次上传。
- 队列满时会拒绝新任务。
- 被封禁 IP 不能上传。
- 如果启用了上传限额，同一 IP 在指定时间窗口内超过次数会被拒绝。

本机调用示例：

```bash
curl -X PUT "http://127.0.0.1:9527/upload" \
  -H "Content-Type: application/octet-stream" \
  -H "X-Filename: %E6%B5%8B%E8%AF%95.docx" \
  -H "X-Proxy-Secret: $PROXY_SECRET" \
  --data-binary "@/path/to/测试.docx"
```

远程/代理调用示例：

```bash
curl -X PUT "https://你的域名/api/upload" \
  -H "Content-Type: application/octet-stream" \
  -H "X-Filename: %E6%B5%8B%E8%AF%95.docx" \
  --data-binary "@/path/to/测试.docx"
```

成功响应示例：

```json
{
  "task_id": "b3e4d8a8-0f3a-4f1b-b8c3-5f8b35d02c11",
  "status": "queued",
  "queue_position": 1,
  "queue_ahead": 0,
  "message": "排队中，前方还有 0 个任务"
}
```

常见错误：

| HTTP 状态码 | code | 含义 |
| --- | --- | --- |
| 400 | `INVALID_DOCX` | 文件不是有效 docx |
| 400 | `INCOMPLETE_UPLOAD` | 上传内容读取不完整 |
| 400 | `FORMAT_CONFIG_INVALID` | `X-Format-Config` 不是合法的 base64url JSON 配置 |
| 403 | `PROXY_REQUIRED` | 缺少或错误的 `X-Proxy-Secret` |
| 403 | `IP_BANNED` | 当前 IP 已被封禁 |
| 408 | `UPLOAD_TIMEOUT` | 文件读取超时 |
| 413 | `FILE_TOO_LARGE` | 文件为空或超过大小限制 |
| 413 | `FORMAT_CONFIG_TOO_LARGE` | `X-Format-Config` 请求头或解码后的配置过大 |
| 429 | `RATE_LIMITED` | 请求过于频繁 |
| 429 | `UPLOAD_LIMIT_EXCEEDED` | 当前 IP 在限额窗口内已达上限 |
| 503 | `QUEUE_FULL` | 任务队列已满 |

### 3.2 查询任务状态

```http
GET /status/{task_id}
GET /api/status/{task_id}
```

`task_id` 必须是上传接口返回的 UUID。

请求示例：

```bash
curl "http://127.0.0.1:9527/status/b3e4d8a8-0f3a-4f1b-b8c3-5f8b35d02c11" \
  -H "X-Proxy-Secret: $PROXY_SECRET"
```

排队中响应示例：

```json
{
  "status": "queued",
  "time": 1781880000.123,
  "queued_at": 1781880000.123,
  "queue_position": 1,
  "queue_ahead": 0,
  "message": "排队中，前方还有 0 个任务"
}
```

处理中响应示例：

```json
{
  "status": "processing",
  "time": 1781880000.123,
  "queued_at": 1781880000.123,
  "started_at": 1781880001.456,
  "queue_position": 0,
  "queue_ahead": 0,
  "message": "正在排版"
}
```

完成响应示例：

```json
{
  "status": "done",
  "time": 1781880005.789,
  "queued_at": 1781880000.123,
  "started_at": 1781880001.456,
  "duration": 4.33,
  "paragraphs": 86,
  "log_filename": "20260619_224512_测试_b3e4d8a8.log",
  "log_url": "/log/b3e4d8a8-0f3a-4f1b-b8c3-5f8b35d02c11",
  "queue_position": 0,
  "queue_ahead": 0,
  "message": "排版完成"
}
```

失败响应示例：

```json
{
  "status": "error",
  "error": "错误摘要",
  "error_code": "OUTPUT_DOCX_INVALID",
  "log_filename": "20260619_224512_测试_b3e4d8a8.log",
  "log_url": "/log/b3e4d8a8-0f3a-4f1b-b8c3-5f8b35d02c11",
  "queue_position": 0,
  "queue_ahead": 0,
  "message": "排版失败"
}
```

当后端已生成输出文件但生成结果未通过 OOXML 完整性检查时，任务状态为 `error`，`error_code` 固定为 `OUTPUT_DOCX_INVALID`，输出文件会被清理，下载接口继续返回 `FILE_NOT_READY`。

常见错误：

| HTTP 状态码 | code | 含义 |
| --- | --- | --- |
| 400 | `INVALID_TASK_ID` | 任务 ID 格式错误 |
| 403 | `PROXY_REQUIRED` | 缺少或错误的 `X-Proxy-Secret` |
| 404 | `TASK_NOT_FOUND` | 任务不存在或已过期 |

### 3.3 下载排版结果

```http
GET /download/{task_id}
GET /api/download/{task_id}
```

任务状态为 `done` 后才能下载。

响应头：

- `Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document`
- `Content-Disposition: attachment; filename=formatted.docx`

请求示例：

```bash
curl "http://127.0.0.1:9527/download/b3e4d8a8-0f3a-4f1b-b8c3-5f8b35d02c11" \
  -H "X-Proxy-Secret: $PROXY_SECRET" \
  -o "排版结果.docx"
```

常见错误：

| HTTP 状态码 | code | 含义 |
| --- | --- | --- |
| 400 | `INVALID_TASK_ID` | 任务 ID 格式错误 |
| 400 | `FILE_NOT_READY` | 文件尚未生成 |
| 403 | `PROXY_REQUIRED` | 缺少或错误的 `X-Proxy-Secret` |
| 410 | `FILE_EXPIRED` | 文件路径不可用或被服务器管理员手动移除 |

上传原件、输出文件、任务日志和任务记录永久保留；后台不会按时间自动清理。下载不会删除文件。

## 4. 管理与监控接口

以下接口都需要管理员鉴权。

### 4.1 监控面板

```http
GET /monitor?token={ADMIN_TOKEN}
```

返回 HTML 监控页面，包含总任务数、成功率、独立 IP、最近任务、活跃 IP、封禁列表和上传限额配置。

可选查询参数：

- `recent_page`: 最近任务页码，默认 1。
- `recent_size`: 最近任务每页数量，默认 50，最大 100。
- `ip_page`: 活跃 IP 页码，默认 1。
- `ip_size`: 活跃 IP 每页数量，默认 50，最大 100。

示例：

```text
http://127.0.0.1:9527/monitor?token=你的_ADMIN_TOKEN
```

### 4.2 统计 JSON

```http
GET /stats?token={ADMIN_TOKEN}
```

也支持请求头：

```bash
curl "http://127.0.0.1:9527/stats" \
  -H "X-Admin-Token: $ADMIN_TOKEN"
```

响应字段：

- `total`: 总任务数。
- `done`: 成功任务数。
- `error`: 失败任务数。
- `unique_ips`: 独立 IP 数。
- `total_mb`: 上传总数据量，单位 MB。
- `avg_s`: 成功任务平均耗时，单位秒。
- `avg_paragraphs`: 成功任务平均段落数。
- `rate`: 成功率百分比。
- `query`: 当前分页参数。
- `recent`: 最近任务列表。
- `recent_total`: 最近任务总数。
- `recent_page`, `recent_size`, `recent_pages`: 最近任务分页信息。
- `trend`: 按日期聚合的任务趋势。
- `top_ips`: 活跃 IP 列表。
- `ip_total`, `ip_page`, `ip_size`, `ip_pages`: IP 分页信息。
- `banned_ips`: 已封禁 IP 列表。

`recent` 中的任务对象主要字段：

- `id`: 任务 ID。
- `ip`: 客户端 IP。
- `ua`: User-Agent。
- `filename`: 上传文件名。
- `file_size`: 文件大小，单位字节。
- `doc_type`: 文档类型。
- `paragraphs`: 段落数。
- `headings`: 标题数。
- `body`: 正文段落数。
- `duration_ms`: 排版耗时，单位毫秒。
- `status`: `queued`、`processing`、`done` 或 `error`。
- `error`: 错误摘要。
- `log_filename`: 日志文件名。
- `created_at`: 创建时间。
- `done_at`: 完成时间。

### 4.3 IP 明细

```http
GET /ip?addr={ip}&token={ADMIN_TOKEN}
GET /ip?ip={ip}&token={ADMIN_TOKEN}
```

返回指定 IP 的上传明细 HTML。

### 4.4 封禁 IP

```http
GET /ban?ip={ip}&reason={reason}&token={ADMIN_TOKEN}
```

封禁指定 IP。`reason` 可选，最长保留 120 个字符。成功后 `303` 重定向回监控面板。

示例：

```bash
curl -i "http://127.0.0.1:9527/ban?ip=203.0.113.10&reason=too_many_uploads&token=$ADMIN_TOKEN"
```

### 4.5 解封 IP

```http
GET /unban?ip={ip}&token={ADMIN_TOKEN}
```

解除指定 IP 的封禁。成功后 `303` 重定向回监控面板。

### 4.6 设置上传限额

```http
GET /limit?enabled=1&window_seconds=3600&count=10&token={ADMIN_TOKEN}
```

参数：

- `enabled`: `1` 表示启用，不传或非 `1` 表示关闭。
- `window_seconds`: 时间窗口，单位秒，最小值 1。
- `count`: 时间窗口内允许上传次数，最小值 1。

示例含义：同一 IP 在 3600 秒内最多上传 10 个文件。

成功后 `303` 重定向回监控面板。

### 4.7 历史清理入口

```http
POST /cleanup
```

为兼容已有管理员书签保留该入口，但永久保留策略下不会删除任何用户文件。成功后 `303` 重定向回监控面板。

### 4.8 查看任务日志

```http
GET /log/{task_id}?token={ADMIN_TOKEN}
```

返回指定任务的纯文本日志。

常见错误：

| HTTP 状态码 | code | 含义 |
| --- | --- | --- |
| 400 | `INVALID_TASK_ID` | 任务 ID 格式错误 |
| 403 | `UNAUTHORIZED` | 缺少管理员权限 |
| 404 | `LOG_NOT_FOUND` | 日志不存在或已过期 |

## 5. 前端接入流程

浏览器端推荐流程：

1. 用户选择 `.docx` 文件。
2. 前端检查扩展名和大小，小于 10 MB 才上传。
3. 从当前模板和排版设置生成后端兼容配置，结构为 `styles`、`page`、`features`。
4. 对配置执行 `base64url(JSON.stringify(config))`，写入 `X-Format-Config`，同时写入 `X-Format-Config-Encoding: base64url-json`。
5. `PUT /api/upload` 上传原始二进制，请求体仍然只是 `.docx` 文件。
6. 后端在当前任务内把配置转换为 `StyleRule`、`PageSettings` 和功能开关，传入 engine 排版。
7. 读取响应中的 `task_id`。
8. 每秒轮询 `GET /api/status/{task_id}`。
9. 状态为 `queued` 时显示排队位置。
10. 状态为 `processing` 时显示处理中。
11. 状态为 `done` 时请求 `GET /api/download/{task_id}` 并触发浏览器下载。
12. 状态为 `error` 时显示错误摘要。

前端默认使用同源 `/api/*` 路径。Cloudflare Pages 的 `resources/frontend/pages/_worker.js` 负责把公开 API 请求转发到后端不带 `/api` 的直连路径：

- `/api/upload` → `/upload`
- `/api/status/{task_id}` → `/status/{task_id}`
- `/api/download/{task_id}` → `/download/{task_id}`
- `/api/presets`、`/api/presets/{preset_id}` → `/presets`、`/presets/{preset_id}`
- `/api/admin/*` → `/admin/*`
- `/api/health`、`/api/ready`、`/api/version` → `/health`、`/ready`、`/version`

Worker 还会代理管理页面直接使用的后端路径：

- `/admin/login`、`/admin/logout`、`/admin/session`
- `/monitor`、`/stats`、`/ip`
- `/ban`、`/unban`、`/limit`、`/cleanup`
- `/log/{task_id}`
- `/presets`

相似但不匹配的路径不会代理，例如 `/apiary`、`/monitor-evil`、`/unknown` 会按静态资源处理。

### 匿名用户模板

- 首次访问 `GET /api/presets` 时，后端通过 `Set-Cookie` 下发签名的
  `docxtool_anon_user` 匿名用户 Cookie。
- Cookie 使用 `HttpOnly`、`SameSite=Lax` 和长期 `Max-Age`；HTTPS 部署时同时使用
  `Secure`。客户端不需要、也不能读取匿名用户 ID。
- `GET /api/presets` 返回系统模板、公共模板和当前匿名用户的个人模板。
- 普通用户通过 `POST /api/presets` 创建个人模板，只能修改或删除自己的模板。
- 匿名模板的 `POST`、`PUT`、`DELETE` 必须来自 `FRONTEND_ORIGIN`；本地开发允许同源
  `localhost`、`127.0.0.1` 或 `::1`。
- 管理员会话继续创建和维护公共模板。旧数据库模板迁移后保持公共可见。
- Cloudflare Worker 只转发 `docxtool_admin_session` 和 `docxtool_anon_user` 两种 Cookie，
  其他 Cookie 和敏感认证请求头会被过滤。

## 6. 统一错误格式

接口错误统一返回 JSON：

```json
{
  "error": "给用户看的中文错误信息",
  "code": "MACHINE_READABLE_CODE"
}
```

客户端建议优先展示 `error`，同时在日志中记录 `code` 和 HTTP 状态码，便于排查。

## 7. 部署注意事项

1. 生产环境必须设置 `ADMIN_TOKEN` 和 `PROXY_SECRET`，代码不提供默认密钥。
2. 只开放 Nginx 80，不要直接暴露 Python 服务端口 9527。
3. Nginx 需要允许 `PUT` 方法并转发请求头。
4. Cloudflare Pages 前端访问同源 `/api/*`，Worker 通过 `BACKEND_BASE_URL` 转发到 Nginx，再由 Nginx 转发到 `127.0.0.1:9527`。
5. 推荐部署细节见 `docs/DEPLOY.md`。
6. `var/logs/` 和 `var/outputs/` 是运行时目录，仓库中只保留 `.gitkeep`，实际日志和生成文件不应提交。
7. `var/data/stats.db` 是源码树运行时 SQLite 数据库位置，不应提交到仓库。若根目录已有旧版 `stats.db` 且未设置 `DATABASE_PATH`，后端会继续使用旧库，迁移需人工停服务后执行。仅解析默认路径不会创建数据库目录，首次实际连接时才会创建父目录；wheel 安装后默认运行数据根不在 `site-packages`。

## 8. WPS 插件公网接口

WPS 插件接口统一使用 `/wps-api/v1` 前缀，JSON envelope 的协议版本为 `wps-api-v1`。注册和登录之外的接口使用 `Authorization: Bearer <会话令牌>`；排版授权和结果回传还要求请求头 `X-DocxTool-Request-Id` 与请求体“请求编号”一致。新注册和新登录签发的会话从签发时起固定有效 7 天，心跳不会延长有效期；升级前已存在的会话不迁移，继续按数据库中的原到期时间生效。

| 方法 | 路径 | 中文用途 |
| --- | --- | --- |
| `POST` | `/wps-api/v1/auth/register` | 注册账号、登记设备并签发会话 |
| `POST` | `/wps-api/v1/auth/login` | 校验账号密码、复用或登记设备并签发会话 |
| `GET` | `/wps-api/v1/auth/me` | 查询当前账号、设备、功能列表和会话到期时间 |
| `POST` | `/wps-api/v1/auth/logout` | 删除当前服务端会话 |
| `POST` | `/wps-api/v1/heartbeat` | 更新设备和会话最后在线时间，不续期 |
| `POST` | `/wps-api/v1/format/authorize` | 为一键排版登记请求并下发服务器格式配置 |
| `POST` | `/wps-api/v1/format/result` | 使用同一请求编号回传成功或失败结果 |

注册和登录请求中的字段为：账号、密码，以及包含设备密钥、设备名称、平台和客户端版本的设备对象。账号和密码均至少 5 位，只允许字母与数字；账号按不区分大小写方式判重。用户摘要只返回用户编号、登录账号和账号状态，不设置独立显示名称。服务端只保存 Argon2id 密码哈希、设备指纹哈希和会话哈希。

WPS 登录使用独立限流：同一出口 IP 每 10 分钟最多 300 次，同一标准化账号每 10 分钟最多 10 次；注册仍为同一 IP 每小时最多 5 次。该调整不改变网页版账号的登录限流。单进程 WPS 服务最多同时执行两个 Argon2 操作，等待中的登录自然排队，不新增超时或降级响应。

排版授权请求字段为：请求编号、命令和客户端版本。第一阶段唯一受控命令是 `apply`。允许时返回：是否允许、是否复用已有请求、同一请求编号、请求状态、配置版本和完整格式配置。结果回传字段为：请求编号、结果状态、耗时、错误代码和客户端版本。成功状态不能携带错误代码，失败状态必须携带明确错误代码。

公网响应中的完整格式配置只交给本机 Control 授权上下文验证和保存。WPS Host 通过内部 Bridge 只接收请求编号和配置版本，调用本机排版准备接口时不提交格式配置；Control 按请求编号将已授权配置注入 Engine。一个授权只能绑定一个 `apply` 事务，事务后续接口必须使用同一请求编号。TaskPane 的账号、网络、功能可用性和待补报数量由 `/v1/bridge/state/wait` 的 `account` 摘要同步，不单独轮询账号接口。排版结果暂时无法回传时写入本地 SQLite 持久 outbox，心跳恢复或下一次 Launcher 启动后继续补报。

`DATABASE_PATH` 与 `WPS_DATABASE_PATH` 必须解析到两个不同的 SQLite 文件；配置为同一文件时，服务在初始化任一数据库前以 `WPS_DATABASE_PATH_CONFLICT` 停止启动。

公网接口不接收文件名、文件路径、文档正文、DOCX、识别结果或排版后的文档。更完整的字段和错误码契约见根目录 `WPS_SERVER_TECHNICAL_DESIGN.md`。

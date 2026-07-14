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

- `version`: 应用版本号。
- `started_at`: 服务启动时间。
- `bind_host`: 当前绑定地址。
- `file_ttl_seconds`: 输出文件保留时间，默认 86400 秒。
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
- `X-Processing-Mode: 可选，处理模式，例如 `smart`
- `X-Format-Config-Encoding: 可选；传入前端设置时必须为 `base64url-json`
- `X-Format-Config: 可选，base64url 编码后的 JSON 配置`

`X-Format-Config` 用于把前端“排版设置”随本次上传传入后端，不新增接口、不改变请求体格式。后端只把它作为当前任务的临时配置使用，不会覆盖随包安装的 `src/docxtool/resources/config/default-format.json`。

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
| 410 | `FILE_EXPIRED` | 输出文件已过期或被清理 |

输出文件默认保留 86400 秒，后台清理线程每 60 秒检查一次过期文件。

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

### 4.7 清理过期输出文件

```http
GET /cleanup?token={ADMIN_TOKEN}
```

手动清理超过保留时间的输出文件。成功后 `303` 重定向回监控面板。

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

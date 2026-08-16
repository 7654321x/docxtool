# DocxTool 5.4 WPS 公网服务技术设计

## 文档定位

本文说明 [`WPS_SERVER_PRD.md`](WPS_SERVER_PRD.md) 的当前实现边界。HTTP 路径、请求体、响应体、状态码和公开错误码以 [`docs/API.md`](docs/API.md) 为唯一契约；本文不复制外部接口字段。

当前实现继续使用根目录 `server.py` 作为唯一服务器入口。WPS 公网账号与网页业务共用 Python 进程和 HTTPS 入口，但使用独立数据库、限流作用域和业务模块。

## 总体架构

```text
WPS 登录窗口
  → /wps-api/v1 注册或登录
  → 本地 DPAPI + account.db
  → AccountRuntime 心跳

TaskPane 一键排版
  → 本机 Control 创建 request_id
  → 公网授权并取得 format_config/config_version
  → HostBridge 发送 request_id
  → 本机 Recognition / Normalization / Engine
  → SQLite 持久 outbox
  → 心跳或下次启动补报结果
```

公网服务器不接收 DOCX、正文、文档路径、图片、表格、文档哈希或识别结果。唯一的最小例外是：用户明确需要在管理员后台查看排版任务时，结果补报可以携带 WPS Host 已读取的基础文件名；它不包含路径，也不进入日志。

## 服务端模块

`src/docxtool/wps_server/` 是 WPS 公网服务的唯一业务归属：

- `config.py`：WPS 数据库路径、会话期限、心跳窗口和限流常量；
- `validation.py`：账号、密码、设备和请求字段校验；
- `database.py`：SQLite 建表、索引、事务和版本检查；
- `auth.py`：Argon2id 哈希、校验、虚假账号耗时平衡和会话 Token；
- `format_config.py`：读取并验证当前正式格式配置；
- `service.py`：注册、登录、心跳、授权、结果回传和管理操作事务；
- `route_handlers.py`：HTTP handler 与 service 的薄适配；
- `admin.py`：WPS 用户、设备、请求和统计查询。

`src/docxtool/web/app.py` 只负责组合数据库连接器、锁、配置和路由，不复制 WPS 业务逻辑。管理员工作台按 Web 数据库和 WPS 数据库分区查询。

## 数据库

公网 WPS 数据库与网页 `stats.db` 分离，当前核心表为：

| 表 | 职责 |
| --- | --- |
| `wps_users` | 标准化账号、Argon2id 摘要、状态和时间 |
| `wps_devices` | 用户设备摘要、状态、客户端版本和最后在线时间 |
| `wps_sessions` | 会话摘要、用户、设备、签发时间和到期时间 |
| `wps_format_requests` | 唯一请求编号、功能、授权状态、终态、配置版本和受限基础文件名 |
| `wps_admin_audit_logs` | 管理员授权上下文、目标账号、写操作结果和关联编号；不保存密码或 Token |
| `wps_notifications` | 账号级纯文本通知、级别、创建时间和展示确认时间 |

数据库不保存原始密码、原始设备序列号、原始会话 Token 或文档数据。用户、设备和会话状态必须在授权和心跳事务内联合复核。

当前 Schema v4 在 v1 的核心表基础上，先于 v2 追加管理员审计表及索引，再于 v3 追加账号级通知表及待确认查询索引，最后由 v4 为 `wps_format_requests` 追加非空 `document_name` 字段，默认空字符串。管理写操作与其成功审计在同一 SQLite 事务中提交；审计写入失败时业务写入必须回滚。账号硬删除不级联删除审计事实，审计中的目标账号编号不设指向 `wps_users` 的外键；通知则随该账号业务数据在同一事务中删除。

新注册和新登录会话从签发时起精确有效 7 天；心跳不续期。已有会话只按数据库中的 `expires_at` 判断，不执行批量迁移。

## 密码与登录性能

- Argon2id 固定使用 `memory_cost=65536 KiB`、`time_cost=3`、`parallelism=4`。
- 单进程使用 `BoundedSemaphore(2)` 统一限制注册哈希、真实或虚假账号校验及旧哈希升级。
- 旧哈希升级在 SQLite 写锁和 `BEGIN IMMEDIATE` 前计算，事务内只复核状态并保存预计算哈希。
- WPS 登录限流为同 IP `300/600s`、同账号 `10/600s`；注册为同 IP每小时 5 次。
- 网页账号和匿名排版不使用 WPS Argon2 信号量，也不改变网页登录限流。

## 本地账号与启动链

`apps/wps/account_store.py` 使用本地 SQLite；密码、会话 Token 和设备密钥在写入前使用当前 Windows 用户 DPAPI 加密。本地数据库同时保存登录偏好、Bootstrap Snapshot 和持久格式结果 outbox。旧版本地行缺少 Snapshot 字段时按本地迁移补为空值；只有新的登录/注册或 `/auth/me` 成功解析后才写入可信公共 Snapshot，不用猜测性默认值伪造服务端状态。待展示通知只保存在 `AccountRuntime` 内存摘要中，不写入账号库或 outbox。

启动顺序固定为：

```text
移除当前项目旧加载项注册
→ 显示登录/注册窗口
→ 可选自动登录在窗口显示后提交一次
→ 登录或注册成功
→ 创建 AccountRuntime
→ 启动 Control Server 和固定 127.0.0.1:3889 静态服务
→ 发布运行配置和 docxtool-wps-app
→ 立即心跳，之后按服务端 Bootstrap 指定的节拍执行
```

没有账号、账号损坏、窗口取消或公网认证失败时，不创建 AccountRuntime、Control Server 或静态服务，也不发布加载项。自动登录失败后保留窗口，用户可以修改后手动登录。

本地端口被占用时，只有运行配置和 Control 健康接口共同证明占用者是 DocxTool 旧服务，才允许停止旧服务并重试；其他占用立即返回 `WPS_WEB_SERVER_PORT_IN_USE`。

## 会话与心跳

AccountRuntime 启动后立即心跳，随后使用登录/注册/`/auth/me` Bootstrap 中的 `heartbeat_interval_seconds` 节拍，不进行高频失败重试。只有 `PublicApiError.network=True` 才标记“服务器离线”；会话过期、账号禁用和设备禁用走各自状态。

网络恢复后先更新账号摘要，再补报 SQLite outbox。服务端返回 `SESSION_INVALID`、`SESSION_EXPIRED`、`INVALID_CREDENTIALS`、`ACCOUNT_DISABLED` 或 `DEVICE_DISABLED` 时，运行时只清除本地会话凭据并进入 `reauth_required`，经 Qt 主线程打开登录窗口重新认证；不得在运行期读取或自动提交旧密码。上述情形、网络失败和正常停止都保留 outbox；只有用户明确执行本机移除账号/清理数据时才允许删除剩余回执。

注册、登录和运行期 heartbeat 复用服务端唯一的待确认通知查询。Runtime 按通知编号合并并去重，沿用现有 Control state/wait 将摘要送到 TaskPane；TaskPane 以纯文本展示后，复用 Control 与公网 `notifications/read` 确认链路。该链路不新增轮询线程、第二套本机协议或本地通知持久化；一次设备确认即按账号级语义确认，未知或已确认编号的重复提交没有副作用。

## 排版授权与结果补报

每次一键排版先由 Control 创建唯一 `request_id` 并调用公网授权。授权成功后，完整 `format_config` 只保存在本机 Control 授权上下文；HostBridge 只接收 `request_id` 和 `config_version`。

授权上下文只能消费一次并绑定一个 `apply` 事务。prepare、commit、finalize 和 rollback 必须使用同一请求编号。Host 终态先验证上下文和 generation，再把本地真实 `PASS/FAIL` 写入 SQLite 持久 outbox。

公网结果暂时不可达不改变本地排版终态；TaskPane 通过账号摘要中的 `pending_result_count` 显示未同步数量。心跳恢复或下一次 Launcher 启动后继续补报。

预览、清除预览、本机检测、TaskPane 设置、添加版头和 Reader 不调用公网排版授权。

## 排版任务文件名元数据

### 目标与非目标

管理员需要在“WPS 排版任务”表中识别对应的本地文档，因此每次实际执行的一键排版可保存一个基础文件名。该字段仅用于管理员已授权的任务查询，不用于搜索、统计、路由、授权、格式配置或文档处理决策。

本轮不上传或保存完整路径、目录、正文、DOCX、摘要、哈希、识别结果或任何其他文档内容；不改变 TaskPane 与 HostBridge 的职责，也不为此新增第二条本机或公网通信链路。

### 数据流与所有权

```text
WPS Host Runtime（唯一可读取 WPS Document.Name 的边界）
        ↓ 终态 active_request.document_name
Control Server（只在结果补报时转交，不写本地诊断日志）
        ↓
AccountRuntime + 本地 format_result_outbox（离线可重试）
        ↓ POST /wps-api/v1/format/result
WPS 服务端校验并写入 wps_format_requests.document_name
        ↓
管理员 WPS 排版任务表
```

文件名不放在授权请求中：TaskPane 不直接访问 WPS 对象，且它持有的状态可能已过期。只有 Host 在同一请求实际开始执行时读取的 `Document.Name` 才是本次排版的事实来源。结果无法立即上报时，文件名与状态、耗时和错误码一起进入现有 outbox，恢复网络后原样补报。

### 契约、校验与兼容性

- `POST /wps-api/v1/format/result` 新增可选 `document_name`。新客户端仅在 Host 返回非空名称时发送；旧客户端省略该字段仍按现有结果流程成功。
- 接受的值必须是 1–120 个字符的单一基础文件名，不能含路径分隔符、NUL、换行或其他控制字符。服务端不从客户端猜测、清洗或还原路径；无效值以稳定 `DOCUMENT_NAME_INVALID` 失败。
- `document_name` 是结果幂等 payload 的一部分。相同请求编号重复补报必须带相同名称或同时省略；终态已保存后不得用重试覆写为另一个文件名。
- 服务端先升级到 Schema v4，再发布会发送该可选字段的客户端。历史记录和旧客户端因默认空字符串保持可读，后台以 `-` 展示未知名称。
- `wps_format_requests.document_name` 只通过已有管理员 session 保护的 WPS 查询展示。应用日志、WPS 本地诊断日志、错误消息、审计日志和最终状态摘要均不得记录该值。

## 本机通信与事务

Host 与 TaskPane 通过 Control Server 的 HostBridge 单槽长请求通信。WPS 对象只在 Host Runtime 主线程操作；Python CommandMonitor 串行业务命令。

正式排版使用本地文件事务：准备临时 DOCX、关闭或桥接当前文档、原子替换、重新打开、完成或回滚。事务 journal 用于 Launcher 重启后的恢复。WPS 端不复制 Recognition、编号、标点或 Engine 算法。

Control 客户端断开只表示本机 Host/TaskPane 离开，不改变公网账号状态。只有真实公网 `network=True` 错误才进入服务器离线状态。

## 管理后台

统一管理员工作台继续复用 Web 管理员 session 和 CSRF 边界，但按数据库分成网页业务与 WPS 插件两个模块。WPS 页面查询用户、设备、在线状态、授权请求、结果统计和真实管理员审计事实。

`WPS_ADMIN_MUTATIONS_ENABLED` 是进程启动时解析的服务端唯一管理写操作门禁，缺失时关闭、非法值 fail fast，不写入 WPS 数据库且不暴露给公网客户端。关闭时页面隐藏状态变更、密码重置、通知发送和硬删除，直接 POST 同样以稳定错误拒绝；只有完成客户端重新认证和 outbox 保留验证后才能由部署配置显式开启。

启用后，停用用户或设备会更新状态并撤销对应公网会话；重置密码撤销该账号全部会话；发送通知写入账号级纯文本记录；硬删除按会话、排版请求、通知、设备、用户顺序在一个事务内删除，并要求再次输入当前账号名确认。状态、密码、通知和删除成功均与审计事实同事务提交，删除确认不匹配可单独保留 `denied` 审计。在线状态根据最后心跳时间实时计算，不增加冗余 `online` 字段。

## HTTP 契约

WPS 外部接口统一位于 `/wps-api/v1/*`。注册、登录、当前账号、退出、心跳、排版授权和结果回传的请求、响应、鉴权、状态码和错误码全部见 [`docs/API.md`](docs/API.md)。

本机 Control 的 `/v1/*` 接口不属于公网 HTTP 契约；它使用 loopback credential、Origin 校验和运行配置保护。

## 日志与隐私

日志只记录事件名、阶段、状态、耗时、计数、稳定错误码、异常类型和脱敏短 ID。禁止记录密码、Token、Authorization、Cookie、设备密钥、正文、基础文件名、文件路径、完整哈希或数据库内容。

后台心跳离线只在状态变化时记录一次“服务器无法连接”；恢复后记录一次恢复事件。TaskPane 用户提示使用中文，稳定代码放在“错误代码：”之后。

## 验证

最低覆盖：

- WPS 数据库 v1→v2→v3→v4 迁移、唯一约束、状态事务、通知确认、文件名元数据和 7 天到期；
- Argon2 参数、双槽并发限制和锁外哈希升级；
- 登录窗口、自动登录提交、无账号不加载插件和端口冲突；
- Bootstrap/`/auth/me` Snapshot、服务端心跳节拍、重新认证交接、离线/恢复状态和持久 outbox；
- 授权上下文、request_id、Host generation 和结果终态；
- 管理后台数据库隔离、审计同事务、门禁关闭拒绝和启用后的状态/密码/通知/硬删除；
- 登录首批与心跳增量通知、Runtime/Control 转发、TaskPane 纯文本展示和幂等确认；
- Control、文档事务和真实 WPS 人工验收。

自动化门禁见 [`docs/WPS_REGRESSION_CHECKLIST.md`](docs/WPS_REGRESSION_CHECKLIST.md)。真实宿主步骤和结果见 [`docs/WPS_VALIDATION.md`](docs/WPS_VALIDATION.md)。

## 生产部署链路收敛

### 目标与非目标

生产环境只有一个面向浏览器和 WPS 正式客户端的公开 Origin：
`https://docxtool.pages.dev`。网页、管理后台和 WPS 公网 API 分别使用
`/api/*`、`/admin/*` 与 `/wps-api/v1/*`，均由同一个 Cloudflare Pages Worker
转发。

目标链路固定为：

```text
浏览器 / WPS 客户端
        ↓ HTTPS
https://docxtool.pages.dev
        ↓ Cloudflare Pages Worker
        ↓ HTTPS + Access Service Token + X-Proxy-Secret
https://<PRIVATE_ORIGIN_HOST>
        ↓ Cloudflare Access → Cloudflare Tunnel
http://127.0.0.1:9527
        ↓
DocxTool Python
```

`<PRIVATE_ORIGIN_HOST>` 仅为文档占位符，不记录真实服务器 IP、域名或密钥。Python
始终绑定 `127.0.0.1:9527`；DocxTool 不公开监听 `8080` 或 `9527`。本轮不改动
Recognition、Normalization、Engine、WPS 本机 Control 协议，也不新建第二个 Worker、
独立管理后台或直连 Origin fallback。

### 已核实基线与设计决策

- Pages Worker 已按 allowlist 代理 Web、管理员和 WPS 管理后台路由，并注入
  `X-Proxy-Secret` 与 `X-Docxtool-Proxy`；本轮在同一代理实现中加入 Access Service
  Token，不复制代理逻辑。
- WPS 公网协议固定为 `/wps-api/v1/*`。其客户端只要求无路径的 HTTPS Origin，并在
  登录后以 `Authorization: Bearer <session>` 认证；服务端已有固定路由和 Bearer
  校验，不依赖独立公网域名。
- 因此 WPS 正式 EXE 可以使用 `https://docxtool.pages.dev`。Worker 只对固定
  WPS allowlist 保留 Bearer 请求头；普通 Web/API 路由仍剥离浏览器提交的
  `Authorization`。WPS 路径不转发浏览器 Cookie，不新增直连服务器 IP 的兼容路径。
- 管理登录与所有管理写操作继续使用同源相对跳转、Cookie、CSRF 和 Worker allowlist；
  后端当前生成相对 `Location`，不会把浏览器重定向到 Private Origin。

### Worker 服务间认证

Pages 环境变量只由 Pages Secret 保存：

```text
BACKEND_BASE_URL=https://<PRIVATE_ORIGIN_HOST>
PROXY_SECRET=<same-as-backend>
CF_ACCESS_CLIENT_ID=<Cloudflare Access service token id>
CF_ACCESS_CLIENT_SECRET=<Cloudflare Access service token secret>
```

Worker 对每个实际回源请求先删除客户端提交的 `CF-Access-Client-Id`、
`CF-Access-Client-Secret`、`X-Proxy-Secret`、代理来源头和管理员凭据，再仅从
Pages 环境变量注入：

```text
CF-Access-Client-Id
CF-Access-Client-Secret
X-Proxy-Secret
X-Docxtool-Proxy: cloudflare-pages
```

缺少任一回源配置、使用非 HTTPS 回源或把 `BACKEND_BASE_URL` 配置为 IP 字面量时，
Worker 返回明确的 5xx 配置错误，不回退到裸服务器地址。Service Token、Proxy Secret
和浏览器 Bearer Token 不写入响应、日志、文档示例或客户端源码。

### 后端生产配置与 Fail Fast

生产服务器配置为：

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

`ADMIN_TOKEN` 和 `PROXY_SECRET` 继续使用不同的随机生产密钥。生产模式要求明确的 HTTPS
`FRONTEND_ORIGIN`，管理 Origin 与前端 Origin 相同；管理员 Cookie 使用 `Secure`，不
再支持生产 HTTP 管理入口。

`PRODUCTION_MODE`、`TRUST_PROXY_HEADERS`、`COOKIE_SECURE` 与
`ADMIN_COOKIE_SECURE` 使用严格布尔解析。合法值仅为现有的
`1/true/yes/on` 或 `0/false/no/off`；拼写错误必须在启动时以包含变量名的配置错误退出，
不得回退默认值。文件 API 在生产环境仍只接受有效 `X-Proxy-Secret`；本地 loopback
开发例外不额外复制第二套判断，而由可靠的生产模式解析保护。

### 迁移、发布与验收

部署文档移除 Nginx、服务器 `8080`、裸 HTTP 管理入口和 IP 回源说明；仅服务旧路径的
`deploy/nginx-docxtool.conf` 已删除，发布脚本同步允许该删除。运维侧需自行：

1. 让 `cloudflared` 将 Private Origin 的 Tunnel 服务指向 `http://127.0.0.1:9527`；
2. 用 Cloudflare Access 的 Service Auth 保护 Private Origin；
3. 将上述四个 Pages 变量配置为 Secret，并按后端配置重启服务；
4. 关闭服务器对 DocxTool `8080` 与 `9527` 的公网入站规则；
5. 用 Pages HTTPS 路径验证用户、管理员登录/登出、会话、管理写操作和 WPS 公网 API。

代码验收覆盖 Worker 注入/覆盖 Token、缺失配置、管理员 Cookie/相对跳转、WPS Bearer
透传及 allowlist；后端覆盖严格布尔解析、HTTPS 同源管理员配置和生产文件 API 边界。
完整自动化验证不等同于真实 Tunnel、Access 或 Pages 线上联通；后者必须在配置完成后
人工验证。

## 非目标

当前不实现卡密、支付、套餐、次数扣减、异常设备识别、自动封禁、远程任意命令、WebSocket、消息队列、微服务或文档上传。

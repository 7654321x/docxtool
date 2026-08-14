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

公网服务器不接收 DOCX、正文、文件名、路径、图片、表格、文档哈希或识别结果。服务器只处理账号、设备、会话、授权配置版本和排版终态统计。

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
| `wps_format_requests` | 唯一请求编号、功能、授权状态、终态和配置版本 |

数据库不保存原始密码、原始设备序列号、原始会话 Token 或文档数据。用户、设备和会话状态必须在授权和心跳事务内联合复核。

新注册和新登录会话从签发时起精确有效 7 天；心跳不续期。已有会话只按数据库中的 `expires_at` 判断，不执行批量迁移。

## 密码与登录性能

- Argon2id 固定使用 `memory_cost=65536 KiB`、`time_cost=3`、`parallelism=4`。
- 单进程使用 `BoundedSemaphore(2)` 统一限制注册哈希、真实或虚假账号校验及旧哈希升级。
- 旧哈希升级在 SQLite 写锁和 `BEGIN IMMEDIATE` 前计算，事务内只复核状态并保存预计算哈希。
- WPS 登录限流为同 IP `300/600s`、同账号 `10/600s`；注册为同 IP每小时 5 次。
- 网页账号和匿名排版不使用 WPS Argon2 信号量，也不改变网页登录限流。

## 本地账号与启动链

`apps/wps/account_store.py` 使用本地 SQLite；密码、会话 Token 和设备密钥在写入前使用当前 Windows 用户 DPAPI 加密。本地数据库同时保存登录偏好和持久格式结果 outbox。

启动顺序固定为：

```text
移除当前项目旧加载项注册
→ 显示登录/注册窗口
→ 可选自动登录在窗口显示后提交一次
→ 登录或注册成功
→ 创建 AccountRuntime
→ 启动 Control Server 和固定 127.0.0.1:3889 静态服务
→ 发布运行配置和 docxtool-wps-app
→ 立即心跳，之后每 600 秒一次
```

没有账号、账号损坏、窗口取消或公网认证失败时，不创建 AccountRuntime、Control Server 或静态服务，也不发布加载项。自动登录失败后保留窗口，用户可以修改后手动登录。

本地端口被占用时，只有运行配置和 Control 健康接口共同证明占用者是 DocxTool 旧服务，才允许停止旧服务并重试；其他占用立即返回 `WPS_WEB_SERVER_PORT_IN_USE`。

## 会话与心跳

AccountRuntime 启动后立即心跳，随后每 600 秒执行一次，不进行高频失败重试。只有 `PublicApiError.network=True` 才标记“服务器离线”；会话过期、账号禁用和设备禁用走各自状态。

网络恢复后先更新账号摘要，再补报 SQLite outbox。账号被 `INVALID_CREDENTIALS`、`ACCOUNT_DISABLED` 或 `DEVICE_DISABLED` 明确拒绝时，本地账号和全部待发回执在同一 SQLite 事务中删除；网络失败、会话过期和正常停止保留回执。

## 排版授权与结果补报

每次一键排版先由 Control 创建唯一 `request_id` 并调用公网授权。授权成功后，完整 `format_config` 只保存在本机 Control 授权上下文；HostBridge 只接收 `request_id` 和 `config_version`。

授权上下文只能消费一次并绑定一个 `apply` 事务。prepare、commit、finalize 和 rollback 必须使用同一请求编号。Host 终态先验证上下文和 generation，再把本地真实 `PASS/FAIL` 写入 SQLite 持久 outbox。

公网结果暂时不可达不改变本地排版终态；TaskPane 通过账号摘要中的 `pending_result_count` 显示未同步数量。心跳恢复或下一次 Launcher 启动后继续补报。

预览、清除预览、本机检测、TaskPane 设置、添加版头和 Reader 不调用公网排版授权。

## 本机通信与事务

Host 与 TaskPane 通过 Control Server 的 HostBridge 单槽长请求通信。WPS 对象只在 Host Runtime 主线程操作；Python CommandMonitor 串行业务命令。

正式排版使用本地文件事务：准备临时 DOCX、关闭或桥接当前文档、原子替换、重新打开、完成或回滚。事务 journal 用于 Launcher 重启后的恢复。WPS 端不复制 Recognition、编号、标点或 Engine 算法。

Control 客户端断开只表示本机 Host/TaskPane 离开，不改变公网账号状态。只有真实公网 `network=True` 错误才进入服务器离线状态。

## 管理后台

统一管理员工作台继续复用 Web 管理员 session 和 CSRF 边界，但按数据库分成网页业务与 WPS 插件两个模块。WPS 页面只查询 WPS 用户、设备、在线状态、授权请求和结果统计。

停用用户或设备时更新状态并删除对应公网会话；不删除历史请求记录。在线状态根据最后心跳时间实时计算，不增加冗余 `online` 字段。

## HTTP 契约

WPS 外部接口统一位于 `/wps-api/v1/*`。注册、登录、当前账号、退出、心跳、排版授权和结果回传的请求、响应、鉴权、状态码和错误码全部见 [`docs/API.md`](docs/API.md)。

本机 Control 的 `/v1/*` 接口不属于公网 HTTP 契约；它使用 loopback credential、Origin 校验和运行配置保护。

## 日志与隐私

日志只记录事件名、阶段、状态、耗时、计数、稳定错误码、异常类型和脱敏短 ID。禁止记录密码、Token、Authorization、Cookie、设备密钥、正文、文件路径、完整哈希或数据库内容。

后台心跳离线只在状态变化时记录一次“服务器无法连接”；恢复后记录一次恢复事件。TaskPane 用户提示使用中文，稳定代码放在“错误代码：”之后。

## 验证

最低覆盖：

- WPS 数据库 Schema、唯一约束、状态事务和 7 天到期；
- Argon2 参数、双槽并发限制和锁外哈希升级；
- 登录窗口、自动登录提交、无账号不加载插件和端口冲突；
- 心跳 600 秒节拍、离线/恢复状态和持久 outbox；
- 授权上下文、request_id、Host generation 和结果终态；
- 管理后台数据库隔离；
- Control、文档事务和真实 WPS 人工验收。

自动化门禁见 [`docs/WPS_REGRESSION_CHECKLIST.md`](docs/WPS_REGRESSION_CHECKLIST.md)。真实宿主步骤和结果见 [`docs/WPS_VALIDATION.md`](docs/WPS_VALIDATION.md)。

## 非目标

当前不实现卡密、支付、套餐、次数扣减、异常设备识别、自动封禁、远程任意命令、WebSocket、消息队列、微服务或文档上传。

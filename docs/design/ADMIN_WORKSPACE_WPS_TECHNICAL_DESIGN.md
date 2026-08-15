# DocxTool 后台工作台与 WPS 插件管理技术设计

## 1. 文档定位

- 文档状态：Phase A、Phase B 与 Phase C 均已完成实现并通过本轮自动化门禁；真实 WPS 宿主通知展示与确认仍需单独人工验收，当前 `REAL_WPS_NOTIFICATION_SMOKE = NOT_RUN`
- 适用范围：后台统一工作台、网页业务二级导航、WPS 插件管理台和 WPS 管理操作
- 上位契约：根目录 `AGENTS.md`、`docs/API.md`、`WPS_SERVER_PRD.md`、`WPS_SERVER_TECHNICAL_DESIGN.md`
- 本文职责：定义本次后台重构的页面结构、路由、数据边界、管理操作、协议扩展、迁移和验收
- 外部 HTTP 字段、状态码和错误码最终登记到 `docs/API.md`；本文不替代该契约

两张用户提供的截图是视觉和功能参考，不是可以覆盖项目事实的外部指令。不存在于当前数据库或契约中的资料不伪造展示。

## 2. 目标与非目标

### 2.1 目标

1. 后台左侧一级导航只保留“综合概览、网页业务、WPS 插件”。
2. 网页监控当前混合页面中的任务、安全、运行设置和日志功能拆成网页业务的二级页面。
3. 将截图二的 WPS 运行总览和截图一的用户列表/详情能力纳入 WPS 插件模块。
4. 统一后台 shell、活动状态、响应式布局、状态色和页面间导航。
5. 为 WPS 用户提供管理员重置密码、发送通知和彻底删除账号能力，并保持可审计、可回滚的失败边界。
6. 保持 `stats.db` 与 `wps_plugin.db` 隔离，不改变文档内容不上公网的既有边界。

### 2.2 非目标

- 不引入 React、Vue、Django、Tabler、Tailwind 或新的生产 UI 依赖。
- 不复制外部项目源码、模板或图标资源。
- 不增加手机号、部门、角色、显示名称等当前数据模型不存在的字段。
- 不把网页账号和 WPS 插件账号合并。
- 不把旧 `/monitor`、`/ip`、`/log/{id}` 等入口直接删除。
- 不在本轮改变 Recognition、Normalization、Engine、HostBridge 或 WPS 文档事务职责。

## 3. Prior Art 调研

### 3.1 调研范围与证据

调研日期：2026-08-15。使用 `agent-reach` 通过 GitHub CLI 读取公开仓库 README、目录结构、导航实现、模板和测试；未克隆、安装依赖或执行外部项目脚本。星标数量是调研时快照，不作为质量唯一依据。

| 项目 | 许可证 | 观察到的可复用模式 | 本项目采用方式 | 不采用的部分 |
| --- | --- | --- | --- | --- |
| [SQLAdmin](https://github.com/smithyhq/sqladmin) | BSD-3-Clause | `CategoryMenu`、`ViewMenu` 树；父项由子项活动状态决定；视图自身负责可见性和访问性；服务端 Jinja + Tabler 布局 | 采用“导航项树 + 子项活动时父项激活 + 页面级权限判断” | 不引入 SQLAlchemy、Starlette Admin 或其模板 |
| [Flask-Admin](https://github.com/pallets-eco/flask-admin) | BSD-3-Clause | `BaseMenu`、分类、链接和子菜单分离；父分类仅在有可见/可访问子项时显示 | 采用可见子项过滤和独立链接/页面职责 | 不引入 Flask 扩展、ORM 自动 CRUD 或 Bootstrap 资源 |
| [FastAPI-Admin](https://github.com/fastapi-admin/fastapi-admin) | Apache-2.0 | `Resource`/`Dropdown` 注册模型，资源清单驱动侧栏；Tabler 的垂直导航和页面卡片 | 采用模块资源清单驱动页面导航和概览卡片 | 不引入 TortoiseORM、Redis、外部 CDN 或其运行时 |
| [Django Unfold](https://github.com/unfoldadmin/django-unfold) | MIT | 侧栏按 section/items 组织；支持 active、permission、badge；详情页可用 tabs 和可复用 section/component | 采用模块二级菜单、详情页 tabs 和可复用 panel 语义 | 不迁移 Django Admin、Tailwind、Alpine 或 HTMX |
| [Tabler](https://github.com/tabler/tabler) | MIT | 响应式垂直 sidebar；菜单数据使用 `children`；`autoOpen`/`keepOpen` 保持当前分支展开；指标卡和两列 dashboard 布局 | 借鉴深色 shell、三级视觉层次、指标卡、趋势/列表组合和移动端折叠 | 不作为项目依赖，不直接复制其 CSS、JS 或静态资源 |

### 3.2 结论

共同模式可以压缩为一条本地规则：

```text
稳定导航定义
    ↓
按当前路径计算子项 active
    ↓
父模块在子项 active 时展开
    ↓
页面只负责自己的查询和业务操作
    ↓
详情页用稳定 tab 显示相关子资源
```

因此本项目采用一个轻量的服务端导航描述，不引入外部 admin 框架。外部仓库只提供设计证据；最终实现必须服从当前路由、数据库、WPS 协议和项目兼容约束。

公开仓库的许可证只说明参考项目的授权条件，不能自动授权复制代码或资源。本次设计不复制大段源码；若后续确需采用第三方静态资源，必须单独核实许可证、来源登记和打包影响。

## 4. 实施前基线事实

本节记录立项时已经核实的基线，用于说明阶段拆分原因；当前完成状态见第 11.3 节及 `docs/API.md`、`WPS_SERVER_TECHNICAL_DESIGN.md`。

### 4.1 Web 管理台

- `src/docxtool/web/admin_workspace_page.py` 已有统一 shell，但目前只有三个平铺链接，没有二级导航。
- `/admin` 已汇总网页和 WPS 的少量指标。
- `/admin/web` 当前直接复用旧 `/monitor` 渲染器，任务、安全、运行设置和日志仍混在一个长页面中。
- `/monitor`、`/ip`、`/log/{task_id}`、`/ban`、`/unban`、`/limit` 和 `/cleanup` 已经是现有兼容入口。
- 管理员 session、POST CSRF 和安全响应边界已经存在，应继续复用。

### 4.2 WPS 管理台和数据库

- 当前 WPS 管理路由只有用户列表、用户详情、用户状态和设备状态。
- `wps_plugin.db` 当前 schema version 为 1，包含 `wps_users`、`wps_devices`、`wps_sessions` 和 `wps_format_requests` 四张核心表。
- 当前真实字段足以展示账号、状态、注册/登录时间、设备、平台、插件版本、在线状态、排版请求和错误代码。
- 当前没有通知表、管理员操作审计表、密码重置操作或账号删除操作。
- WPS 心跳为 `POST /wps-api/v1/heartbeat`，客户端通过 `apps/wps/public_api.py` 和 `apps/wps/account_runtime.py` 调用。
- 当前注册/登录响应已包含用户、设备、会话创建/到期时间、功能清单和配置版本；但客户端的 `account_from_response()` 与 `account_store` 只持久化其中一部分字段。
- `GET /wps-api/v1/auth/me` 已能返回当前会话的用户、设备、会话、功能和配置摘要，但正常登录后不需要再调用它重复获取同一批数据。
- TaskPane 的账号摘要通过已有本机 Control 状态链路同步，不新增第二套本机通信协议。

## 5. 总体架构

### 5.1 页面与数据流

```text
管理员 session + CSRF
        ↓
统一后台 shell / 导航树
        ├─ 综合概览：Web 查询 + WPS 查询，在应用层汇总
        ├─ 网页业务：只查询 stats.db
        └─ WPS 插件：只查询 wps_plugin.db

WPS 登录 / 注册 / 重新认证
        ↓
Account Bootstrap Snapshot
        ↓
account_store + AccountRuntime
        ↓
WPS 插件账号心跳（携带通知增量）
        ↓
WPS 公网服务读取待确认通知
        ↓
AccountRuntime 更新账号摘要
        ↓
现有 Control state/wait
        ↓
TaskPane 展示并发送 acknowledged 确认
```

两个数据库只在应用层分别查询和组合，不使用跨数据库 SQL JOIN、共享连接或跨库事务。

### 5.2 WPS 客户端账号初始化与状态刷新

WPS 客户端采用“Account Bootstrap Snapshot + heartbeat 增量刷新”模型。每次通过登录窗口成功建立认证会话时，包括手工登录、注册后自动登录、用户已明确开启自动登录后的启动登录，以及用户显式完成的重新认证，服务端都通过同一份注册/登录成功响应返回完整 Bootstrap Snapshot。运行期会话过期、撤销或状态拒绝统一进入 `reauth_required`，必须等待用户显式重新登录；`AccountRuntime` 不得在后台读取旧密码、调用登录接口或跳过登录窗口。

`LoginWindow` 只负责收集凭据、触发认证和展示结果，不拥有第二套账号字段查询、拼装或持久化逻辑。所有来源先经同一份公共 Snapshot 解析与字段校验；注册/登录响应再将公共 Snapshot 与本地凭据、设备密钥和新 session token 组合为本地账号。`/auth/me` 使用已有 bearer session，既不返回也不得伪造 `session_token`；它复用公共 Snapshot 解析，然后只合并服务端拥有的非敏感字段，保留现有本地的 token、设备密钥、密码和记住/自动登录偏好。实现可保留或重命名 `account_from_response()`，但不得让 `/auth/me` 冒充登录响应，或维护第二套字段校验。启动登录窗口内的自动登录和用户显式重新认证必须复用同一解析、保存和运行时接管链路。

| 数据 | 注册/登录/重新认证返回 | 本地保存 | heartbeat 刷新 |
| --- | --- | --- | --- |
| `user.id`、`user.username`、`user.status` | 是 | 是 | 账号状态变化或认证错误时更新 |
| `device.id`、`device.device_name`、`device.platform`、`device.status` | 是 | 是 | 设备状态变化或认证错误时更新 |
| `session_created_at`、`session_expires_at` | 是 | 是 | 新会话建立时更新 |
| `features`、`config_version`、`heartbeat_interval_seconds` | 是 | 是 | 是 |
| 待确认通知 | 首批有限数量 | 仅运行期 pending 摘要 | 是，按通知 ID 去重 |
| `network_available`、`apply_available`、`pending_result_count`、`error_code`、`reauth_required` | 否 | Runtime | Runtime |

Bootstrap 不携带后台专用字段，例如 `created_at`、`last_login_at`、`last_ip`、累计排版统计、全部设备/会话、管理员审计或历史任务。客户端响应解析必须校验上述必需字段和类型；缺少必需稳定字段时以稳定响应错误失败，不用猜测性默认值拼出半完整账号状态。Phase C 的 `notifications` 是可选追加字段，缺失时按空列表处理以保持旧服务端/客户端兼容。

密码、原始 session token 和设备密钥继续按现有 DPAPI 边界保存，不属于可展示的 Bootstrap 字段。客户端仍按现有公网契约在 heartbeat 请求中发送 `device_id` 和 `app_version` 用于会话—设备绑定与版本更新；“登录一次获取”指不重复查询或拼装稳定身份资料，不删除该安全校验字段。

`heartbeat_interval_seconds` 在注册/登录响应与 heartbeat 响应中使用同一 canonical 服务端配置。客户端启动后立即采用 Bootstrap 值，运行中收到 heartbeat 新值后更新下一次调度，不能先依赖本地硬编码频率再等待首个 heartbeat。

旧本地账号数据库缺少新增快照字段时，不得清空账号或 outbox：若现有 session 有效，使用一次 `/auth/me` 补齐同一 Bootstrap 字段（不重新签发 token，且仅合并公共字段）；否则在下一次成功认证时补齐。`/auth/me` 保留为会话恢复、快照缺失、诊断或显式重新同步接口，不作为每次成功登录后的必经请求。

#### 5.2.1 `reauth_required` 的桌面交接

`AccountRuntime` 在后台线程中只负责写入 `reauth_required`、停止受控功能授权、保留 outbox，并发出一次性重新认证请求；它不得直接打开 Qt 窗口、退出进程或操作 WPS UI。

认证状态转换必须有界，避免旧密码循环和无意义弹窗：

| 触发条件 | `AccountRuntime` 动作 | UI 与数据边界 |
| --- | --- | --- |
| `SESSION_EXPIRED` | 直接转入 `reauth_required` | `DesktopController` 在主线程打开重新认证窗口；运行期不读取或自动提交旧密码 |
| `SESSION_INVALID` | 直接转入 `reauth_required` | 该错误可能来自密码重置、停用或硬删除，不尝试用旧密码静默猜测原因 |
| `INVALID_CREDENTIALS`、`ACCOUNT_DISABLED` 或 `DEVICE_DISABLED` | 保留本地账号摘要和 outbox，转入 `reauth_required` | 显示稳定的认证或状态提示，不调用 `clear_account()`，不删除待补报结果 |
| 纯网络错误 | 保留当前认证状态和 outbox | 仅记录网络状态并使用既有心跳调度恢复，不要求用户重新认证 |

每次从正常状态进入 `reauth_required` 只发出一次 UI 请求；只有成功重新认证、用户明确移除本地账号，或进程重新建立运行时后才重置该请求标记。

进入 `reauth_required` 必须通过 `account_store` 的专用本地会话失效操作（实际名称可随现有模块命名），而不是调用会同时删除账号和 outbox 的 `clear_account()`。该操作在同一处完成以下最小状态变更：保留账号摘要、设备标识和全部待补报结果；清空无效 session token 与到期时间；关闭运行期的旧凭据自动提交，并重置重新认证请求标记。登录窗口不得读取、预填或自动提交旧密码；只有用户显式完成新的认证后，才允许以新凭据覆盖本地受保护凭据并重新开启其选择的记住/自动登录偏好。

`DesktopController` 是重新认证交接 owner：通过 Qt 主线程接收该请求，提示用户会话已失效并打开现有登录窗口的重新认证模式。该模式复用同一 `submit_account()` → `account_from_response()` → `account_store.save_account()` 链路，预填账号和复用设备密钥，但不预填或自动提交旧密码。

- 用户认证成功：`DesktopController` 要求 `AccountRuntime.reload_account()`，清除 `reauth_required`，恢复下一次心跳、授权和 outbox 补报；
- 用户取消或认证失败：保持 `reauth_required=true`、`apply_available=false` 和 outbox，不重复弹窗；托盘“登录与账号设置”入口再次打开同一重新认证模式；
- 已经有重新认证窗口时不再创建第二个窗口；
- 当前本地文档事务不因重新认证提示被中断，后续受控操作在重新认证成功前明确拒绝。

#### 5.2.2 认证调度边界

`auto_login` 只允许发生在启动流程已经打开 `LoginWindow` 之后，且必须调用与用户点击“登录”完全相同的 `submit_account()` 链路；它不是 `AccountRuntime` 的后台能力，也不得用于会话失效后的重新认证。`AccountRuntime` 只能检测认证状态、保存脱敏状态、停止受控功能并向 `DesktopController` 发出一次性 UI 请求。这样登录窗口始终是凭据提交 owner，后台线程始终不触碰 Qt UI 和受保护密码。

### 5.3 导航描述

共享 shell 使用一份 canonical 导航描述，至少表达以下字段：

- `key`：稳定模块或页面标识；
- `label`：显示文本；
- `href`：页面入口；
- `active_prefix` 或等价匹配规则；
- `children`：二级菜单；
- `visible`：当前管理员是否可见。

父项 active 的规则是：自身路径匹配，或任一可见子项 active。只有当前模块的二级菜单展开；刷新页面后根据 URL 恢复展开状态。导航描述不得复制到多个页面渲染器中。

### 5.4 渲染模块 ownership

页面渲染按职责拆分，不继续把所有 HTML、CSS 和业务页面堆进一个 Python 文件：

- `admin_shell.py`：共享 shell、canonical navigation、活动状态、共享 CSS 和通用 panel/table/form 组件；
- `admin_web_pages.py`：网页业务概览、任务、安全、运行设置和日志页面；
- `admin_wps_pages.py`：WPS 运行总览、用户、设备、排版任务和用户详情 tabs；
- `admin_workspace_page.py`：在调用方迁移期间保留兼容 facade；迁移完成后不得继续维护第二套页面实现。

不引入模板框架不等于所有服务端 HTML 必须放在同一模块；每个渲染模块只拥有自己的页面结构和字段组合。

## 6. 路由与页面结构

### 6.1 一级和二级路由

| 一级模块 | 页面 | 路径 | 默认内容 |
| --- | --- | --- | --- |
| 综合概览 | 全局概览 | `/admin` | Web/WPS 服务状态、综合指标、快捷入口 |
| 网页业务 | 模块概览 | `/admin/web` | 网页业务摘要和二级入口 |
| 网页业务 | 任务中心 | `/admin/web/tasks` | 任务指标、趋势、最近任务、分页 |
| 网页业务 | 安全与访问 | `/admin/web/security` | IP、封禁、访问状态和安全操作 |
| 网页业务 | 运行设置 | `/admin/web/runtime` | 上传限制、运行状态和维护操作 |
| 网页业务 | 日志查询 | `/admin/web/logs` | 任务日志查询和详情 |
| WPS 插件 | 运行总览 | `/admin/wps` | WPS 运行状态、趋势、请求和用户摘要 |
| WPS 插件 | 用户管理 | `/admin/wps/users` | 用户筛选、状态、设备和排版统计 |
| WPS 插件 | 设备管理 | `/admin/wps/devices` | 设备、在线状态、版本和启停 |
| WPS 插件 | 排版任务 | `/admin/wps/tasks` | 授权、成功、失败、待回报和耗时 |
| WPS 插件 | 用户详情 | `/admin/wps/users/{user_id}` | 用户概况及详情 tabs，不作为独立一级菜单 |

WPS 一级入口默认指向 `/admin/wps`，不再直接指向用户列表。

### 6.2 旧入口兼容与 POST 回跳

旧入口只映射到同一份模块化查询和渲染逻辑，可采用跳转或兼容 handler；不得继续维护旧的整页渲染实现，也不得因跳转丢失“指定 IP”或“指定任务日志”的详情语义。

| 旧入口 | 规范页面 | 必须保留的语义 |
| --- | --- | --- |
| `GET /monitor` | `/admin/web/tasks` | 已支持的分页、关键词和状态筛选 |
| `GET /ip?ip=...` | `/admin/web/security?ip=...` | 指定 IP 的访问/封禁详情，而不是只显示通用安全列表 |
| `GET /log/{task_id}` | `/admin/web/logs?task_id=...` | 精确任务编号对应的日志详情 |
| `POST /ban`、`POST /unban` | `/admin/web/security` | 成功后保留有效的目标 IP 上下文 |
| `POST /limit`、`POST /cleanup` | `/admin/web/runtime` | 成功后回到运行设置及其当前允许的筛选上下文 |

所有旧 POST 继续使用现有管理员鉴权和 CSRF，并遵循 Post/Redirect/Get。回跳地址由服务端根据 action 固定选择；不得接受任意请求参数作为 `next` 或重定向目标。查询参数只保留规范页面明确支持且已通过现有归一化/校验的字段，不盲目回显任意参数。`/stats` 和其他 JSON/文件接口不因页面重构改变。

### 6.3 WPS 用户详情 tabs

`/admin/wps/users/{user_id}` 使用 `tab` 查询参数或等价服务端标签，支持：

- `overview`：账号状态、当前设备、插件信息和使用统计；本轮不展示最近任务、基本信息或安全风险卡；
- `devices`：设备、平台、版本、最后在线和设备操作；
- `tasks`：该用户的排版请求；
- `logs`：已有可查询日志或明确空状态；Phase B 接入持久审计后显示管理员审计事件，不伪造历史记录；
- `security`：启停、密码重置、通知和删除账号。

不存在的资料字段不显示占位值；不把空字段包装成虚构的“手机号/部门/角色”。

用户列表中的“详情”默认以右侧抽屉加载同一份详情数据，保留列表和筛选上下文。无脚本环境或直接访问详情 URL 时仍渲染完整详情页，不能让抽屉成为唯一可访问路径。

## 7. 页面数据和视觉实现

### 7.1 共享 shell

继续使用服务端 HTML 和现有内联/模块 CSS，实现：

- 深色海军蓝背景和层级面板；
- 金色强调色；绿色、红色和黄色状态标签；
- 顶部标题、服务状态、刷新、导出、返回工具和退出；
- 桌面端固定侧栏，窄屏端折叠/横向二级导航；
- 表格横向滚动，不因窄屏破坏列语义；
- 所有动态文本 HTML escape，所有 POST 表单带现有 CSRF hidden input。

指标卡、趋势、列表和详情 panel 使用共享样式和小型渲染 helper，不为每个页面复制整份 CSS。

### 7.2 综合概览

综合概览只显示可由真实查询得到的指标，至少包括：

- 网页任务总数、成功数、失败数和当前排队数；
- WPS 用户数、在线设备数、排版请求数和待回报数；
- Web 与 WPS 服务 readiness；
- 指向两个业务模块的快捷入口。

### 7.3 WPS 运行总览

以截图二的结构实现：

- 账号、设备、请求、成功率、失败和待处理等综合指标卡；
- 按现有请求时间字段生成近 7 天趋势；无数据时显示明确空状态；
- 在线设备/插件版本摘要；
- 最近排版请求列表；
- 用户活跃和排版统计摘要。

成功率只对已完成的成功/失败请求计算；没有可比较分母时显示 `-`，不显示伪造的 0%。平均耗时只使用真实完成请求。

### 7.3.1 用户行交互

用户表的操作列只保留“详情”。点击后在当前列表右侧打开详情抽屉，支持关闭按钮、遮罩点击和 Escape 关闭，并把焦点还给触发“详情”的链接。

抽屉顶部展示真实账号摘要，并提供设备、日志和受服务端写操作门禁控制的账号管理入口。设备、任务、日志、安全仍使用稳定 tabs；所有会改变状态的表单继续复用现有 POST、CSRF、确认与服务端门禁，不能因为改为抽屉而新增第二套管理写操作协议。

### 7.4 网页业务页面

- 任务中心承接旧监控页的任务统计、趋势、最近任务和分页。
- 安全与访问承接活跃 IP、封禁列表、IP 详情和封禁/解封操作。
- 运行设置承接上传限制、readiness、版本和维护入口。
- 日志查询承接任务日志、筛选和详情，不把安全操作日志混入任务状态。

### 7.5 服务端分页与筛选

WPS 用户、设备、排版任务和 Phase B 的审计列表统一采用服务端分页，不先加载全部数据再在浏览器分页。页面至少支持：

- `page`：从 1 开始，默认 1；
- `page_size`：默认 20，按项目上限限制，不能由请求无限放大；
- `q`：账号、设备或请求编号搜索；
- `status`：状态筛选；
- `online`：设备在线筛选；
- `version`：插件版本筛选。

查询结果统一提供 `rows`、`total`、`page` 和 `page_size`，保留筛选条件生成上一页/下一页链接。不得继续使用“固定取前 200 条再假装分页”的实现。

## 8. WPS 管理操作与数据变更

### 8.1 管理员鉴权

所有管理变更继续使用现有管理员 session、`require_admin_post` 和 CSRF。GET 只读取和渲染，不能触发密码、通知、删除或状态变更。

### 8.1.1 WPS 管理写操作启用门禁

Phase B 的用户/设备启停、密码重置和硬删除必须同时受一个 canonical 的服务端管理写操作门禁 `WPS_ADMIN_MUTATIONS_ENABLED` 控制。该门禁是默认关闭的服务端布尔配置，使用项目既有服务端配置机制在进程启动时解析；缺失时为关闭，显式值非法时 fail fast，不静默放宽为开启。它不写入 WPS 数据库、不暴露给 WPS 公网客户端，也不作为后台页面中的可点击开关。

- 同一门禁驱动 action definition 的 `available`，但页面隐藏不能代替服务端保护；每个 WPS 管理 POST 在管理员鉴权和 CSRF 通过后、任何数据库写入前必须再次检查。
- 门禁关闭时返回稳定的“管理写操作未启用”结果（错误码最终登记到 `docs/API.md`），不执行业务写入、不写成功审计；如需记录拒绝事件，只能按 `result=denied` 保留脱敏上下文。
- Phase B 首次部署时保持门禁关闭：先完成 v2 schema、审计、Bootstrap/重新认证客户端和 outbox 兼容验证；确认项目承诺支持的客户端基线满足要求后，才由部署配置显式打开门禁。
- 门禁关闭或回退时，页面立即隐藏相关 action，直接 POST 同样被拒绝；已有只读查询和 Phase A 页面不受影响。

### 8.2 密码重置

管理员在用户详情的“安全” tab 输入新密码并提交：

1. 服务端复用 `validate_password`；
2. Argon2 哈希计算遵循现有并发限制，尽量在数据库写锁外完成；
3. 在同一事务内更新 `password_hash`、`updated_at`、删除该用户全部 `wps_sessions` 并写入成功审计；审计写入失败时整个密码重置回滚；
4. 成功后用户必须重新登录，历史设备记录保留；
5. 明文密码不得进入日志、审计记录、HTML 响应或异常信息。

运行中的旧客户端必须纳入该设计：

- 服务端撤销会话后，客户端下一次公网请求收到 `SESSION_INVALID` 或等价会话撤销错误；
- `AccountRuntime` 清除会话凭据并进入 `reauth_required` 状态，不在运行期使用旧密码重新登录；
- 客户端回到明确的重新登录界面，管理员重置密码不得被误判为账号非法；
- 本机尚未补报的排版结果保留在 outbox 中，不因密码重置、会话撤销或后台重新认证失败而静默删除；用户使用新密码重新登录后继续补报；
- 通用 `INVALID_CREDENTIALS`、`SESSION_INVALID`、`SESSION_EXPIRED` 及后台重新认证失败都不得触发 outbox 自动清理；只有用户明确执行本地“移除账号/清理本地数据”并完成确认时，才按现有本地清理语义处理剩余 outbox。

### 8.3 通知

新增 WPS 账号级通知，正文作为纯文本处理，不支持管理员注入 HTML/脚本。

数据库新增 `wps_notifications`，至少包含：通知编号、用户编号、标题、正文、级别、创建时间和 `acknowledged_at`，并建立用户/未确认/时间索引。标题、正文、列表长度使用项目统一输入上限。

公网协议采用增量扩展：

- 服务端提供唯一的 `list_pending_notifications(user_id)` 查询；注册、登录、用户显式重新认证和 heartbeat 都复用这一查询，不维护两套待通知筛选逻辑；
- 注册/登录/重新认证成功响应在 Phase C 返回首批有限数量待确认通知，避免用户启动后额外等待一次 heartbeat；
- `POST /wps-api/v1/heartbeat` 的成功响应增加 `notifications` 数组，运行期间继续返回尚未确认的有限数量通知；客户端按通知 ID 去重；
- 新增认证接口 `POST /wps-api/v1/notifications/read`，批量接收 `notification_ids` 并返回实际确认的编号；重复确认安全幂等，未知或已确认编号不产生副作用；
- 协议语义使用 `acknowledged`，表示通知已经送达并被客户端确认展示，不声称用户本人认真阅读；UI 可以继续显示“已读”；
- 任一有效设备确认后，该账号的通知视为 acknowledged；这是账号级语义，不为每台设备维护第二套状态；
- `AccountRuntime` 保存待展示摘要，并通过现有 Control state/wait 传给 TaskPane；TaskPane 展示后调用确认接口。

旧客户端忽略心跳响应中的新增字段，新客户端在服务端没有通知时正常运行。

### 8.4 彻底删除账号

删除操作必须要求管理员二次确认，推荐要求输入当前账号名。服务端再次校验确认值，不信任前端按钮状态。

在同一 `BEGIN IMMEDIATE` 事务内按依赖顺序删除：

1. `wps_sessions`；
2. `wps_format_requests`；
3. `wps_notifications`；
4. `wps_devices`；
5. `wps_users`。

失败时完整回滚。删除成功后释放账号名；与该账号相关的设备、会话、排版请求和通知不可恢复，并会改变历史 WPS 请求数、成功率和趋势统计。二次确认界面必须明确提示这一影响。管理员审计事件不随账号业务数据删除，以保留“哪个管理员授权上下文在何时执行了删除”这一安全事实，但不得记录密码、通知正文或 Token。

硬删除不新增 tombstone、已删除账号表或可枚举的 `ACCOUNT_DELETED` 公网错误。旧客户端在会话撤销后只会收到通用 `SESSION_INVALID`，随后旧密码登录时也只会收到通用 `INVALID_CREDENTIALS`；客户端不得从这些错误推断账号已删除。为避免把硬删除重新做成软删除，本机 outbox 默认保留；只有用户明确执行本地账号/数据清理并确认后才允许清空。

### 8.5 管理员审计

当前管理员认证不存在独立管理员用户身份，因此本阶段的 actor 定义为管理员授权上下文，不得虚构管理员账号、姓名或角色。管理员业务操作至少记录：

- `audit_id`；
- `actor_type`：`session` 或 `legacy_token`；
- `actor_session_id_short`：存在管理员 session 时记录不可复用的短摘要；
- `target_user_id`；
- `event`；
- `result`；
- `error_code`；
- `created_at`；
- `request_id` 或 `correlation_id`。

记录密码重置、通知发送、账号删除、用户/设备启停及删除确认失败。数据库迁移失败不写入该表，改用结构化应用日志记录。

本次采用 `wps_admin_audit_logs` 作为 WPS 数据库内的持久审计表。`target_user_id` 保存执行操作时的不可变目标用户 ID 文本，不设置指向 `wps_users` 的外键，不使用 `ON DELETE CASCADE`；账号硬删除后该字段继续保留。`actor_session_id_short` 只能是不可复用的短摘要，不保存完整 session、共享 Token 或 CSRF。

审计表不保存密码、Token、通知正文、设备密钥或完整请求体；账号硬删除时保留对应审计行。

每个管理状态变更的业务写入与其成功审计必须在同一数据库连接、同一事务中提交：密码重置、用户/设备启停、硬删除，以及 Phase C 的通知发送都不能出现“操作已生效但成功审计缺失”或“审计成功但业务回滚”。二次确认不匹配等未执行变更的拒绝结果可以单独写入 `result=denied` 审计；事务或迁移本身失败时优先记录结构化错误日志，不伪造成功审计。

若当前日志管线已经提供结构化事件，则优先复用，不另建重复日志框架。用户详情的 `logs` tab 只展示真实存在的审计记录。

## 9. Schema 迁移与兼容

### 9.1 版本

Schema 按阶段演进：Phase B 将 v1 升级到 v2，只新增审计表及索引；Phase C 再将 v2 升级到 v3，新增通知表及索引。不修改四张现有核心表的既有字段语义。

迁移要求：

- v1 数据库可原地升级到 v2，v2 数据库可原地升级到 v3；
- 已有用户、设备、会话和排版请求不丢失；
- 迁移失败回滚并保留原数据库可恢复性；
- `PRAGMA user_version` 大于当前支持版本时继续 fail fast；
- 新增运行时读取和迁移逻辑共用同一 canonical 字段语义；
- 已分别验证旧数据、审计写入、删除回滚、通知读写和通知删除回滚。

迁移生命周期使用现有结构化应用日志记录：`wps.database.migration.start`、`wps.database.migration.success`、`wps.database.migration.error`，字段至少包括 `from_version`、`to_version`、`error_code` 和 `duration_ms`。迁移不得依赖尚未创建的审计表写入失败记录。

### 9.2 兼容边界

- 心跳响应新增字段为向后兼容的追加字段。
- Phase B 在登录、注册和 `/auth/me` 响应追加 `heartbeat_interval_seconds`；服务端必须先于依赖该字段的新客户端部署。旧客户端忽略该字段；新客户端遇到缺失字段按稳定响应错误失败，不猜测本地默认值。
- `/auth/me` 只返回当前 bearer 对应的公共 Snapshot，不返回 session token；本地客户端必须采用“共享解析 + 现有账号合并”而非把它当作新的登录响应。
- 新增通知读取接口不改变现有登录、心跳、排版授权和结果回传字段。
- Phase C 的通知字段是登录/heartbeat 响应中的可选追加字段，旧客户端可忽略，新客户端将缺失字段视为无待确认通知。
- 旧管理 URL 保持兼容，但新页面链接统一指向模块化 URL。
- 账号删除是明确的破坏性管理操作，不提供自动恢复或隐式软删除。

## 10. 失败边界与安全

- 用户不存在、确认值不匹配、密码不合规、通知输入超限和数据库迁移失败必须立即返回稳定错误，不用默认值假成功。
- 管理操作失败只回滚当前事务，不退出长期运行的 Web/WPS 服务。
- SQL 一律参数化；页面输出和 TaskPane 通知按上下文转义。
- 不记录密码、Token、Cookie、设备密钥、通知正文、完整 IP/路径或完整哈希。
- 删除、密码重置和通知发送记录 `start → success/error` 生命周期，能够确定首个失败阶段。
- 数据库迁移记录 `wps.database.migration.start → success/error` 生命周期；迁移错误不能因为审计表不存在而被吞掉。
- 不用通知或日志功能引入轮询线程；通知复用已有心跳节拍和 Control 状态等待机制。

## 11. 分阶段实施与停止门禁

### 11.1 Phase A — Admin Workspace UI 与现有监控

只实现后台页面、查询和只读交互，不接入任何 WPS 管理写操作：

1. 共享 shell 与 canonical navigation；
2. Web 四个二级页面和旧 URL compatibility；
3. WPS 运行总览查询；
4. WPS users 服务端分页/筛选；
5. WPS devices 服务端分页/筛选；
6. WPS tasks 服务端分页/筛选；
7. WPS user detail tabs；
8. 右键菜单与“…”按钮共用的 action model；
9. 为后续阶段保留统一 action model，但只渲染当前真实可用的只读动作；
10. 完成 UI、route、query、分页、菜单可见性和兼容入口的聚焦验证。

Phase A 完成后必须停止并检查结果。明确不修改：

- WPS schema；
- `/wps-api/v1` 公网协议；
- `AccountRuntime`；
- Control state/wait；
- TaskPane。
- 用户/设备启停、密码重置、账号删除和通知等 WPS 管理 POST；

### 11.2 Phase B — WPS 管理写操作、审计与 Schema v2

Phase A 验收通过后再实现：

1. WPS schema v1 → v2，只增加审计表及索引；
2. `wps_admin_audit_logs` 及 actor/target 语义；
3. 为已有用户/设备状态操作接入持久审计并在本阶段首次开放这些状态变更；
4. 管理员重置密码；
5. 硬删除用户及破坏性确认提示；
6. 登录/注册/`/auth/me`/重新认证共用的 Account Bootstrap Snapshot：持久化已有稳定响应字段，并在这些恢复响应中追加与 heartbeat 共用的 `heartbeat_interval_seconds`；
7. 对 `account_store` 做向后兼容的本地快照字段迁移，复用公共 Snapshot 解析并区分“认证响应建账号”和“`/auth/me` 合并账号”，保持 LoginWindow 只负责 UI；
8. 最小范围修改 `PublicApi`、`account_store`、`AccountRuntime`、LoginWindow 与 `DesktopController` 认证链路，实现 `reauth_required`、主线程重新认证交接、禁止运行期后台提交旧密码、保留 outbox 和 `/auth/me` 按需恢复；
9. 管理操作错误、事务回滚和迁移生命周期日志；
10. migration、rollback、audit、Bootstrap、密码重置、桌面重新认证交接、删除和 outbox 保留测试。
11. 同步 `docs/API.md` 和 WPS 技术说明中的 Bootstrap、重新认证、硬删除和本地清理边界。

Phase B 可以修改认证相关的 `PublicApi`、`account_store`、`AccountRuntime`、LoginWindow 和 `DesktopController`，但只限上述 Bootstrap 与重新认证边界；不实现通知表、通知送达，不扩展 heartbeat 响应，不修改 Control state/wait 或 TaskPane。Phase B 验收通过后再次停止。

#### 11.2.1 实施切片

Phase B 按四个闭合切片实施，每个切片先完成对应聚焦测试，再开始下一切片；`WPS_ADMIN_MUTATIONS_ENABLED` 在 B1—B3 始终保持关闭：

1. **B1：服务端基础。** 新增并验证门禁解析、v1→v2 审计表迁移、迁移生命周期日志和审计 repository；不开放任何 WPS 管理写操作。
2. **B2：认证 Snapshot 与本地存储。** 在登录、注册和 `/auth/me` 追加/合并公共 Snapshot，完成本地快照兼容迁移、字段校验与 `heartbeat_interval_seconds` 调度来源；不改 Control/TaskPane。
3. **B3：运行时重新认证。** 实现专用会话失效、`reauth_required`、Qt 主线程交接和 LoginWindow 重新认证模式；验证运行期不读取或自动提交旧密码，outbox 始终保留。
4. **B4：受门禁保护的管理写操作。** 在 B1—B3 通过后接入用户/设备启停、密码重置、硬删除、PRG 回跳和同事务审计；分别验证门禁关闭的直接 POST 拒绝和门禁开启后的实际写入。

#### 11.2.2 客户端兼容与写操作启用顺序

Phase B 在同一设计内仍按安全顺序交付：

1. 先部署 v2 schema、审计能力和登录/`/auth/me` 的追加字段，并保持 WPS 管理写操作门禁关闭；
2. 再发布并验证带有 Snapshot 合并、`reauth_required`、仅限启动 LoginWindow 的自动登录和 outbox 保留行为的桌面客户端；
3. 验证会话自然过期、会话撤销、错误凭据、账号/设备停用、密码重置和硬删除都不会触发隐式 `clear_account()` 或 outbox 删除；
4. 只有项目承诺支持的桌面客户端基线已经包含上述行为时，才由部署配置显式打开门禁，并同时开放用户/设备状态变更、密码重置和硬删除的 UI 与 POST 路由。

若无法确认客户端基线已满足该条件，则视为启用门禁未通过，保持管理写操作不可用；不得为了赶进度先暴露会撤销会话的操作，再把旧客户端数据丢失解释为既有行为。

#### 11.2.3 停止与回退边界

1. v2 是只追加审计表和索引的前向迁移；停止 Phase B 或回退客户端时不自动执行 destructive down migration，也不删除已生成的审计事实。
2. 在门禁尚未打开前，客户端发布失败、兼容验证失败或认证链路异常时，保持门禁关闭即可阻止所有新的 WPS 管理写操作；旧客户端继续忽略新增响应字段，Phase A 的只读管理能力不受影响。
3. 门禁打开后发现写操作风险时，优先立即关闭 `WPS_ADMIN_MUTATIONS_ENABLED`，使 UI 隐藏动作且 POST 统一拒绝；不得通过篡改审计记录、伪造状态或自动恢复已提交的硬删除来“回退”。
4. 已提交硬删除的恢复只能作为独立事故处置，由经过授权的备份恢复方案处理；它不属于本次管理页面的常规回退路径。

### 11.3 Phase C — WPS Notifications 与客户端链路（已完成）

本阶段已完成：

1. WPS schema v2 → v3，增加 `wps_notifications` 及索引；
2. `wps_notifications` 的服务端读写和唯一 `list_pending_notifications` 查询；
3. 注册/登录/重新认证的首批通知，以及 heartbeat 的 additive `notifications` response；
4. `notifications/read` acknowledged 接口；
5. `PublicApi` 通知方法；
6. `AccountRuntime` 通知摘要，复用 Phase B 已建立的 reauth/outbox 状态；
7. Control state/wait 扩展；
8. TaskPane 展示、确认和兼容处理；
9. WPS Python/Node 测试、协议兼容测试和完整自动化验证。
10. 同步 `docs/API.md` 和 WPS 技术说明中的通知字段、acknowledged 语义和接口契约。

已执行变更范围验证、WPS 专项门禁、全量 pytest 和发布前 `-DryRun -Verify` 演练；演练未创建提交或推送。真实 WPS 宿主仍需单独报告 `REAL_WPS_NOTIFICATION_SMOKE`。

## 12. 验证与验收

### 12.1 自动化验证

- 路由测试覆盖三个一级入口、全部二级入口、活动状态和旧 URL 兼容。
- HTML 渲染测试确认一级菜单恰好三个、当前模块展开、截图核心区块存在且不出现虚构资料字段。
- Web 页面测试覆盖任务、安全、运行设置和日志拆分后的查询及 POST 回跳。
- Phase A：只运行页面、路由、查询、分页、菜单 action visibility、旧入口和只读用户详情的聚焦测试，并确认 `/monitor`、`/ip`、`/log/{task_id}` 仍进入对应二级页且不丢详情语义，`/ban`、`/unban`、`/limit`、`/cleanup` 仍按规范页面完成 PRG 回跳；确认没有 schema/API/client 变更。
- Phase B：运行 v1→v2、无通知表条件下的外键删除顺序、迁移失败回滚、审计 actor/target 与同事务提交、CSRF、权限、门禁配置缺失默认关闭与非法值 fail fast、管理写操作门禁默认关闭及直接 POST 拒绝、门禁显式开启后的用户/设备启停、密码规则、Bootstrap 响应解析、`/auth/me` 公共字段合并、本地快照迁移、专用会话失效不调用 `clear_account()`、会话撤销、主线程重新认证交接、启动登录窗口内的自动登录与运行期后台登录禁止、删除确认、历史统计提示、outbox 保留和客户端兼容启用门禁测试。
- Phase C：运行 v2→v3、包含通知删除的级联顺序、同一待通知查询的登录首批/heartbeat 增量、通知幂等、`notifications/read` acknowledged 语义、旧客户端兼容、AccountRuntime、Control 状态和 TaskPane 测试。
- 运行 `verify_changed.ps1`、相关 Python 测试、WPS Node 聚焦测试、`ruff` 和 `git diff --check`；L 级任务完成后按要求执行 FULL 门禁。

### 12.2 页面验收标准

1. 左侧一级导航只出现“综合概览、网页业务、WPS 插件”。
2. 点击网页业务时只能展开网页业务二级菜单；旧监控功能不再全部堆在一个默认页面。
3. 点击 WPS 插件默认进入运行总览，截图一和截图二的核心结构在真实数据范围内可见。
4. Phase A 完成时用户详情可以查看真实数据和分页浏览，但不提供 WPS 状态变更；用户/设备启停、密码重置和删除在 Phase B 的客户端兼容门禁通过后验收，通知在 Phase C 完成后验收。
5. 用户详情最终能够执行用户/设备启停、密码重置、通知发送和彻底删除，并正确处理成功、失败和重复操作。
6. 右键与“…”菜单只显示当前阶段真实可用的操作，不出现可点击的未实现能力。
7. 页面刷新、直接访问深层 URL 和移动端窄屏时，活动模块和二级菜单状态保持正确。
8. 真实 WPS 宿主未执行时，最终报告明确 `REAL_WPS_SMOKE = NOT_RUN`，不得将模拟测试宣称为真实宿主通过。

## 13. 明确决策

- WPS 默认入口为“运行总览”。
- 网页业务旧监控功能拆为四个二级页面。
- 用户详情采用概况、设备、任务、日志、安全 tabs。
- 账号删除采用硬删除，关联业务数据一并删除；审计事实保留。
- 管理员审计记录的是管理员授权上下文，不虚构独立管理员账号身份；目标用户 ID 不设外键，以支持硬删除后保留审计。
- 数据库迁移失败写结构化生命周期日志，不依赖尚未创建的审计表。
- 密码重置撤销会话并要求重新登录，不在运行期后台使用旧密码；本机待补报结果默认保留。
- 登录、注册、启动登录窗口内的自动登录和用户显式重新认证共用 Account Bootstrap Snapshot；稳定账号字段一次获取并本地保存，heartbeat 只刷新动态状态。
- `/auth/me` 只合并公共 Snapshot，绝不返回或伪造 session token；认证响应建账号与现有会话恢复共享字段校验但不混淆 token 所有权。
- `AccountRuntime` 只发出重新认证状态；`DesktopController` 在 UI 线程打开同一登录链路，取消时不重复弹窗、不丢 outbox。
- `/auth/me` 仅用于现有会话恢复、快照缺失、诊断或显式重新同步，不作为成功登录后的必经请求。
- 硬删除不增加 tombstone 或 `ACCOUNT_DELETED` 协议；客户端不从通用认证错误推断删除，outbox 只在用户明确本地清理后删除。
- 通知以账号为单位 acknowledged；登录返回首批待确认通知，heartbeat 继续增量刷新，UI 可显示“已读”，确认使用独立认证接口。
- Phase A 保持 WPS 管理只读；所有会撤销会话或改变账号状态的操作在 Phase B 的客户端兼容门禁通过后才开放，避免旧客户端清空 outbox。
- WPS 管理写操作由服务端 canonical 门禁统一控制：UI 可见性复用该状态，POST 路由独立强制检查；默认关闭，只有完成客户端兼容验证后才由部署配置显式开启。
- 实施顺序固定为 Phase A → Phase B → Phase C；每阶段完成后先验证并停止，不跨阶段夹带实现。
- 不引入第三方 admin/UI 框架，不复制 GitHub 项目源码，不新增不存在的用户资料字段。

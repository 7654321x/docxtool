# WPS 格式设置与本地模板库技术设计

## 目标与边界

本设计覆盖 WPS TaskPane 的“格式设置”中央 WebDialog、本地用户模板持久化和现有格式配置传递。用户可以按登录账号保存多个本机模板，通过 `select` 切换模板，并添加、重命名、修改或删除自定义模板。

模板仅保存在本机，不上传公网服务器。Recognition、Normalization、Engine、Reader、SDK、公网 HTTP 契约、Token、服务器数据库和 Core 默认格式模型均不修改。设置页继续只暴露段落样式、页面版式、字符设置和页码设置四类现有配置。

## 数据所有权与存储

`src/docxtool/resources/config/default-format.json` 继续作为唯一系统默认格式来源，经 `load_active_format_profile()` 和 `validate_format_config()` 校验后作为只读“系统默认”模板提供。系统默认模板不写入用户模板表，不允许重命名或删除；用户可以将其复制为新的自定义模板。

用户模板存入独立数据库：

```text
%LOCALAPPDATA%\DocxTool\wps\format_profiles.db
```

该数据库不与 `account.db` 合并。账号退出、被拒绝或本地账号记录清除时不删除模板；同一 `user_id` 再次登录后恢复原模板，新账号不可见旧账号模板。

数据库包含：

```text
format_profiles
  profile_id TEXT PRIMARY KEY
  owner_user_id TEXT NOT NULL
  name TEXT NOT NULL
  name_key TEXT NOT NULL
  config_json TEXT NOT NULL
  schema_version INTEGER NOT NULL
  revision INTEGER NOT NULL
  created_at INTEGER NOT NULL
  updated_at INTEGER NOT NULL
  UNIQUE(owner_user_id, name_key)

format_profile_state
  owner_user_id TEXT PRIMARY KEY
  active_profile_id TEXT NOT NULL DEFAULT ''
  legacy_migrated INTEGER NOT NULL DEFAULT 0
  updated_at INTEGER NOT NULL
```

模板名称和版本等可检索元数据使用独立 SQL 字段；嵌套格式内容使用经过 Core 校验的 JSON 文本保存，避免为每个字体、字号、页边距和功能开关建立重复数据库字段。`name_key` 由压缩空白后的模板名称 `casefold()` 得到，同一账号内名称唯一，不同账号允许同名。

`active_profile_id=''` 表示当前使用虚拟的系统默认模板。删除活动自定义模板时，在同一事务内把活动模板切回系统默认。数据库中不保存密码、Token、设备密钥、正文、文档名或路径。

## 账号隔离

模板 owner 只从已绑定的 `AccountRuntime` 获取稳定 `user_id`。Format Dialog、TaskPane 或其他浏览器端请求不得传入、覆盖或查询任意 `owner_user_id`。没有已登录账号运行时时，本地模板接口立即返回 `WPS_FORMAT_PROFILE_ACCOUNT_REQUIRED`。

模板数据库生命周期独立于 `account_store.clear_account()`：清理账号和结果 outbox 不打开、不修改模板数据库。账号切换后，新的 Control Server 只能以新账号 `user_id` 查询模板。

## 本机接口

现有 Control Server 增加仅限回环和现有 Bearer Token 的内部接口：

```text
GET  /v1/format/profiles
GET  /v1/format/profiles/active
GET  /v1/format/profiles/detail?profile_id=...
POST /v1/format/profiles/initialize
POST /v1/format/profiles/create
POST /v1/format/profiles/update
POST /v1/format/profiles/delete
POST /v1/format/profiles/select
```

列表只返回模板元数据；活动模板和单次选择/保存响应返回当前有效 `format_config`。每个写操作使用单个 SQLite 事务，失败回滚后暴露稳定错误码。请求体不包含 owner，服务端不接受跨账号模板 ID。

`config_version` 继续表示当前 Core 格式兼容版本；用户模板自己的修改次数使用 `revision`，两者不得混用。Preview/Apply 命令仍只传现有 `format_config`，不向公网接口增加模板 ID 或模板名称。

## 配置生命周期

SQLite 是用户模板的唯一权威来源。TaskPane 在 Preview 或 Apply 提交前读取当前账号活动模板，取得不可变的本次 `format_config` 快照，再沿现有 HostBridge 链路提交。模板在任务运行期间被修改，不影响已经提交的任务。

`Application.PluginStorage` 不再长期保存权威 current/draft。它只作为旧版配置的一次性迁移来源和 WPS 窗口必要状态存储；格式 Dialog 的草稿保存在当前窗口内存中。

首次为某账号初始化模板状态时：

1. TaskPane 读取旧版 PluginStorage current envelope，并把其中有效配置作为可选迁移输入提交给本机初始化接口。
2. 有有效旧配置时，事务内创建“我的格式”并设为活动模板；没有旧配置时使用系统默认。
3. 事务成功后才清除旧 current、draft 和 revision；失败时保留旧数据供下次重试。
4. `legacy_migrated` 保证每个账号最多迁移一次。没有 owner 的旧配置只归属于升级后第一个成功迁移它的登录账号，不能复制给后续账号。

页面中的 `lines_per_page`、`chars_per_line`、`grid_alignment`、`space_before_line` 和 `space_after_line` 虽不显示，仍随完整 `config_json` 保存并送入 Core。

## 请求链路

1. Preview 提交前读取活动模板，把同一份配置放入本地通信桥命令；Host Runtime 调用 `/v1/recognize` 时传给现有识别入口。
2. Apply 提交前读取活动模板并提交给本地 `/v1/bridge/command`。Control Server 先按现有流程请求公网授权，再校验并绑定该请求配置；后续 `/v1/format/prepare` 只读取已绑定配置。
3. 公网授权返回的配置和版本仍作为授权与兼容基线；当前经过校验的本地用户配置沿用现有 `requested_format_config` 路径，不改变公开协议。

## UI 与交互

TaskPane 只保留“格式设置”入口。点击后使用可信同源静态地址调用 `Application.ShowDialog()`，不隐藏 TaskPane，不创建第二个 TaskPane、浏览器窗口、PySide2 窗口或 Win32 窗口。

Dialog 顶部增加模板管理区：

```text
模板：[系统默认 / 用户模板 select]  [添加模板] [删除模板]
模板名称：[输入框]
```

- 打开 Dialog 时选择当前活动模板并加载其完整配置。
- 切换 `select` 前若存在未保存修改，使用中文确认是否放弃；确认后加载目标模板。
- “添加模板”复制当前界面配置，建立未持久化新草稿，清空并聚焦模板名称；只有点击“保存设置”才插入数据库。
- 用户模板名称和内容均可编辑；“保存设置”原子保存名称和内容，并把该模板设为活动模板。
- 系统默认名称只读且删除按钮禁用；如需修改，先添加为用户模板。
- 删除用户模板前中文确认；删除活动模板后切回系统默认并刷新界面。
- “恢复默认”只把当前草稿内容恢复为系统默认，不修改模板名称、不立即保存。
- 取消或关闭窗口丢弃未保存草稿，不生成空模板或无名模板。

页面继续使用无系统标题栏的自绘 Header、圆形关闭按钮、滚动内容区和固定 Footer；段落样式、页面版式、字符设置和页码设置现有布局不变。

## 校验、诊断与兼容

模板名称压缩首尾和连续空白，不能为空，最长 80 个字符。所有配置写入和读取均通过现有 Core `validate_format_config()`；不在 WPS 端复制格式规则。稳定错误码包括：

```text
WPS_FORMAT_PROFILE_ACCOUNT_REQUIRED
WPS_FORMAT_PROFILE_NAME_REQUIRED
WPS_FORMAT_PROFILE_NAME_TOO_LONG
WPS_FORMAT_PROFILE_NAME_CONFLICT
WPS_FORMAT_PROFILE_NOT_FOUND
WPS_FORMAT_PROFILE_SYSTEM_LOCKED
WPS_FORMAT_PROFILE_CONFIG_INVALID
WPS_FORMAT_PROFILE_DATABASE_FAILED
WPS_FORMAT_PROFILE_MIGRATION_FAILED
```

日志只记录阶段、模板短 ID、revision、计数、耗时和错误码，不记录模板名称、完整配置、owner 全值、路径或凭据。版本保持 5.4。

## 测试与验收

- SQLite：同账号增删改查、名称唯一、活动模板切换、事务回滚和数据库不存在时初始化。
- 账号：不同账号隔离、同名允许、账号清除后模板保留、同账号重新登录恢复。
- 迁移：旧 current 只迁移一次，成功后清理，失败时保留，后续账号不继承。
- Control：回环鉴权、owner 由运行时绑定、非法配置和跨账号模板 ID 失败。
- UI：select 切换、添加草稿、自定义名称、重命名、删除确认、系统默认保护、脏草稿确认和取消不写入。
- 链路：Preview 与 Apply 使用同一活动模板快照，公网授权、Recognition 和 Engine 行为不变。

运行 WPS 模板存储和 Control 聚焦 Python 测试、`node --test apps/wps/tests/format-settings.test.mjs apps/wps/tests/wps-runtime.test.mjs`、Ruff、compileall、`git diff --check` 和 `apps/wps/scripts/verify.ps1`。不自动构建 EXE。真实 WPS 未执行时报告：

```text
REAL_WPS_FORMAT_PROFILE_SMOKE = NOT_RUN
```

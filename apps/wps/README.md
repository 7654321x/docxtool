# DocxTool WPS App

`apps/wps` 是 DocxTool 的 WPS 外围应用。它负责 WPS 宿主交互，但不维护第二套识别、规范化或排版引擎。

## 架构边界

```text
main.py 固定 127.0.0.1:3889 静态服务 → index.html（极薄启动壳，只加载 main.js）
        ↓
main.js（同步 bootstrap）
        ↓
bootstrap-log.js → runtime-config.js → host-runtime.js → ribbon.js
        ↓
WPS Ribbon / TaskPane
        ↓
HostBridge 单命令槽 + 25 秒异步长请求
        ↓
127.0.0.1 随机 loopback Control Server
        ↓
src/docxtool
Importer → Segmenter → Recognition(authoritative) → Normalizer → Engine
        ↓
validate_docx_integrity
```

`apps/wps` 可以调用 `src/docxtool`，但 `src/docxtool` 不得反向依赖 WPS。

项目根 `index.html` 只负责加载 `main.js`，真正的 bootstrap 顺序仍由 `main.js` 单一负责。`main.py` 使用本机静态服务发布这些文件，并更新当前项目的 WPS 加载项注册，不依赖 `wpsjs debug` 自动拉起 WPS。

关键 bootstrap 使用经典同步脚本加载。WPS 会在加载项装载阶段解析 Ribbon 回调，因此 `host-runtime.js` 必须先于 `ribbon.js` 完成执行，确保 `OnAddinLoad` 被调用时 Host Runtime 已可用。Host 与 TaskPane 各保持一个 Control Server 异步长请求：TaskPane 将命令写入单槽，Host 领取后复用现有业务流程并发布递增 revision 的状态。空闲时不轮询 WPS API；PluginStorage 只保存任务窗格 ID、页面版本和预览批注元数据，旧格式设置仅在本地模板库首次初始化时迁移一次。

## 已迁移能力

- Ribbon：预览排版、一键排版、清除预览、状态面板、本机检测
- TaskPane：识别结果、宿主绑定状态、兼容性提示、执行状态、格式设置入口、关闭面板
- 格式设置：点击 TaskPane 按钮后由 WPS `Application.ShowDialog` 打开中央 WebDialog；TaskPane 主面板保持可见。Dialog 提供模板 `select`、添加模板、删除模板和可编辑模板名称，模板内容保存在 `%LOCALAPPDATA%\DocxTool\wps\format_profiles.db`，按登录账号隔离；预览和一键排版提交前读取当前活动模板。
- 当前 WPS DOCX 保存完成确认、关闭、重新打开确认
- authoritative 识别预览
- `HostSnapshot -> bind_recognition_plan()` 正式 SDK 宿主绑定
- 只有 Binder 返回 `confirmed + verify_host_range` 的识别块才创建 WPS 预览批注
- 创建 Range 前后再次验证宿主段落 raw hash 和 raw fragment hash
- 预览 session 按文档 identity 隔离，切换文档不会覆盖其他文档的批注跟踪状态
- DocxTool 完整 Engine 正式排版
- 临时输出 → 关闭原文档 → 原子替换 → 重开确认 → 删除备份
- 失败 rollback；同一时刻只允许一个正式排版事务
- 排版事务写入短期 runtime journal；Control Server 重启会恢复未完成的 prepare/commit
- Loopback Control Server 默认使用系统分配的空闲端口
- DocxTool 统一日志格式与文档 context log
- Engine `compatibility_warnings` 原样脱敏后显示在任务窗格

旧 `wps--plugin` 中以下能力不迁移：

- `LocalFormatCommandGenerator`
- `WpsApiDocumentExecutor` 正式排版职责
- paragraph/section Formatting Contract
- WPS 自己的 structural normalization
- WPS 自己实现的 source locator / 重复段落消歧 / canonical text 绑定
- 旧 9528 / local-agent / command-service 路径
- 为第二套格式执行服务的 Worker / Broker 链

## 预览流程

```text
保存当前 DOCX 并等待 WPS Saved=true
        ↓
DocxTool recognize_docx(authoritative)
        ↓
RecognitionPlan
        ↓
从当前 WPS 文档采集 HostSnapshot
        ↓
DocxTool bind_recognition_plan
        ↓
confirmed + verify_host_range
        ↓
再次校验 paragraph/fragment raw hash
        ↓
创建预览批注
```

`review + preview_only` 会在完整 Range 校验通过后创建明确标注“建议人工复核”的批注；`unresolved + skip` 不创建编辑器 Range，只在任务窗格中显示未定位结果。

HostSnapshot 原文只通过带短期 Bearer token 的 `127.0.0.1` Control Server 传给本机 DocxTool Binder，不写入日志。Control Server 对请求体保留 16 MiB 硬上限。

## 正式排版事务

```text
保存当前 DOCX并等待完成
        ↓
DocxTool Engine 输出临时 DOCX
        ↓
validate_docx_integrity
        ↓
记录 prepared journal
        ↓
WPS 关闭原文档
        ↓
确认源 SHA256 未变化
        ↓
备份 + 原子替换
        ↓
记录 committed journal
        ↓
WPS 重新打开并确认 ActiveDocument
        ↓
finalize 删除备份和 journal
```

如果替换后重新打开或 finalize 失败，WPS 会先关闭已打开的新文件，再请求 Python rollback，随后重新打开恢复后的原文件。若进程在中途退出，下一次 Control Server 启动会读取 `runtime/transaction-state.json` 并恢复未完成事务；恢复无法安全完成时直接报 `WPS_TRANSACTION_RECOVERY_REQUIRED`，不会静默继续。

WPS 一键排版在输出文档内使用内置快捷样式：正文为 `Normal`，一至四级标题分别为 `Heading1` 至 `Heading4`。这些是 OOXML 内部样式 ID，中文 WPS 顶部继续显示“正文、标题1、标题2、标题3、标题4”，不会新增英文快捷样式按钮。主标题、版头、落款、附件等特殊结构继续使用 DCT 样式；网页、SDK、CLI 和批处理入口也继续使用 DCT 样式。该行为只修改当前排版结果文档，不修改 WPS 全局模板；成功后结果保留，只有排版失败、取消或事务回滚时恢复原文档。详细设计见 [`../../docs/design/WPS_BUILTIN_STYLE_GALLERY_TECHNICAL_DESIGN.md`](../../docs/design/WPS_BUILTIN_STYLE_GALLERY_TECHNICAL_DESIGN.md)。

任务窗格的“排版范围”可选择全文或指定排版前页码，页码支持 `3`、`3-5`、`3,5,8-10`。WPS 在排版开始前固定原始页边界和对应物理段落，跨页段落整体纳入；后续排版改变分页时不重新计算。完整 DOCX 仍由本机读取以保留范围外内容，但只有指定范围对应的源物理段进入逻辑拆分、识别、规范化和排版，范围外段落、表格、样式、原生编号和页面设置原样保留。局部排版不执行全局版头、页码、页面设置、全文清理或尾部重排。

任务窗格的“添加版头”单独读取当前版头并填写发文机关标志、发文字号、可选签发人和分割线类型。确认后直接通过本机事务生成到当前文档，不执行全文识别、一键排版或公网授权；已有版头先中文确认替换，失败时恢复原文。当前只支持单机关发文；旧 `.doc/.wps` 打开表单时仅临时转换检查，真正添加时才生成同名 `.docx`。

## 日志

Python 和 WPS JavaScript 统一汇入 DocxTool logger。格式沿用 DocxTool：

```text
%(asctime)s [%(levelname)-5s] %(name)s | %(message)s
```

WPS 日志消息使用：

```text
[WPS][component] event | 中文说明 | key=value
```

运行日志位于：

```text
apps/wps/logs/
```

每次识别/排版使用 DocxTool `make_document_log_path + set_context_log_path` 创建独立文档日志。日志文件名固定使用通用 `document` 前缀，不包含源 DOCX 文件名；日志内容不写正文、完整路径、session token 或完整文件哈希，只记录脱敏 `file_id`。WPS JavaScript 的诊断事件通过短期 Bearer token POST 到本机 Control Server，再由同一个 `docx_tool` logger 写入。

## 本地使用

将整个 `apps/wps` 复制到 DocxTool 仓库根目录后：

```pwsh
pwsh -NoProfile -Command "cd apps/wps; npm install"
pwsh -NoProfile -Command "python apps/wps/main.py verify"
pwsh -NoProfile -Command "python apps/wps/main.py start"
```

用户只能通过 EXE 或 `python apps/wps/main.py start` 进入登录/注册流程。`start` 会先完成登录或注册；没有可用本地账号、账号损坏后取消登录，或关闭登录窗口时，不启动本地服务并移除本项目的 WPS 加载项注册。登录成功后才会为 Control Server 分配随机本机端口，启动固定为 `127.0.0.1:3889` 的插件网页服务，生成短期 `runtime/runtime-config.js`，并更新当前项目的 WPS 加载项注册。不得直接调用内部 `start(0)` 发布插件：账号数据库存在不表示当前 Control Server 已绑定 `AccountRuntime`。固定网页来源避免 WPS 因端口变化反复询问信任；若 `3889` 已被占用，启动器会先验证该监听者确实是 DocxTool WPS 旧服务，确认后自动停止并重试，非 DocxTool 占用仍直接报错，不回退到随机端口。插件网页响应禁止缓存，避免 WPS 跨会话继续加载旧版 Bootstrap、Host 或 TaskPane。它不会自动打开或关闭 WPS；服务就绪后按需打开 WPS 文字即可。运行结束后会删除包含 session token 的 runtime config。
若启动前 WPS 已经打开并缓存了旧任务窗格，自动停止旧 Python 服务也不能强行卸载当前 WPS 页面；请关闭 WPS 后重新打开。未登录期间不会重新发布本项目加载项。

独立登录注册窗口使用 `PySide2 5.15.2.1 + Qt Widgets + QSS`，通过布局和 Qt 5 高 DPI 属性适配 Windows 7 SP1、8.1、10 和 11。每次启动都先显示登录窗口；“记住密码”允许使用 Windows DPAPI 保存并回填密码，“自动登录”同时启用记住密码，但只表示窗口显示后自动触发一次与用户点击“登录”相同的提交流程，不会绕过窗口或在后台直接复用会话。自动登录失败时窗口保持打开，用户可以修改后手动登录；登录成功前不启动本地服务、不注册 WPS 加载项。登录成功后可从系统托盘进入“登录与账号设置”，双击托盘或再次运行程序也会打开设置。取消记住密码会清除密码密文并关闭自动登录。“开机自启”是独立开关，写入当前用户启动项，不需要管理员权限；开机启动后仍先显示登录窗口。账号、会话和设备密钥继续保存在 `%LOCALAPPDATA%\DocxTool\wps\account.db`；一键排版每次执行前必须重新取得公网授权。

只测试 Python Control Server：

```pwsh
pwsh -NoProfile -Command "python apps/wps/main.py control"
```

构建用户端无控制台 GUI 单文件 EXE：

```pwsh
pwsh -NoProfile -File apps/wps/scripts/build-exe.ps1 -ServerOrigin https://wps.example.com
```

生产构建只接受不带路径的 HTTPS Origin。脚本固定 PyInstaller 6.22.0，生成 `dist/wps/DocxToolWps.exe`，并自动从仓库外目录执行冻结态 `verify`。源码 `client-config.json` 继续使用本机开发地址，正式 Origin 只在构建时注入。模板数据库保持在用户本机数据目录，不进入 EXE 或发布包。

## 验证

推荐直接运行统一门禁：

```pwsh
pwsh -NoProfile -File apps/wps/scripts/verify.ps1
```

它依次执行：

```text
python apps/wps/main.py verify
python -m pytest apps/wps/tests -q
node --check apps/wps/main.js
node --check apps/wps/js/bootstrap-log.js
node --check apps/wps/js/bootstrap-complete.js
node --check apps/wps/js/ribbon.js
node --check apps/wps/host-runtime.js
node --check apps/wps/taskpane.js
manifest.xml / ribbon.xml XML 解析
package.json JSON 解析
```

仓库 GitHub CI 也执行 WPS Python 测试、JavaScript 语法检查和 XML/JSON 解析。这些门禁只能证明源码、事务与接口边界。必须在真实 WPS 中完成“预览批注 → 切换文档 → 清除预览 → 一键排版 → 自动重开 → rollback 演练 → DOCX/视觉对照”后，才能标记真实宿主 PASS。

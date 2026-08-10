# WPS App Rules

本文件只约束 `apps/wps/`。

1. WPS 是 DocxTool 的外围应用，不是第二套文档引擎。
2. `apps/wps` 可以调用 `src/docxtool` 的公开能力；`src/docxtool` 不得依赖、导入或判断 WPS。
3. WPS 专属代码只负责 Ribbon、任务窗格、宿主生命周期、本地控制、预览交互和诊断。
4. 禁止在 WPS 目录复制识别规则、规范化规则、格式 profile、编号规则、字体规则或正式排版 Engine。
5. 正式排版必须走 `DocxImporter -> Recognition(authoritative) -> Normalization -> Engine -> validate_docx_integrity`。
6. 正式排版失败时不得 fallback 到 WPS API 第二套格式写入；保持原文件不变并暴露真实错误。
7. 排版必须先写临时 DOCX；WPS 关闭原文档后才允许事务替换，重新打开成功后再删除备份。事务状态必须写入本地 runtime journal，Control Server 重启时恢复未完成替换。
8. 预览默认只读，不写正式格式。需要文档批注时应作为独立宿主交互能力实现，不改变识别/排版规则。
9. 预览定位必须使用 `HostSnapshot -> bind_recognition_plan()`。禁止直接把 DOCX `physical_paragraph_index` 当作 WPS `Paragraphs.Item()` 下标，也禁止在 WPS 端重新实现 source locator、重复段落消歧或 canonical text 绑定。
10. 预览批注允许使用 SDK Binder 返回的 `confirmed + verify_host_range` 和 `review + preview_only`；两者创建和读回 Range 时都必须再次验证 Binder precondition 中的段落 raw hash 与 fragment raw hash，`review` 批注必须明确提示人工复核且不得用于正式格式写入。`unresolved + skip` 始终禁止创建 Range 或批注。
11. 调用识别或正式排版前必须等待 WPS `Document.Save()` 真正完成；不能在 `Save()` 返回后立即让 Python 读取磁盘文件。
12. 预览批注跟踪状态按文档 identity 隔离，切换文档不得覆盖另一文档的 preview session。
13. Python 日志复用 DocxTool `docx_tool` logger、`LOG_FORMAT`、文档 context log；JS 日志通过本地 Control Server 汇入相同格式。
14. 日志不得记录正文、完整绝对路径、session token 或完整文件哈希；日志文件名使用通用 `document` 前缀，路径使用脱敏 `file_id`。为区分 WPS 多文档窗口，业务命令日志允许记录 `Application.ActiveDocument.Name` 产生的 `document_name`，但不得记录 `FullName` 或从路径推导额外目录信息。
15. Windows 显式命令使用 PowerShell 7：`pwsh -NoProfile -Command "..."`。
16. 修改后至少运行 `python apps/wps/main.py verify`、`python -m pytest apps/wps/tests -q`、JavaScript 语法检查和 XML/JSON 解析；这些门禁必须进入仓库 CI。没有真实 WPS 验证时不得声称真实宿主 PASS。
17. WPS 业务命令统一经 Control Server 的单个 `CommandMonitor` 线程串行执行；HTTP 日志接收和健康检查不占用业务命令槽。WPS 的 `Application`、`Document`、`Range` 和 `Comments` 操作只在 Host Runtime 中执行，Python 监控线程不得直接调用 WPS 对象。
18. Launcher 使用锁定版本 `wpsjs 2.2.3` 的官方 `wpsjs debug` 启动契约。启动前只检测拥有可见顶层窗口的 `wps.exe`（WPS 文字主窗口）；传输助手、云服务及无窗口后台 `wps.exe` 不得阻止启动。检测到可见 WPS 文字窗口时记录 `WPS_RESTART_REQUIRED` 并要求用户关闭后重启，不得杀死用户进程，也不得增加热重连、会话恢复或第二通信通道。Control 日志和事务产物必须位于插件源码监听目录之外。
19. Host 启动时清空旧 PluginStorage 请求槽和旧状态，再发布唯一 `host_ready=true`。TaskPane 只在该状态成立时写入 `wps-request-v2` 单槽请求；忙碌、Host 未就绪、请求 JSON 无效、协议无效、缺少请求 ID、缺少命令和重复请求必须分别使用独立事件与错误码。
20. 日志必须在真实失败源头记录具体事件，顶层 `host.command.failed`、`monitor.command.failed` 和 Control 请求失败只作关联汇总。保存调用、保存等待、文档路径、HostSnapshot、SDK Binding、Range 各项前置条件、批注创建/回滚、排版阶段和事务状态转换不得用同一个通用错误事件替代。
21. Python 与 JS 日志统一只允许阶段、状态、耗时、计数、稳定错误码、脱敏短 ID，以及第 14 条限定的 `document_name`。正文、绝对路径、Token、Authorization、原始快照、Range 文字、完整哈希和 traceback 不得进入日志；`/v1/log` 及其 OPTIONS 不生成普通请求/access 日志，日志传输失败只在当前 JS 上下文输出一次脱敏错误。
22. `OnAddinLoad` 是 Host Runtime 的首选启动入口；若 WPS 复用无窗口后台宿主而未触发该回调，首次点击“状态面板”必须在 WPS 主线程中幂等调用同一个 `HostRuntime.start()` 后再创建 TaskPane。WPS 创建或复用任务窗格后可能重新加载主 Bootstrap，新 Bootstrap 完成时必须再次调用同一个幂等 `HostRuntime.start()`，恢复当前页面上下文的唯一请求轮询器；必须分别记录 `bootstrap.host_start.enter/completed/failed`、Host 实例短 ID 和唯一的 `host.poll.first_tick`。`CreateTaskPane` 按锁定版本官方模板只传 URL。其他 Ribbon 业务命令不得借此隐式启动 Host，也不得增加第二套状态、通信通道、重试或热重连。该场景必须运行 `node --test apps/wps/tests/wps-runtime.test.mjs`。
23. 触发场景：WPS“一键排版”没有传入格式配置时，必须使用 `structural` 处理并默认启用现有 Core 序号规范和安全标点；已识别的一至四级标题按层级重建可见序号，URL、邮箱、版本号等技术片段由 Core 安全标点引擎保护，不得在 WPS 端复制编号或标点算法。调用方显式传入配置时保持其 `numbering.enabled` 和 `punctuation.enabled` 原意。配置完成日志必须记录实际处理模式、编号开关和安全标点开关。修改后运行 `apps/wps/tests/test_wps_app.py` 中的一键排版编号、安全标点回归，以及 `tests/test_processing_flags.py tests/test_punctuation_engine.py`。
24. 触发场景：正式排版替换当前唯一文档时，不能先关闭该文档再依赖同一 Host 页面调用 `Documents.Open()`；关闭唯一文档会销毁加载项上下文。必须先用 `Document.SaveAs2()` 切换到唯一桥接 DOCX，由桥接文档保持 Host，提交源文件替换并通过 `Documents.Open()` 重开源文档后，再关闭桥接文档并用 `FileSystem.unlinkSync()` 删除。失败回滚同样必须在源文档恢复后清理桥接文件。修改后运行 `node --test apps/wps/tests/wps-runtime.test.mjs`。
25. WPS `customUI` 的 `<tab>` 不支持 `onAction`，不能依赖点击自定义页签直接执行代码。需要精简 Ribbon 时保留一个明确的 TaskPane `<button onAction>` 入口，预览、排版、清除和检测等业务操作放在侧边栏中；不得向 `<tab>` 添加非官方点击回调。修改后解析 `ribbon.xml` 并运行 WPS JS Runtime 测试。
26. 触发场景：WPS 当前活动文档是旧版 `.doc` 或 `.wps` 时，`预览排版`和`一键排版`必须在同一个 Host 前置入口中静默永久升级为同名 `.docx`；`本机检测`不得触发升级，`清除预览`在旧格式上直接成功返回 0。升级只允许由 WPS Host 对隐藏临时文件调用一次 `Document.SaveAs2(path, 12)`；预览原样发布转换结果后继续现有 SDK 识别与 Binding，排版复用该转换桥接文件进入现有 Core 事务。同名 `.docx` 已存在时必须在转换前停止且不得覆盖；旧源内容在新 DOCX 重开成功前必须保留于事务备份，任一失败都恢复旧源文件。不得只修改扩展名，不得在 Python 中解析旧格式，也不得建立第二套识别或排版链。日志按 `document.format.*`、`document.upgrade.*` 分阶段记录，修改后运行 `apps/wps/tests/test_wps_app.py` 的 legacy upgrade 测试及 `node --test apps/wps/tests/wps-runtime.test.mjs`。

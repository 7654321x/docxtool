# WPS App Rules

本文件只约束 `apps/wps/` 的跨任务架构和安全边界。具体故障场景、诊断码和回归命令统一见 [`../../docs/WPS_REGRESSION_CHECKLIST.md`](../../docs/WPS_REGRESSION_CHECKLIST.md)。

1. WPS 是 DocxTool 的外围应用，不是第二套文档引擎。
2. `apps/wps` 可以调用 `src/docxtool` 的公开能力；`src/docxtool` 不得依赖、导入或判断 WPS。
3. WPS 专属代码只负责 Ribbon、任务窗格、宿主生命周期、本地控制、预览交互和诊断。
4. 禁止在 WPS 目录复制识别、规范化、格式 profile、编号、字体或正式排版 Engine。
5. 正式排版必须走 `DocxImporter → Recognition → Normalization → Engine → validate_docx_integrity`。
6. 正式排版失败时不得 fallback 到 WPS API 第二套格式写入；原文件必须保持不变并暴露真实错误。
7. 排版必须先写临时 DOCX，并通过本地事务 journal 管理关闭、替换、重开、提交、回滚和恢复。
8. 预览默认只读；定位必须使用 `HostSnapshot → bind_recognition_plan()`，不得把 DOCX 物理段落序号直接当作 WPS 段落下标。
9. WPS `Application`、`Document`、`Range` 和 `Comments` 只能在 Host Runtime 中操作，Python 监控线程不得直接调用 WPS 对象。
10. WPS 业务命令统一经 Control Server 的单个 `CommandMonitor` 串行执行；Host 与 TaskPane 使用单槽长请求，禁止恢复 PluginStorage 命令轮询。
11. 新 Host generation 必须使旧 Host、旧命令和旧 TaskPane 状态等待失效；协议状态值保持 `READY/RUNNING/PASS/FAIL`，展示层使用中文。
12. 日志必须阶段化、脱敏并使用稳定错误码；不得记录正文、完整路径、Token、Authorization、原始快照或完整哈希。
13. 启动器每次先完成登录窗口流程；登录成功前不创建 AccountRuntime、Control Server、静态服务或加载项注册。
14. 自动登录只能在登录窗口已经显示后触发与用户点击“登录”相同的提交函数，不得后台复用会话或跳过窗口。
15. 端口冲突只允许确认占用者是本项目旧服务后自动停止并重试；其他进程不得自动结束，也不得回退随机端口。
16. WPS 一键排版继续使用现有 Core、Recognition、Normalization、Engine 和公网授权链，不在 WPS 端复制算法。
17. WPS 一键排版固定传入 `style_profile=wps_docxtool`：正文和一至四级标题使用 `DCT-*` 自定义样式，不改写 OOXML 内置 `Normal`、`Heading1`—`Heading4`，使 WPS“清除格式”可恢复内置正文样式。
18. WPS 指定页码范围必须在保存、转换和 Engine 调用前按原始分页固定；范围外内容原样复制，不能改写全局页面设置、版头或尾部顺序。
19. “添加版头”必须走独立文档事务，不调用 Recognition、一键排版或公网授权；当前界面只支持单机关。
20. 默认只运行相关源码测试和 `apps/wps/scripts/verify.ps1`，不自动构建 EXE。真实 WPS 未验证时必须报告对应 `*_SMOKE = NOT_RUN`。
21. 修改 TaskPane HTML、CSS 或 Reader/TaskPane 脚本后，必须同步递增静态资源查询版本；需要强制 WPS 放弃旧窗格时还必须递增 `TASKPANE_PAGE_VERSION`，并运行 `node --test apps/wps/tests/run-node-tests.mjs`。仅关闭再打开旧窗格不等于重新加载页面。
22. WPS“格式设置”只显示段落样式、页面版式、字符设置和页码设置四类；`lines_per_page`、`chars_per_line`、`grid_alignment`、`space_before_line`、`space_after_line` 虽隐藏于界面仍必须保留。多个自定义模板保存在独立的本机 SQLite `format_profiles.db`，按登录账号稳定 `user_id` 隔离；系统默认模板不可删除或重命名，账号清除不得删除用户模板。预览与一键排版必须在提交前读取同一份活动模板配置；修改后运行 WPS Node 聚焦测试、`python -m ruff check`、编译检查和 `git diff --check`。

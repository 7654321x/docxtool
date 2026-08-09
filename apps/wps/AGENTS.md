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
10. 只有 SDK Binder 返回 `binding_status=confirmed` 且 `recommended_action=verify_host_range` 的块允许创建预览 Range；创建和读回 Range 时再次验证 Binder precondition 中的段落 raw hash 与 fragment raw hash。
11. 调用识别或正式排版前必须等待 WPS `Document.Save()` 真正完成；不能在 `Save()` 返回后立即让 Python 读取磁盘文件。
12. 预览批注跟踪状态按文档 identity 隔离，切换文档不得覆盖另一文档的 preview session。
13. Python 日志复用 DocxTool `docx_tool` logger、`LOG_FORMAT`、文档 context log；JS 日志通过本地 Control Server 汇入相同格式。
14. 日志不得记录正文、完整绝对路径、session token、源文件名或完整文件哈希；日志文件名使用通用 `document` 前缀，路径使用脱敏 `file_id`。
15. Windows 显式命令使用 PowerShell 7：`pwsh -NoProfile -Command "..."`。
16. 修改后至少运行 `python apps/wps/main.py verify`、`python -m pytest apps/wps/tests -q`、JavaScript 语法检查和 XML/JSON 解析；这些门禁必须进入仓库 CI。没有真实 WPS 验证时不得声称真实宿主 PASS。

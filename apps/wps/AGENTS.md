# WPS App Rules

本文件只约束 `apps/wps/`。

1. WPS 是 DocxTool 的外围应用，不是第二套文档引擎。
2. `apps/wps` 可以调用 `src/docxtool` 的公开能力；`src/docxtool` 不得依赖、导入或判断 WPS。
3. WPS 专属代码只负责 Ribbon、任务窗格、宿主生命周期、本地控制、预览交互和诊断。
4. 禁止在 WPS 目录复制识别规则、规范化规则、格式 profile、编号规则、字体规则或正式排版 Engine。
5. 正式排版必须走 `DocxImporter -> Recognition(authoritative) -> Normalization -> Engine -> validate_docx_integrity`。
6. 正式排版失败时不得 fallback 到 WPS API 第二套格式写入；保持原文件不变并暴露真实错误。
7. 排版必须先写临时 DOCX；WPS 关闭原文档后才允许事务替换，重新打开成功后再删除备份。
8. 预览默认只读，不写正式格式。需要文档批注时应作为独立宿主交互能力实现，不改变识别/排版规则。
9. Python 日志复用 DocxTool `docx_tool` logger、`LOG_FORMAT`、文档 context log；JS 日志通过本地 Control Server 汇入相同格式。
10. 日志不得记录正文、完整绝对路径、session token 或完整文件哈希；路径使用脱敏 `file_id`。
11. Windows 显式命令使用 PowerShell 7：`pwsh -NoProfile -Command "..."`。
12. 修改后至少运行 `python apps/wps/main.py verify`、WPS Python 测试和 JavaScript 语法检查；没有真实 WPS 验证时不得声称真实宿主 PASS。

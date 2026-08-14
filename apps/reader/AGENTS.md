# Reader App Rules

本文件只约束 `apps/reader/` 的本地 TXT Reader。

1. Reader 是完全本地的阅读功能，不接入公网账号、排版授权、Recognition、Normalization、Engine、HostBridge 或 WPS 文档事务。
2. Reader 业务入口为 `apps/reader/ReaderService`；WPS `reader_routes.py` 只验证本机请求并调用该服务，不直接操作 SQLite。
3. TXT 正文只保存到用户本地 Reader 数据目录；SQLite 只保存书籍元数据、章节、进度和设置。
4. 日志、错误、发布文件和诊断不得包含正文、书名、原始文件名、绝对路径或 Token。
5. TaskPane 只通过 `/v1/reader/*` 有界接口读取内容；不得新增正文全文接口或公网同步。
6. 自动滚动使用 `requestAnimationFrame` 和真实时间差；切换、隐藏、人工滚动、折叠和关闭时暂停并保存进度。
7. Reader UI 资源使用仓库内 SVG/QSS，不使用 Emoji、第三方图标库或 Windows 10/11 专属 UI API。
8. 修改后至少运行 Reader Python 测试、`apps/wps/tests/test_reader_routes.py` 和 Reader/WPS Node 测试。

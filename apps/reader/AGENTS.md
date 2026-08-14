# Reader App Rules

本文件只约束 `apps/reader/` 的本地 TXT Reader。

1. Reader 是完全本地的阅读功能，不接入公网账号、排版授权、Recognition、Normalization、Engine、HostBridge 或 WPS 文档事务。
2. Reader 业务入口为 `apps/reader/ReaderService`；WPS `reader_routes.py` 只验证本机请求并调用该服务，不直接操作 SQLite。
3. TXT 正文只保存到用户本地 Reader 数据目录；SQLite 只保存书籍元数据、章节、进度和设置。
4. 日志、错误、发布文件和诊断不得包含正文、书名、原始文件名、绝对路径或 Token。
5. TaskPane 只通过 `/v1/reader/*` 有界接口读取内容；不得新增正文全文接口或公网同步。
6. 自动滚动使用 `requestAnimationFrame` 和真实时间差；切换、隐藏、人工滚动、折叠和关闭时暂停并保存进度。
7. Reader UI 资源使用仓库内 SVG/QSS，不使用 Emoji、第三方图标库或 Windows 10/11 专属 UI API。
8. 阅读进度的 `text_offset` 与 `scroll_ratio` 都表示规范化后整本 TXT 的全局位置；章节索引末章 `end_offset` 是进度总长度，前端不得把有界内容块比例直接持久化。
9. 段落定义为规范化换行后的每个非空逻辑文本行；连续空行不产生段落。WPS Reader 的“上一页/下一页”按实际阅读视口翻页，距离为视口高度减一行高度，保留一行上下文；到达有界窗口边缘时才加载相邻窗口。`/v1/reader/navigate` 保留为内部兼容接口，但页面翻页不得再用字符比例猜测视口位置。
10. 删除采用“托管正文改名 → SQLite 元数据删除 → 临时文件清理”顺序：数据库失败必须暴露原错误并报告回滚失败；数据库已提交后的清理失败只能记录 `reader.book.delete.cleanup_failed` 并保持删除成功。
11. 多字段阅读设置必须通过一个 SQLite 事务原子写入。当前 Reader 使用整本 UTF-8 文本读取；字符 offset 无法直接安全映射到字节 offset，本轮有界读取评估为 `DEFERRED`，不得用错误的 `seek(character_offset)` 假装修复。
12. 修改后至少运行 Reader Python 测试、`apps/wps/tests/test_reader_routes.py` 和 Reader/WPS Node 测试。
13. 阅读进度必须以当前视口实际可见正文位置计算，`text_offset` 与 `scroll_ratio` 表示整本 TXT 的全局位置；界面百分比固定显示两位小数。自动播放按实际行高逐行滚动，窗口或章节结束时自动加载后续内容，只有整本书末尾才停止。修改后至少运行 `apps/wps/tests/reader-ui.test.mjs`。

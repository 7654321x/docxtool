# DocxTool WPS App

`apps/wps` 是 DocxTool 的 WPS 外围应用。它负责 WPS 宿主交互，但不维护第二套识别、规范化或排版引擎。

## 架构边界

```text
WPS Ribbon / TaskPane
        ↓
apps/wps/main.js
        ↓
127.0.0.1 随机 loopback Control Server
        ↓
src/docxtool
Importer → Segmenter → Recognition(authoritative) → Normalizer → Engine
        ↓
validate_docx_integrity
```

`apps/wps` 可以调用 `src/docxtool`，但 `src/docxtool` 不得反向依赖 WPS。

## 已迁移能力

- Ribbon：预览排版、一键排版、清除预览、状态面板、本机检测
- TaskPane：识别结果、复核状态、执行状态、返回文档、关闭面板
- 当前 WPS DOCX 保存、关闭、重新打开
- authoritative 识别预览
- 基于 DocxTool 已验证 source locator 的 WPS 预览批注；不生成第二套格式命令
- DocxTool 完整 Engine 正式排版
- 临时输出 → 关闭原文档 → 原子替换 → 重开确认 → 删除备份
- 失败 rollback；同一时刻只允许一个正式排版事务
- Loopback Control Server 默认使用系统分配的空闲端口
- DocxTool 统一日志格式与文档 context log

旧 `wps--plugin` 中以下能力不迁移：

- `LocalFormatCommandGenerator`
- `WpsApiDocumentExecutor` 正式排版职责
- paragraph/section Formatting Contract
- WPS 自己的 structural normalization
- 旧 9528 / local-agent / command-service 路径
- 为第二套格式执行服务的 Worker / Broker 链

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

每次识别/排版另外使用 DocxTool `make_document_log_path + set_context_log_path` 创建独立文档日志。日志不写正文、完整路径、session token 或完整文件哈希。WPS JavaScript 的诊断事件通过短期 Bearer token POST 到本机 Control Server，再由同一个 `docx_tool` logger 写入。

## 本地使用

将整个 `apps/wps` 复制到 DocxTool 仓库根目录后：

```pwsh
pwsh -NoProfile -Command "cd apps/wps; npm install"
pwsh -NoProfile -Command "python apps/wps/main.py verify"
pwsh -NoProfile -Command "python apps/wps/main.py start"
```

`start` 会先绑定 `127.0.0.1` 的空闲端口，再生成短期 `runtime/runtime-config.js`，最后调用固定版本的 `wpsjs` 加载插件。运行结束后会删除包含 session token 的 runtime config。

只测试 Python Control Server：

```pwsh
pwsh -NoProfile -Command "python apps/wps/main.py control"
```

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
node --check apps/wps/taskpane.js
manifest.xml / ribbon.xml XML 解析
package.json JSON 解析
```

这些门禁只能证明源码、事务与接口边界。必须在真实 WPS 中完成“预览批注 → 清除预览 → 一键排版 → 自动重开 → DOCX/视觉对照”后，才能标记真实宿主 PASS。

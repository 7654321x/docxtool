# DocxTool WPS App

`apps/wps` 是 DocxTool 的 WPS 外围应用。它负责 WPS 宿主交互，但不维护第二套识别、规范化或排版引擎。

## 架构边界

```text
WPS Ribbon / TaskPane
        ↓
apps/wps/main.js
        ↓
127.0.0.1 WPS Control Server
        ↓
src/docxtool
Importer → Segmenter → Recognition(authoritative) → Normalizer → Engine
        ↓
validate_docx_integrity
```

`apps/wps` 可以调用 `src/docxtool`，但 `src/docxtool` 不得反向依赖 WPS。

## 已迁移能力

- Ribbon：预览排版、一键排版、清除预览、状态面板、本机检测
- TaskPane：识别结果、复核状态、执行状态
- 当前 WPS DOCX 保存、关闭、重新打开
- authoritative 识别预览
- DocxTool 完整 Engine 正式排版
- 临时输出 → 关闭原文档 → 原子替换 → 重开确认 → 删除备份
- 失败 rollback，禁止 fallback 到旧 WPS 格式写入
- Loopback Control Server
- DocxTool 统一日志格式与文档 context log

旧 `wps--plugin` 中以下能力不迁移：

- `LocalFormatCommandGenerator`
- `WpsApiDocumentExecutor` 正式排版职责
- paragraph/section Formatting Contract
- WPS 自己的 structural normalization
- 旧 9528 / local-agent / command-service 路径

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

每次识别/排版另外使用 DocxTool `make_document_log_path + set_context_log_path` 创建独立文档日志。日志不写正文、完整路径、session token 或完整文件哈希。

## 本地使用

将整个 `apps/wps` 复制到 DocxTool 仓库根目录后：

```pwsh
pwsh -NoProfile -Command "cd apps/wps; npm install"
pwsh -NoProfile -Command "python apps/wps/main.py verify"
pwsh -NoProfile -Command "python apps/wps/main.py start"
```

`start` 会启动本地 Control Server，生成短期 `runtime/runtime-config.js`，再调用 `wpsjs debug -s` 加载 WPS 插件。运行结束后会删除包含 session token 的 runtime config。

只测试 Python Control Server：

```pwsh
pwsh -NoProfile -Command "python apps/wps/main.py control"
```

## 验证

基础门禁：

```pwsh
pwsh -NoProfile -Command "python apps/wps/main.py verify"
pwsh -NoProfile -Command "python -m pytest apps/wps/tests -q"
pwsh -NoProfile -Command "node --check apps/wps/main.js"
pwsh -NoProfile -Command "node --check apps/wps/taskpane.js"
```

这些门禁只能证明源码、事务与接口边界。必须在真实 WPS 中完成“预览 → 一键排版 → 自动重开 → DOCX/视觉对照”后，才能标记真实宿主 PASS。

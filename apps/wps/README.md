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
- TaskPane：识别结果、宿主绑定状态、兼容性提示、执行状态、返回文档、关闭面板
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

`review` 和 `unresolved` 绑定不会创建编辑器 Range，只在任务窗格中显示供复核。

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

仓库 GitHub CI 也执行 WPS Python 测试、JavaScript 语法检查和 XML/JSON 解析。这些门禁只能证明源码、事务与接口边界。必须在真实 WPS 中完成“预览批注 → 切换文档 → 清除预览 → 一键排版 → 自动重开 → rollback 演练 → DOCX/视觉对照”后，才能标记真实宿主 PASS。

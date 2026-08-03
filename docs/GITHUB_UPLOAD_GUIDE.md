# GitHub 上传和发布指南

本文说明如何把当前项目安全发布到 GitHub。它只记录仓库地址、上传范围和命令，不保存任何 SSH 私钥、令牌或真实生产密钥。

## 1. 目标仓库

```text
https://github.com/7654321x/docxtool.git
```

默认分支：

```text
main
```

本地项目路径：

```text
D:\PycharmProjects\docxtool
```

## 2. SSH 验证

验证本机 SSH key 是否能访问 GitHub：

```pwsh
pwsh -NoProfile -Command "ssh -T git@github.com"
```

正常结果类似：

```text
Hi 7654321x! You've successfully authenticated, but GitHub does not provide shell access.
```

检查目标仓库：

```pwsh
pwsh -NoProfile -Command "git ls-remote https://github.com/7654321x/docxtool.git refs/heads/main"
```

只允许把 `.pub` 公钥配置到 GitHub。不要把无扩展名私钥、`.pem`、`.key`、`ADMIN_TOKEN`、`PROXY_SECRET` 或 Cookie 写进仓库。

## 3. 当前发布范围

默认发布以下类型文件：

- 项目文档：`README.md`、`CHANGELOG.md`、`docs/README.md`、`docs/DEPLOY.md`、`docs/API.md`、`docs/SDK.md`、`docs/RECOGNITION_SOURCE_LOCATORS.md`、`docs/HOST_TEXT_V1_GOLDEN.json`、`docs/USER_WPS_VALIDATION.md`、`docs/USER_WPS_VALIDATION_RESULT.md`、`docs/RECOGNITION_ARCHITECTURE.md`、`docs/ARCHITECTURE_DAG.md`、`docs/RECOGNITION_RELEASE.md`、`docs/migration/README.md`、`docs/migration/codex-workflow.md`、`docs/migration/phase-a2-checklist.md`、`docs/migration/phase-a2-looper-log.md`、`docs/migration/phase-a3-final-looper-log.md`、`docs/migration/phase-b0-manifest.json`、`docs/migration/phase-b0-report.md`、`docs/UPLOAD_MANIFEST.md`、`docs/GITHUB_UPLOAD_GUIDE.md`、`公文格式规范.md`、`AGENTS.md`、`CONVENTIONS.md`
- 依赖和启动：`requirements.txt`、`requirements.lock`、`requirements-dev.lock`、`run.sh`、`run.ps1`
- 服务器代理模板：`deploy/nginx-docxtool.conf`
- 配置：`.env.example`、`.gitignore`、`.gitattributes`、`pytest.ini`、`ruff.toml`、`pyproject.toml`、`.github/workflows/ci.yml`
- 应用层：`src/docxtool/application/__init__.py`、`src/docxtool/application/process_document.py`
- 文档主链：`src/docxtool/document/pipeline/*.py`，承载处理模式、ParagraphData materialization 和 Importer 调用顺序；`document/importer.py` 保留兼容 facade
- 物理导入层：`src/docxtool/document/importing/__init__.py`、`src/docxtool/document/importing/images.py`、`src/docxtool/document/importing/inline_tokens.py`、`src/docxtool/document/importing/numbering.py`、`src/docxtool/document/importing/physical_format.py`、`src/docxtool/document/importing/reader.py`、`src/docxtool/document/importing/sections.py`
- 分段层：`src/docxtool/document/segmentation/*.py`，其中 `partition.py` 负责来源范围保序分区，`conservation.py` 负责无重叠、无丢失、无重复的守恒核验
- 旧识别隔离：`src/docxtool/document/recognition/legacy/__init__.py`、`classifier.py`、`pipeline.py`、`scoring.py`；Core 输入适配位于 `src/docxtool/document/recognition/core_adapter.py`
- Recognition 内部实现：`src/docxtool/document/recognition/providers/*.py`、`context/*.py`、`decoding/*.py`；旧 `candidates.py`、`global_context.py`、`decoder.py` 继续作为兼容入口
- Web 收口模块：`src/docxtool/web/bootstrap.py`、`runtime_state.py`、`compatibility.py`、`handler.py`；`web/app.py` 继续作为旧 import 和 monkeypatch 入口
- Engine 收口模块：`src/docxtool/document/engine/render_context.py`、`special_items.py`、`paragraph_renderer.py`、`export_finalize.py`、`export_pipeline.py`；`engine/core.py` 继续作为公开兼容入口
- 后端、排版核心和 SDK：`server.py`、`src/docxtool/**/*.py`、`src/docxtool/resources/config/default-format.json`、`src/docxtool/resources/schemas/*.json`，其中管理员请求上下文和 POST CSRF 辅助位于 `src/docxtool/web/admin_access.py`，管理员监控动作参数解析位于 `src/docxtool/web/admin_actions.py`，管理员监控动作处理位于 `src/docxtool/web/admin_route_handlers.py`，管理员 session 路由处理位于 `src/docxtool/web/admin_session_routes.py`，管理员表单解析位于 `src/docxtool/web/admin_forms.py`，管理员静态页面位于 `src/docxtool/web/admin_pages.py`，用户认证响应辅助位于 `src/docxtool/web/auth_payloads.py`，普通用户认证路由处理位于 `src/docxtool/web/auth_route_handlers.py`，Web 建表和迁移位于 `src/docxtool/web/database_schema.py`，文件 API 授权位于 `src/docxtool/web/file_api_auth.py`，前端首页读取位于 `src/docxtool/web/frontend_pages.py`，HTTP handler 路由动作分派位于 `src/docxtool/web/handler_dispatch.py`，HTTP handler 响应发送位于 `src/docxtool/web/handler_responses.py`，日志脱敏位于 `src/docxtool/web/log_redaction.py`，后台维护线程入口位于 `src/docxtool/web/maintenance.py`，监控页面局部渲染位于 `src/docxtool/web/monitoring_pages.py`，预设模板路由处理位于 `src/docxtool/web/preset_route_handlers.py`，请求参数合并位于 `src/docxtool/web/request_params.py`，响应编码和错误体辅助位于 `src/docxtool/web/responses.py`，兼容路由匹配位于 `src/docxtool/web/routing.py`，服务启动编排位于 `src/docxtool/web/server_runtime.py`，任务状态/下载/日志路由处理位于 `src/docxtool/web/task_route_handlers.py`，后台 worker 一次性启动、队列消费、内存处理中状态、子进程入口和超时清理位于 `src/docxtool/web/task_worker.py`；机械迁移门禁和阶段状态分别记录在 `docs/migration/codex-workflow.md`、`docs/migration/phase-a2-checklist.md`
- 监控首页和统计接口路由响应发送位于 `src/docxtool/web/monitor_route_handlers.py`；前端首页和管理员登录页路由响应发送位于 `src/docxtool/web/page_route_handlers.py`；健康检查路由响应发送位于 `src/docxtool/web/health_route_handlers.py`。
- 管理员监控仪表盘整页 HTML 渲染位于 `src/docxtool/web/monitor_dashboard_page.py`。
- HTTP handler 响应头、OPTIONS 和方法入口分派位于 `src/docxtool/web/handler_lifecycle.py`。
- 管理员、文件 API 和模板修改路由的鉴权转发位于 `src/docxtool/web/protected_route_handlers.py`。
- 管理员、文件 API 和 preset 修改路由的鉴权响应位于 `src/docxtool/web/route_authorization.py`。
- DOCX 上传限流、落盘、安全校验和任务入队编排位于 `src/docxtool/web/upload_route_handlers.py`。
- 已校验上传任务的 queued 记录和内存队列入队位于 `src/docxtool/web/task_queue.py`。
- 脚本：`scripts/generate_secrets.py`、`scripts/benchmark_recognition.py`、`scripts/compare_recognition_runs.py`、`scripts/analyze_end_format.py`、`scripts/analyze_letterhead_batch.py`、`scripts/batch_test_docx.py`、`scripts/generate_005_format_fixtures.py`、`scripts/normalize_correct_template_role_spacing.py`、`scripts/phase_a_equivalence_snapshot.py`、`scripts/phase_a_web_contract_snapshot.py`、`scripts/migrate_legacy_database.ps1`、`scripts/publish_to_github.ps1`
- 前端和 Cloudflare Pages：`resources/frontend/pages/index.html`、`resources/frontend/pages/_worker.js`
- 运行目录占位：`var/data/.gitkeep`、`var/logs/.gitkeep`、`var/outputs/.gitkeep`、`var/runtime/.gitkeep`
- 测试：`tests/test_*.py`、`tests/*.test.mjs`

当前唯一生产前端源入口是 `resources/frontend/pages/index.html`。重构前的旧前端入口和 legacy 页面已移除。

旧 PyQt 桌面端文件已移除；当前发布范围只保留 Web 服务新架构。

## 4. 绝对不要上传

以下内容不得提交或发布：

- `.env` 和 `.env.*`，但保留 `.env.example`
- 真实密钥、令牌、Cookie、Authorization 请求头
- SSH 私钥、证书私钥、`.pem`、`.key`
- `stats.db`、`var/data/*.db`、`*.db`、`*.sqlite`、`*.sqlite3`
- `logs/`、`outputs/`、`runtime/`、`var/logs/*`、`var/outputs/*`、`var/runtime/*`
- `.venv/`、缓存、构建产物、临时依赖包
- `local_recycle/private_manifests/` 中的真实 fixture 文件名、源文档 SHA 和本地关联映射
- 根目录用户 `.docx`
- 未脱敏的测试 Word、用户 Word、日志正文
- `wps/` 下的 wheel、Python 运行时、构建产物和插件私有文件；当前仅允许 `wps/公文格式规范.md`

`.gitignore` 只影响未跟踪文件。已经被 Git 跟踪或已经进入历史的文件，不会因为写入 `.gitignore` 自动消失。

## 5. 发布命令

日常推送默认使用快速模式：保留临时干净克隆、允许清单复制、敏感文件扫描、差异检查、提交、推送和远端提交号核验，但不重复运行全量 Python、Ruff 和 Node 测试。可显式标记为 `-Quick`；省略该标记仍保持同一快速行为，兼容既有调用。

```pwsh
pwsh -NoProfile -File .\scripts\publish_to_github.ps1 -Quick -CommitMessage "说明本次修改"
```

以下情况必须使用完整验证：用户要求全量验证或正式发布；修改识别/导入/分段/规范化/渲染主链路、SDK 公开协议、鉴权安全、依赖锁、启动部署或 CI；或存在未解释快照、批量 DOCX 回归差异。

完整验证使用：

```pwsh
pwsh -NoProfile -File .\scripts\publish_to_github.ps1 -Verify -CommitMessage "说明本次修改"
```

脚本自动完成：复制允许文件、敏感文件扫描、差异检查、提交、推送和远程提交号核验。它不会 force push；如果发布期间远端分支发生变化，脚本会停止。

发布扫描还会执行 `scripts/check_public_metadata.py`，阻止公开 B0 manifest 或报告包含 DOCX 文件名、测试目录、绝对路径、源文档 SHA 和可识别的 fixture 名称。commit、tree、wheel、配置和输出聚合哈希不受影响。完整私有映射仅保存在被 Git 忽略的 `local_recycle/private_manifests/`，发布脚本不复制该目录。

仅在需要时使用：

```pwsh
# 只预览，不提交、不推送
pwsh -NoProfile -File .\scripts\publish_to_github.ps1 -DryRun

```

## 6. 重要限制

临时干净克隆只能保证“新提交”不带不允许文件，不能清除远端仓库已经存在的旧 Git 历史。如果敏感内容已经进入历史，需要另行制定历史清理方案，并在确认风险后单独执行。

发布脚本通过“只复制允许清单文件”的方式删除远端已退役文件。因此，如果新增了真实项目文件，必须同步更新：

- `docs/UPLOAD_MANIFEST.md`
- `docs/GITHUB_UPLOAD_GUIDE.md`
- `scripts/publish_to_github.ps1`

## 7. 手动检查命令

```pwsh
pwsh -NoProfile -Command "git status --short --branch"
pwsh -NoProfile -Command "python -m pytest"
pwsh -NoProfile -Command "python -m ruff check src tests scripts"
pwsh -NoProfile -Command "node --test tests/worker-routing.test.mjs"
pwsh -NoProfile -Command "python -m build"
```

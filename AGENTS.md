# DocxTool Project Agent Rules

全局 Codex 工程规则由全局 `AGENTS.md` 统一继承，本文件只保存 DocxTool 项目专属的架构、验证、发布和生产环境事实。

## 项目技能路由

1. DOCX 识别、规范化和排版使用 `docxtool-recognition-layout`。
2. GitHub 发布使用 `scripts/publish_to_github.ps1` 的 Quick 流程；仅在用户明确要求完整验收时使用 `-Verify`。

## 任务验证入口

优先使用按改动范围选择检查的入口：

```pwsh
pwsh -NoProfile -File .\scripts\verify_changed.ps1
```

该入口输出 `SELECTED_CHECKS`、`SKIPPED_CHECKS` 和 `NOT_RUN`，不生成 EXE；完整 WPS 门禁仍由 `apps/wps/scripts/verify.ps1` 提供。

## 文档维护

1. `docs/README.md` 是文档导航和职责索引；新增或调整长期文档必须登记。
2. 当前架构统一见 `docs/ARCHITECTURE.md`，不维护逐文件职责副本。
3. 公文结构回归见 `docs/DOCX_REGRESSION_CHECKLIST.md`；WPS 宿主回归见 `docs/WPS_REGRESSION_CHECKLIST.md`；Reader 局部规则见 `apps/reader/AGENTS.md`。
4. `docs/API.md` 是 HTTP 外部契约；`docs/RELEASE.md` 是发布范围、SSH 操作和安全边界。
5. 规范、PRD、技术设计、API、回归清单和验收记录保持分立，不复制同一事实。

## 迁移专项

适用于机械迁移或行为保持重构：

1. 每轮只完成一个主要职责，不夹带行为优化。
2. 只允许调整文件归属、导入关系、兼容 facade 和等价测试。
3. 运行 `docs/migration/codex-workflow.md` 规定的快速、模块或里程碑门禁。
4. 出现未解释的快照或行为差异时标记 `blocked`，保存脱敏证据并停止迁移项。
5. 完成当前微任务后停止，不自动提交、推送或进入下一阶段。

## 接口与依赖边界

1. 文档层保持 `models/analysis/text → importing/segmentation → recognition → normalization → engine` 单向依赖。
2. `document/pipeline`、`document/recognition` 不得导入 `document/engine`；`document/engine` 不得从 importer facade 获取共享模型。
3. 可替换导出器执行前必须通过签名或明确 adapter 适配参数。
4. `web.handler` 和 `web.compatibility` 必须能在全新解释器中独立导入，并保持旧 `web.app` monkeypatch 边界。
5. SDK 协议模型、校验器和清单必须保持无循环导入。

## 本地回收站与发布

1. `local_recycle/` 仅用于本机临时补丁、快照、备份和可重新生成产物，不得提交。
2. 发布前阅读 `docs/RELEASE.md`，使用 `scripts/publish_to_github.ps1`，不得直接把整棵工作树推送到 GitHub。
3. 发布必须先同步并核验本地分支基线，再在当前本地仓库按允许清单暂存并创建提交，最后通过 SSH 推送；禁止只在临时克隆中生成远端提交。
4. 普通发布使用脚本默认流程；只有用户明确要求时才使用 `-Verify` 完整验收。版本以 `src/docxtool/version.py`、`pyproject.toml` 和 `CHANGELOG.md` 为准。
5. 新增或移动正式源码、资源、测试和文档时，第一时间同步写入 `scripts/publish_to_github.ps1` 的允许清单；新增长期文档还必须立即登记到 `docs/README.md`，不得等到发布前再补。
6. `src/docxtool/` 是日常开发与 GitHub 发布的唯一权威源码。`docxtool/` 是部署包镜像：日常修改、测试和普通发布均忽略该目录；只有用户明确下达“发布新版本”命令时，才同步并发布该部署包。

## 当前生产回源事实

以下信息由用户于 2026-08-17 明确确认；处理部署、Nginx、Cloudflare Pages 或 WPS 公网链路时必须以此为准：

- 公网母域名：`toolpp.cn`。
- 后端 HTTPS Origin：`origin.toolpp.cn`。
- 后端服务器公网 IP：`43.130.232.115`。
- 后端服务仅监听：`127.0.0.1:9527`，由 Nginx 提供公网 HTTPS；不开放 `9527`。
- 公网用户入口：`https://docx.toolpp.cn`；WPS 和浏览器只使用该地址，不直连 Origin。
- Origin TLS 证书：`origin.toolpp.cn` 使用 Let's Encrypt 免费证书，由 Ubuntu 上的
  `certbot --nginx -d origin.toolpp.cn` 获取并部署给 Nginx；Certbot 定时任务自动续期。
- Origin DNS 仅使用 A 记录 `43.130.232.115`，当前不配置 AAAA。
- 浏览器和 WPS 到 `https://docx.toolpp.cn` 可使用 IPv4 或 IPv6；WPS 不得因 Origin IPv4-only 而强制 IPv4。
- `PRODUCTION_MODE=true` 时，除 `/health`、`/ready` 外的所有 Backend HTTP 业务请求必须由 Worker 注入正确的 `X-Proxy-Secret`；Origin 直连不提供业务旁路。
- `docxtool/setup.sh` 从唯一配置 `MAX_UPLOAD_SIZE_MB` 渲染 Nginx 的 `client_max_body_size`；Backend 仍执行应用层上传校验。

## 重复问题处理

1. 先查阅相关专项回归清单和文档唯一职责表，避免重复实现或重复记录。
2. 可复用规则写入对应的唯一专项文档，不在多个文档重复维护同一事实。
3. 修改公文、OOXML、页眉页脚、分节、字段、关系或样式时，优先依据官方文档和现有回归测试。

## 常用检查

```pwsh
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m pytest tests/test_architecture_docs.py -q"
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m ruff check src tests scripts"
pwsh -NoProfile -Command "git diff --check"
pwsh -NoProfile -File .\scripts\publish_to_github.ps1 -Quick -CommitMessage "说明本次修改"
```

只有用户明确要求完整验收时，才使用：

```pwsh
pwsh -NoProfile -File .\scripts\publish_to_github.ps1 -Verify -CommitMessage "说明本次修改"
```

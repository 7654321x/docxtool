# Global Codex Agent Rules

本文件适用于整个仓库，只保存跨任务强制规则。公文回归、WPS 宿主和 Reader 的具体规则分别见专项文档，不在此重复维护。

## 基本原则

1. 先阅读相关源码、配置、测试和专项文档，再修改代码或文档。
2. 保持改动范围最小，不做与当前任务无关的重构、依赖升级或格式化。
3. 不为了通过测试删除测试、降低安全限制或绕过鉴权逻辑。
4. 不修改真实密钥、生产配置或用户私有数据。
5. 不执行 `git commit` 或 `git push`，除非用户明确要求。
6. 用户工作树已有修改属于用户内容，必须保留；不得使用破坏性恢复命令覆盖它们。
7. 任务按 S/M/L 分级：S 级单文件小修复使用短计划和聚焦测试；M 级模块功能先写短设计；L 级识别、排版、账号、鉴权、协议、数据库、发布或架构变更必须先写正式技术设计，再修改源码。分级规则和模板见 `docs/design/CODEX_WORKFLOW_OPTIMIZATION.md`。

## 需求与错误边界

1. 根据源码、配置、测试和实际运行结果核实需求前提；区分已验证事实、合理推断和建议。
2. 必需条件不成立时立即失败并保留真实异常链；不得用空结果、默认值、静默跳过或假成功掩盖失败。
3. 不增加未经要求的缓存、重试、降级、自动修复、兼容 fallback、自动封禁或重复状态。
4. 外部 API 和库函数按当前依赖版本的官方签名调用；不猜测字段、异常类型或返回结构。
5. 数据库失败只回滚当前必要事务后抛错；只有能增加业务上下文时才包装异常。

## Windows 与验证

Windows 显式命令固定使用 PowerShell 7：

```pwsh
pwsh -NoProfile -Command "..."
```

修改后按任务范围运行最小必要测试。跨模块、发布或用户明确要求完整验证时，再执行相应专项门禁。未运行真实 WPS 时不得声称真实宿主 PASS，必须明确标记 `NOT_RUN`。

## 技能路由

1. DOCX 识别、规范化和排版使用 `docxtool-recognition-layout`；普通 WPS UI、Reader、Agent 文档和发布任务不触发该技能。
2. Codex 设置、技能和工作流问题使用 `openai-docs`；网页调研使用一个网络检索路由，避免同一问题重复搜索。
3. GitHub 发布直接使用项目 Quick 发布流程；只有用户明确要求完整验收时才进入 `-Verify` 门禁。
4. 复杂审阅、重构和方案评估才使用通用代码审阅准则；单文件小修复不加载无关技能。

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
6. 用户正文、真实路径、密钥、Token、完整哈希和完整运行日志不得写入长期文档。

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
3. 可替换导出器执行前通过签名或明确 adapter 适配参数；不得捕获导出器内部任意 `TypeError` 后重试。
4. `web.handler` 和 `web.compatibility` 必须能在全新解释器中独立导入，并保持旧 `web.app` monkeypatch 边界。
5. SDK 协议模型、校验器和清单必须保持无循环导入。

## 本地回收站与发布

1. `local_recycle/` 仅用于本机临时补丁、快照、备份和可重新生成产物，不得提交。
2. 已被 Git 跟踪的修改必须保留在原路径，不能移动到回收站制造干净工作树。
3. 发布前阅读 `docs/RELEASE.md`，使用 `scripts/publish_to_github.ps1`，不得直接把整棵工作树推送到 GitHub。
4. 发布必须先同步并核验本地分支基线，再在当前本地仓库按允许清单暂存并创建提交，最后通过 SSH 推送；禁止只在临时克隆中生成远端提交。
5. 普通发布使用脚本默认流程；只有用户明确要求时才使用 `-Verify` 完整验收。版本以 `src/docxtool/version.py`、`pyproject.toml` 和 `CHANGELOG.md` 为准；当前文档基线为 5.6.0。
6. 新增或移动正式源码、资源、测试和文档时，第一时间同步写入 `scripts/publish_to_github.ps1` 的允许清单；新增长期文档还必须立即登记到 `docs/README.md`，不得等到发布前再补。

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
2. 可复用规则写入对应的唯一专项文档，不写入用户正文、真实路径或完整日志。
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

# Docxtool 上传清单

本清单用于 AI 协作、代码审阅和 GitHub 发布。以当前本地项目结构为准，不沿用旧目录名或已退役文件。

当前项目根目录：

```text
D:\PycharmProjects\docxtool
```

目标 GitHub 仓库：

```text
https://github.com/7654321x/docxtool.git
```

## 1. 每次都应上传或保留的项目文件

| 文件路径 | 作用 | 说明 |
| --- | --- | --- |
| `README.md` | 项目说明和本地运行方式 | GitHub 首页会使用 |
| `CHANGELOG.md` | 发布版本与变更记录 | 与 `pyproject.toml` 版本同步维护 |
| `docs/DEPLOY.md` | 生产部署说明 | Cloudflare Pages + Python 后端 |
| `docs/API.md` | HTTP 接口、鉴权、错误码 | 前后端联调和排错 |
| `docs/RECOGNITION_ARCHITECTURE.md` | 识别架构和稳定边界 | 识别层维护依据 |
| `docs/ARCHITECTURE_DAG.md` | Web 处理链和 SDK 宿主适配 DAG | 解释队列、worker、子进程和绑定协议边界 |
| `docs/RECOGNITION_RELEASE.md` | 识别发布门禁和回滚 | 发布验收依据 |
| `docs/DOCX_REGRESSION_CHECKLIST.md` | 已知公文问题和回归检查清单 | 批量测试与视觉抽查依据 |
| `docs/SDK.md` | 本地识别 SDK 接口和集成边界 | WPS/第三方软件调用依据 |
| `docs/INTEGRATION_CONTRACT_V1.md` | SDK 通用宿主 JSON 协议 | WPS、Word 和其他宿主共同实现依据 |
| `docs/HOST_ADAPTER_GUIDE.md` | 宿主适配器伪代码和职责边界 | 仅描述接入流程，不实现插件 |
| `docs/examples/sdk-contract-examples.md` | 脱敏 SDK 协议示例 | 普通段落、多片段、review、unresolved 示例 |
| `docs/RECOGNITION_SOURCE_LOCATORS.md` | 来源定位与宿主绑定协议 | WPS/第三方安全定位依据 |
| `docs/HOST_TEXT_V1_GOLDEN.json` | 脱敏 host-text-v1 金标 | Python/WPS 统一文本契约依据 |
| `docs/USER_WPS_VALIDATION.md` | WPS 用户验收步骤 | 仅操作脱敏 fixture |
| `docs/USER_WPS_VALIDATION_RESULT.md` | WPS 用户验收记录模板 | 初始状态均为未测试 |
| `公文格式规范.md` | 根目录公文格式规范副本 | 与 WPS 目录规范保持一致，兼容既有链接 |
| `docs/UPLOAD_MANIFEST.md` | 本清单 | 上传范围依据 |
| `docs/GITHUB_UPLOAD_GUIDE.md` | GitHub 发布说明 | 不包含私钥 |
| `AGENTS.md` | 本地协作规则 | Codex/AI 工作规则 |
| `CONVENTIONS.md` | 开发约定 | 排版边界和人工验证说明 |
| `requirements.txt` | Python 依赖 | 当前位于仓库根目录 |
| `requirements.lock` | 带哈希的生产依赖锁 | 使用 `pip install --require-hashes -r requirements.lock` |
| `requirements-dev.lock` | 带哈希的开发与 CI 依赖锁 | 固定 pytest、ruff、build 和 pip-tools |
| `pyproject.toml` | Python 包配置 | `src` 布局和 wheel 资源打包 |
| `run.sh` | Linux 启动脚本 | 调用 `server.py` |
| `run.ps1` | Windows 启动脚本 | 支持 Python 3.8—3.10，并为 Windows 7 回退到 `schtasks.exe` |
| `deploy/nginx-docxtool.conf` | Nginx代理模板 | 不包含服务器IP或磁盘绝对路径 |
| `.env.example` | 环境变量示例 | 不含真实密钥 |
| `.gitignore` | Git 忽略规则 | 不会自动移除已跟踪文件 |
| `.gitattributes` | Git 文本/二进制规则 | 控制换行和二进制文件处理 |
| `pytest.ini` | pytest 配置 | 测试配置 |
| `ruff.toml` | Ruff 配置 | 代码检查配置 |
| `.github/workflows/ci.yml` | GitHub Actions | CI 测试 |

## 2. 后端和排版核心

| 文件路径 | 作用 |
| --- | --- |
| `server.py` | 兼容入口，调用新包 |
| `src/docxtool/__init__.py` | Python 包入口 |
| `src/docxtool/__main__.py` | `python -m docxtool` 入口 |
| `src/docxtool/version.py` | 运行时包版本统一入口 |
| `src/docxtool/paths.py` | 项目路径、运行目录和默认资源定位 |
| `src/docxtool/env.py` | 环境变量加载和本地启动配置 |
| `src/docxtool/auth/__init__.py` | 普通用户认证包入口 |
| `src/docxtool/auth/passwords.py` | Argon2id 密码哈希与校验 |
| `src/docxtool/auth/service.py` | 用户名和密码输入归一化及验证 |
| `src/docxtool/web/__init__.py` | Web 包入口 |
| `src/docxtool/web/app.py` | Web 服务入口、上传下载、任务队列、管理后台、健康检查 |
| `src/docxtool/web/admin_auth.py` | 管理员 session、legacy token 和 CSRF 校验 | 通过注入的数据库连接器和密钥配置工作 |
| `src/docxtool/web/anonymous_identity.py` | 匿名 owner cookie 签名、解析和来源校验 | 不读写数据库，只处理 headers、cookie 和密钥配置 |
| `src/docxtool/web/client_ip.py` | 可信代理、客户端 IP 和密钥比较辅助 | 只处理 headers、socket 地址和代理配置 |
| `src/docxtool/web/config.py` | Web 环境和 CORS 配置解析 | 不读写数据库、不处理请求体，供 `web.app` 兼容入口调用 |
| `src/docxtool/web/file_utils.py` | 文件名、下载头和错误脱敏辅助 | 不读写磁盘，只处理字符串 |
| `src/docxtool/web/format_request.py` | 上传格式配置和处理模式解析 | 只处理 headers 和格式配置对象，不执行任务 |
| `src/docxtool/web/health.py` | 健康检查、readiness、版本和启动 URL payload | 只组装只读状态，不处理 HTTP 路由 |
| `src/docxtool/web/monitoring.py` | 监控页查询、分页和链接辅助 | 只处理分页参数和 URL，不读写数据库 |
| `src/docxtool/web/preset_config.py` | 预设模板名称、ID、格式配置和 API 行数据归一化 | 不读写数据库，只处理模板配置对象 |
| `src/docxtool/web/rate_limits.py` | 上传限流、认证限流、IP 封禁和上传次数限制 | 通过注入的数据库连接器处理任务、设置和封禁表 |
| `src/docxtool/web/request_utils.py` | HTTP 路径、Cookie、CSRF、JSON 和 HTML 辅助 | 只处理请求头、字节和字符串，不读写数据库 |
| `src/docxtool/web/stream_io.py` | HTTP 上传读取和下载流输出辅助 | 只处理流、路径和 writer，不判断任务状态 |
| `src/docxtool/web/task_paths.py` | 任务路径和永久保留清理钩子 | 只计算路径，清理未完成上传或无效输出 |
| `src/docxtool/web/task_state.py` | 任务计数、队列位置、公开状态和识别摘要 | 只处理传入的任务/队列容器和脱敏摘要，不直接访问路由 |
| `src/docxtool/web/time_check.py` | 启动时区和网络时间校验辅助 | 只生成启动提示，不影响服务启动流程 |
| `src/docxtool/sdk/` | 面向第三方的只读识别 SDK | 返回脱敏结构计划，不操作宿主文档 |
| `src/docxtool/sdk/binding.py` | 宿主无关的识别计划绑定 | 对本地段落快照保序验证，不调用 WPS API |
| `src/docxtool/document/__init__.py` | 文档处理包入口 |
| `src/docxtool/document/importer.py` | DOCX 结构识别、段落分类、元数据生成 |
| `src/docxtool/document/effective_format.py` | run、样式继承、主题字体的有效格式解析 |
| `src/docxtool/document/source_tape.py` | 物理段落来源范围与 raw/canonical 坐标映射 |
| `src/docxtool/document/models/` | 导入链路共享数据模型 | 为 importer、分段和 SDK 兼容入口提供稳定中间结构 |
| `src/docxtool/document/normalization/` | 导入后的结构归一化 | 当前承载尾部附件、落款、日期顺序修正和诊断同步 |
| `src/docxtool/document/segmentation/` | 物理段到逻辑段的分段辅助 | 当前承载来源定位、标题正文边界和软换行强结构判断 |
| `src/docxtool/document/classifier.py` | 文档模式和段落结构分类 |
| `src/docxtool/document/letterhead_config.py` | 版头配置归一化和安全校验 |
| `src/docxtool/document/recognition/` | 候选、Beam 解码、诊断、验证和兼容映射 |
| `src/docxtool/document/recognition/colon.py` | 共享冒号结构分析 | 只输出称呼、机构标签、键值和解释性正文证据，不直接定型 |
| `src/docxtool/document/recognition/global_context.py` | 文首结构、正文边界和同级标题族的全文只读分析 |
| `src/docxtool/document/style_config.py` | 样式规则、页面设置、日志配置、默认配置读取 |
| `src/docxtool/resources/__init__.py` | 打包资源包入口 |
| `src/docxtool/resources/config/default-format.json` | 默认公文格式配置，随 wheel 安装 |
| `src/docxtool/resources/schemas/` | SDK JSON Schema 资源 | 随 wheel 安装，作为跨语言协议来源 |
| `src/docxtool/document/engine/__init__.py` | 排版引擎导出入口 |
| `src/docxtool/document/engine/core.py` | DOCX 导出和实际排版逻辑 |
| `src/docxtool/document/engine/context_candidate.py` | 基于原始元素事实和局部邻接的独立上下文候选 |
| `src/docxtool/document/engine/document_structure.py` | 只读结构化公文板块模型与边界识别 |
| `src/docxtool/document/engine/normal.py` | 常规文种规则分派 |
| `src/docxtool/document/engine/letterhead.py` | 版头、发文字号、签发人和红色分隔线 |
| `src/docxtool/document/engine/style_catalog.py` | 结构化 Word 样式目录 |
| `src/docxtool/document/engine/page_number.py` | 字段页码和奇偶页外侧位置 |
| `src/docxtool/document/engine/numbering.py` | 结构序号规范化 |
| `src/docxtool/document/engine/punctuation.py` | 标点规范化核心 |
| `src/docxtool/document/engine/punctuation_docx.py` | DOCX 标点安全处理 |
| `src/docxtool/document/engine/signature_block.py` | 落款单位、成文日期和附件结构排版 |
| `src/docxtool/document/engine/structure_context.py` | 板块候选与既有上下文分类的只读双重验证 |
| `src/docxtool/document/engine/cleanup.py` | 保守样式清理 |
| `src/docxtool/document/engine/table.py` | 表格处理边界入口 |
| `src/docxtool/security/__init__.py` | 安全模块入口 |
| `src/docxtool/security/docx_validator.py` | DOCX 上传安全校验 |
| `src/docxtool/security/docx_integrity.py` | 生成 DOCX 的 OOXML 完整性校验 |
| `src/docxtool/storage/__init__.py` | 存储包入口 |
| `src/docxtool/storage/database.py` | SQLite 路径和连接辅助 |
| `scripts/generate_secrets.py` | 生成随机密钥辅助脚本 |
| `scripts/benchmark_recognition.py` | 无正文识别性能基准 |
| `scripts/compare_recognition_runs.py` | 安全识别差分和确定性检查 |
| `scripts/analyze_end_format.py` | 排版结果与正确模板的无正文格式差异分析 |
| `scripts/analyze_letterhead_batch.py` | 批量版头状态与问题归类 |
| `scripts/batch_test_docx.py` | 编号测试文档批处理、结构对齐模板比较与可选视觉渲染抽查 |
| `scripts/generate_005_format_fixtures.py` | 可复现的本地乱格式测试文档生成 |
| `scripts/generate_wps_validation_fixtures.py` | 生成脱敏 WPS 手工验收 DOCX |
| `scripts/normalize_correct_template_role_spacing.py` | 正确模板职务姓名空段归一化 |
| `scripts/migrate_legacy_database.ps1` | 旧数据库复制迁移辅助脚本，默认 dry run |
| `scripts/publish_to_github.ps1` | 安全发布到 GitHub 的脚本 |

## 3. 前端和 Cloudflare Pages

当前唯一前端源入口：

```text
resources/frontend/pages/index.html
```

Cloudflare Pages 部署文件：

```text
resources/frontend/pages/index.html
resources/frontend/pages/_worker.js
```

说明：

- `resources/frontend/pages/index.html` 是唯一权威生产前端。
- 重构前的旧前端入口和 legacy 页面已移除，不再上传。

运行目录只上传空目录占位文件：

```text
var/data/.gitkeep
var/logs/.gitkeep
var/outputs/.gitkeep
var/runtime/.gitkeep
```

这些目录中的数据库、日志、输出文件和运行时临时文件禁止上传。

## 4. 测试文件

默认上传：

```text
tests/test_*.py
tests/*.test.mjs
```

`tests/` 下的 `.docx` 样例只在确实需要回归测试样例时保留或上传。当前安全发布脚本默认不复制任何 `.docx`，因此不会把根目录用户文档或测试样例文档推送到 GitHub。若以后确需上传测试 fixture，应先脱敏并显式加入清单。

## 5. 已退役或非默认发布文件

这些重构前文件已移除，不再进入 GitHub 发布清单。旧桌面端、旧前端入口、旧技能目录和临时演示文件如需重新维护，应在独立目录重新引入。

如果以后重新维护桌面端，应单独建立发布清单和依赖说明。

## 6. 禁止上传

不要上传或提交：

```text
.env
.env.*
真实 ADMIN_TOKEN
真实 PROXY_SECRET
API Key
Authorization 请求头
Cookie
SSH 私钥
证书私钥
stats.db
stats.db-*
var/data/*
var/logs/*
var/outputs/*
var/runtime/*
logs/
outputs/
runtime/
__pycache__/
*.pyc
.venv/
venv/
env/
.pytest_cache/
.ruff_cache/
.playwright-mcp/
.idea/
build/
dist/
tmp_wheels/
*.zip
根目录 *.docx
未脱敏用户 Word 文档
```

`.gitignore` 只能阻止未跟踪文件被自动加入，不能自动移除已经被 Git 跟踪的文件。若某个敏感文件已经进入 Git 历史，单纯更新 `.gitignore` 不会清除历史。

## 7. GitHub 发布方式

推荐使用：

```pwsh
pwsh -NoProfile -File .\scripts\publish_to_github.ps1 -CommitMessage "说明本次修改"
```

该命令默认完成安全扫描、提交、推送和远程核验。可选操作：

```pwsh
pwsh -NoProfile -File .\scripts\publish_to_github.ps1 -DryRun
pwsh -NoProfile -File .\scripts\publish_to_github.ps1 -Verify -CommitMessage "说明本次修改"
```

发布脚本会使用临时干净克隆，只复制允许文件，并阻止密钥、DOCX、数据库、日志和 WPS 私有工程进入提交。它不会 force push。

## 8. 发布前检查

```pwsh
pwsh -NoProfile -Command "python -m pytest"
pwsh -NoProfile -Command "python -m ruff check src tests scripts"
pwsh -NoProfile -Command "node --test tests/worker-routing.test.mjs"
pwsh -NoProfile -Command "python -m build"
```

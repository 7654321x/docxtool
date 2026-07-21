# Docxtool 上传清单

本清单用于 AI 协作、代码审阅和 GitHub 发布。以当前本地项目结构为准，不沿用旧目录名或已退役文件。

当前项目根目录：

```text
D:\PycharmProjects\docxtool
```

目标 GitHub 仓库：

```text
git@github.com:7654321x/docxtool.git
```

## 1. 每次都应上传或保留的项目文件

| 文件路径 | 作用 | 说明 |
| --- | --- | --- |
| `README.md` | 项目说明和本地运行方式 | GitHub 首页会使用 |
| `docs/DEPLOY.md` | 生产部署说明 | Cloudflare Pages + Python 后端 |
| `docs/API.md` | HTTP 接口、鉴权、错误码 | 前后端联调和排错 |
| `docs/RECOGNITION_ARCHITECTURE.md` | 识别架构和稳定边界 | 识别层维护依据 |
| `docs/RECOGNITION_RELEASE.md` | 识别发布门禁和回滚 | 发布验收依据 |
| `docs/UPLOAD_MANIFEST.md` | 本清单 | 上传范围依据 |
| `docs/GITHUB_UPLOAD_GUIDE.md` | GitHub 发布说明 | 不包含私钥 |
| `AGENTS.md` | 本地协作规则 | Codex/AI 工作规则 |
| `CONVENTIONS.md` | 开发约定 | 排版边界和人工验证说明 |
| `requirements.txt` | Python 依赖 | 当前位于仓库根目录 |
| `pyproject.toml` | Python 包配置 | `src` 布局和 wheel 资源打包 |
| `run.sh` | Linux 启动脚本 | 调用 `server.py` |
| `run.ps1` | Windows 启动脚本 | 基于脚本自身目录创建虚拟环境并启动后端 |
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
| `src/docxtool/paths.py` | 项目路径、运行目录和默认资源定位 |
| `src/docxtool/env.py` | 环境变量加载和本地启动配置 |
| `src/docxtool/auth/__init__.py` | 普通用户认证包入口 |
| `src/docxtool/auth/passwords.py` | Argon2id 密码哈希与校验 |
| `src/docxtool/auth/service.py` | 用户名和密码输入归一化及验证 |
| `src/docxtool/web/__init__.py` | Web 包入口 |
| `src/docxtool/web/app.py` | Web 服务入口、上传下载、任务队列、管理后台、健康检查 |
| `src/docxtool/document/__init__.py` | 文档处理包入口 |
| `src/docxtool/document/importer.py` | DOCX 结构识别、段落分类、元数据生成 |
| `src/docxtool/document/classifier.py` | 文档模式和段落结构分类 |
| `src/docxtool/document/letterhead_config.py` | 版头配置归一化和安全校验 |
| `src/docxtool/document/recognition/` | 候选、Beam 解码、诊断、验证和兼容映射 |
| `src/docxtool/document/style_config.py` | 样式规则、页面设置、日志配置、默认配置读取 |
| `src/docxtool/resources/__init__.py` | 打包资源包入口 |
| `src/docxtool/resources/config/default-format.json` | 默认公文格式配置，随 wheel 安装 |
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
pwsh -NoProfile -File .\scripts\publish_to_github.ps1
```

默认只演练，不提交、不推送。确认无误后：

```pwsh
pwsh -NoProfile -File .\scripts\publish_to_github.ps1 -Push
```

发布脚本会使用临时干净克隆，把本清单允许的文件复制进去，并让远端已退役文件在新提交中删除。它不会清除远端旧 Git 历史，也不会 force push。

## 8. 发布前检查

```pwsh
pwsh -NoProfile -Command "python -m pytest"
pwsh -NoProfile -Command "python -m ruff check src tests scripts"
pwsh -NoProfile -Command "node --test tests/worker-routing.test.mjs"
pwsh -NoProfile -Command "python -m build"
```

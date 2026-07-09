# Docxtool AI 上传文件清单

这是一份**当前项目专用**清单。以后让 AI 修改本公文排版工具时，按本文件上传，不要让 AI 依靠通用目录名猜测项目结构。

本仓库根目录是 `docxtool/`。项目外层目录里的日志、测试 Word、打包产物、临时文件不属于上传范围。

## 1. 每次都上传

| 文件路径 | 文件作用 | 是否必须上传 | 关联功能 |
| --- | --- | --- | --- |
| `README.md` | 项目功能、启动方式、部署说明 | 是 | 项目总览 |
| `API.md` | HTTP 接口、鉴权、错误码说明 | 是 | 前后端联调、接口排查 |
| `UPLOAD_MANIFEST.md` | 本清单 | 是 | AI 上下文选择 |
| `requirements.txt` | Python 依赖 | 是 | 环境安装 |
| `.env.example` | 环境变量示例，不含真实密钥 | 是 | 部署配置 |
| `.gitignore` | 排除日志、数据库、缓存、输出文件 | 是 | 上传安全 |

## 2. 后端接口和服务

修改上传、状态查询、下载、鉴权、监控、日志、队列、限流、健康检查时上传：

| 文件路径 | 文件作用 | 是否必须上传 | 关联功能 |
| --- | --- | --- | --- |
| `server.py` | Web 服务入口和全部 HTTP 路由 | 是 | `/upload`、`/api/upload`、`/status`、`/download`、监控后台 |
| `run.sh` | Linux 启动脚本 | 视情况 | 部署启动 |
| `API.md` | 接口契约文档 | 是 | 接口变更同步 |

当前后端没有独立的 `routes/`、`controllers/`、`models/`、`migrations/` 目录。如果以后新增这些目录，必须补到本清单。

## 3. 前端页面和代理

修改页面、按钮、模板设置、上传接口、状态轮询、下载、Cloudflare Pages 时上传：

| 文件路径 | 文件作用 | 是否必须上传 | 关联功能 |
| --- | --- | --- | --- |
| `index.html` | 旧版前端页面，兼容参考 | 是 | 老页面、接口参考 |
| `index1.html` | 当前新版前端页面 | 是 | 模板设置、上传、轮询、下载、`X-Format-Config` |
| `pages_dist/index.html` | Pages 部署页面 | 视情况 | Cloudflare Pages |
| `pages_dist/_worker.js` | Pages Worker 代理 | 视情况 | `/api/upload`、`/api/status`、`/api/download` 代理 |

当前前端是单 HTML 文件，没有独立 `assets/js/`、`assets/css/`、`components/`。如果以后拆分，必须补到本清单。

## 4. 公文排版核心

修改公文格式、标题识别、正文识别、编号、加粗、段距、页边距、表格/图片复制、日期/署名/附件规则时上传：

| 文件路径 | 文件作用 | 是否必须上传 | 关联功能 |
| --- | --- | --- | --- |
| `importer.py` | DOCX 结构识别、段落分类、元数据生成 | 是 | 标题、日期、署名、正文、附件识别 |
| `style_config.py` | 样式规则、页面设置、`config.json` 读取 | 是 | 字体、字号、缩进、页边距、行距 |
| `config.json` | 默认公文格式配置 | 是 | 默认模板、样式行、页面参数 |
| `engine/__init__.py` | 排版引擎导出入口 | 是 | 引擎模块入口 |
| `engine/_core.py` | DOCX 导出和实际排版逻辑 | 是 | 字体、段落、编号、加粗、页码、间距 |
| `engine/normal.py` | 常规文种规则分派 | 是 | 日期行压缩、职务姓名等规则 |

当前项目没有独立 `formatter.py`、`analyzer.py`、`punctuation.py`、`fix_spacing.py`、`converter.py`。对应能力目前集中在 `importer.py`、`engine/_core.py`、`style_config.py`。

## 5. Hermes Skill

修改 Hermes 使用的公文格式规则时上传：

| 文件路径 | 文件作用 | 是否必须上传 | 关联功能 |
| --- | --- | --- | --- |
| `hermes_skills/official-document-formatting/SKILL.md` | Hermes 公文格式排版规则 | 是 | 职务日期间距、标题编号、正文加粗、格式检查 |
| `hermes_skills/official-document-formatting/agents/openai.yaml` | Hermes UI 元数据 | 是 | skill 名称、默认提示 |

旧的 `docxtool-page-integration` skill 已删除，不再上传。

## 6. 测试文件

让 AI 修复逻辑或验证回归时，优先上传相关测试。若只改文档或 README，可不上传测试。

| 文件路径 | 文件作用 | 是否必须上传 | 关联功能 |
| --- | --- | --- | --- |
| `tests/test_engine_heading_spacing.py` | 头部空行、日期段后、编号空格、重复文本回归 | 是 | 公文排版核心 |
| `tests/test_numbered_bold_detection.py` | `一是/二是/三是` 与日期/职务识别回归 | 是 | 段落识别、特殊加粗 |
| `tests/test_config_driven_styles.py` | 配置驱动样式测试 | 视情况 | `config.json`、`style_config.py` |
| `tests/test_importer_heading_flow.py` | 标题流转识别测试 | 视情况 | `importer.py` |
| `tests/test_report_heading_keywords.py` | 报告类标题关键词测试 | 视情况 | 报告文种 |
| `tests/test_signature_detection.py` | 落款识别测试 | 视情况 | 落款署名、落款日期 |
| `tests/test_server_*.py` | 服务端接口、鉴权、日志、生产控制测试 | 视情况 | `server.py` |
| `tests/test_pages_proxy_packaging.py` | Pages 代理打包测试 | 视情况 | `pages_dist/` |

测试目录中的示例 `.docx` 只在需要复现排版差异时上传。上传前确认没有隐私内容。

## 7. 按任务选择上传组合

| 任务类型 | 必传文件 |
| --- | --- |
| 修公文格式或 Word 排版问题 | `importer.py`, `style_config.py`, `config.json`, `engine/__init__.py`, `engine/_core.py`, `engine/normal.py`, 相关 `tests/`, 标准/异常 Word 示例 |
| 修“职务姓名 + 日期”头部间距 | `importer.py`, `engine/_core.py`, `style_config.py`, `config.json`, `tests/test_engine_heading_spacing.py`, `tests/test_numbered_bold_detection.py` |
| 修上传/下载/队列/鉴权 | `server.py`, `API.md`, `README.md`, 相关 `tests/test_server_*.py` |
| 修新版页面接口接入 | `index1.html`, `index.html`, `server.py`, `API.md`, `pages_dist/_worker.js` |
| 修 Cloudflare Pages 代理 | `pages_dist/_worker.js`, `pages_dist/index.html`, `server.py`, `API.md`, `tests/test_pages_proxy_packaging.py` |
| 修默认模板/样式配置 | `config.json`, `style_config.py`, `index1.html`, `engine/_core.py`, 相关配置测试 |
| 修 Hermes 公文格式规则 | `hermes_skills/official-document-formatting/SKILL.md`, `agents/openai.yaml`, 当前已验证的格式样例 |
| 部署或 GitHub 发布 | `README.md`, `API.md`, `.env.example`, `requirements.txt`, `run.sh`, 所有源代码文件，排除运行数据 |

## 8. 不要上传

以下文件和目录不要上传给 AI，也不要提交到 GitHub：

- `.env`
- 真实 API 密钥、真实后台密码、真实代理密钥
- `stats.db`, `stats.db-*`
- `logs/` 下的运行日志，保留 `.gitkeep` 即可
- `outputs/` 下的生成 Word，保留 `.gitkeep` 即可
- `__pycache__/`, `*.pyc`
- `.venv/`, `venv/`
- `.git/`
- `build/`, `dist/`
- `*.zip`
- 临时测试文档、用户隐私 Word、含身份证/手机号/地址等敏感信息的文件

## 9. 新增文件登记

以后新增文件后，按下面格式补充到对应章节：

| 文件路径 | 文件作用 | 是否必须上传 | 关联功能 |
| --- | --- | --- | --- |
| 示例：`api/template.py` | 模板接口文件 | 是 | 自定义模板、SQL 存储 |
| 示例：`models/template.py` | 模板数据库模型 | 是 | 模板配置持久化 |
| 示例：`static/js/template.js` | 前端模板接口调用 | 是 | 前端接入后端接口 |

## 10. 上传前检查

1. 本次修改目标是否写清楚。
2. 是否按任务类型上传了对应文件组合。
3. 新增文件是否已登记到本清单。
4. 是否移除了 `.env`、密钥、隐私数据、日志、数据库、输出 Word。
5. 是否说明当前运行方式和入口文件。
6. 是否说明希望 AI 修改哪些文件、不要动哪些文件。
7. 是否说明已有功能不能破坏。
8. 是否说明输出要求，例如“只给修改建议”“给补丁方案”“直接改代码并验证”“生成 Codex/Hermes 提示词”。

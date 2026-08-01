# 公文排版 Web 服务

这是一个公文排版 Web 服务，支持 `.docx` 上传、格式识别、自动排版、任务状态查询、文件下载、管理后台和 Cloudflare Pages Worker 代理。

当前项目只保留 Web 服务新架构。重构前的桌面端文件和旧前端入口已从发布树移除。

## 当前入口

- 后端入口：`server.py`
- 本地/源码前端入口：`resources/frontend/pages/index.html`
- Cloudflare Pages 部署目录：`resources/frontend/pages/`
- Pages Worker：`resources/frontend/pages/_worker.js`
- Pages 静态页面：`resources/frontend/pages/index.html`

重构前的旧前端入口已退役并移除，不再作为前端入口。

## 主要文件

- `server.py`：兼容入口，调用 `src/docxtool/web/app.py`。
- `src/docxtool/web/app.py`：Web 服务、上传下载、任务队列、管理后台、健康检查。
- `src/docxtool/web/admin_access.py`：管理员请求上下文、页面 CSRF token 和 POST CSRF 校验辅助。
- `src/docxtool/web/admin_actions.py`：管理员监控页 IP、封禁原因和上传限制表单参数解析辅助。
- `src/docxtool/web/admin_auth.py`：管理员会话、legacy token、管理员请求上下文和 CSRF 校验辅助。
- `src/docxtool/web/admin_forms.py`：管理员登录表单字段解析辅助。
- `src/docxtool/web/admin_pages.py`：管理员登录页等静态 HTML 页面渲染辅助。
- `src/docxtool/web/anonymous_identity.py`：匿名用户 owner cookie 签名、解析和来源校验辅助。
- `src/docxtool/web/auth_payloads.py`：用户认证接口 Content-Type 判断、响应体和 Cookie 响应头组装辅助。
- `src/docxtool/web/client_ip.py`：可信代理、客户端 IP、IP 头和密钥比较辅助。
- `src/docxtool/web/config.py`：Web 环境变量、前端来源、Cookie Secure 和 CORS 响应头解析。
- `src/docxtool/web/database_schema.py`：Web SQLite 建表、轻量迁移和默认数据初始化编排。
- `src/docxtool/web/file_api_auth.py`：文件 API 代理密钥和本机调试访问授权辅助。
- `src/docxtool/web/file_utils.py`：文件名清理、下载响应头和错误详情脱敏辅助。
- `src/docxtool/web/format_request.py`：上传请求的格式配置、预设元数据和处理模式解析。
- `src/docxtool/web/frontend_pages.py`：打包前端首页 HTML 的定位和读取辅助。
- `src/docxtool/web/health.py`：健康检查、readiness、版本信息和启动地址 payload。
- `src/docxtool/web/log_redaction.py`：管理员日志展示前的敏感字段脱敏辅助。
- `src/docxtool/web/maintenance.py`：永久保留策略下的后台维护线程兼容入口。
- `src/docxtool/web/monitoring.py`：监控页查询参数、分页和链接生成辅助。
- `src/docxtool/web/monitoring_pages.py`：管理员监控分页、IP 明细和任务日志 HTML 渲染辅助。
- `src/docxtool/web/owner_migration.py`：匿名 owner 的任务和私人模板迁移辅助。
- `src/docxtool/web/preset_config.py`：预设模板名称、ID、格式配置和 API 行数据归一化辅助。
- `src/docxtool/web/preset_defaults.py`：默认公文模板配置、默认功能开关和官方模板 seed 辅助。
- `src/docxtool/web/preset_store.py`：预设模板列表、详情、创建、更新和删除的数据库读写辅助。
- `src/docxtool/web/rate_limits.py`：上传限流、认证限流、IP 封禁和上传次数限制辅助。
- `src/docxtool/web/request_utils.py`：HTTP 路径、Cookie、CSRF、JSON 和 HTML 转义辅助。
- `src/docxtool/web/request_params.py`：query、JSON body 和表单 body 请求参数合并辅助。
- `src/docxtool/web/responses.py`：HTTP 文本/JSON 响应编码、附加头和认证错误体辅助。
- `src/docxtool/web/secrets.py`：Web 管理密钥和代理密钥加载、弱密钥启动校验辅助。
- `src/docxtool/web/stream_io.py`：HTTP 请求体定长读取、上传落盘和下载文件流输出辅助。
- `src/docxtool/web/task_cache.py`：内存任务缓存裁剪辅助。
- `src/docxtool/web/task_paths.py`：任务上传、输出、临时路径和永久保留清理钩子。
- `src/docxtool/web/task_records.py`：任务排队、处理中和终态的数据库记录写入辅助。
- `src/docxtool/web/task_recovery.py`：服务启动时将未完成任务标记为中断的恢复辅助。
- `src/docxtool/web/task_result.py`：终态任务结果的数据库、内存状态和日志同步收口。
- `src/docxtool/web/task_statistics.py`：任务结果统计写入、监控计数和 IP 聚合查询辅助。
- `src/docxtool/web/task_state.py`：任务计数、队列位置、公开任务状态和识别摘要脱敏。
- `src/docxtool/web/task_worker.py`：任务执行边界选择和后台 worker 线程启动辅助。
- `src/docxtool/web/time_check.py`：启动时区和北京网络时间校验提示。
- `src/docxtool/web/user_auth.py`：普通用户 session、登录 cookie、principal 和 CSRF 校验辅助。
- `src/docxtool/document/models/`：导入、识别、规范化、渲染和 SDK 共享的稳定文档数据模型。
- `src/docxtool/document/importer.py`：DOCX 结构识别、段落分类、元数据生成。
- `src/docxtool/document/segmentation/`：逻辑段 source locator、可见文字守恒和段内格式特征映射。
- `src/docxtool/document/normalization/`：识别完成后的尾部顺序、日期/附件显示规范和诊断一致性处理。
- `src/docxtool/document/style_config.py`：样式规则、页面设置、日志配置。
- `src/docxtool/document/engine/`：DOCX 导出和实际排版逻辑。
- `src/docxtool/security/`：上传 DOCX 安全校验。
- `src/docxtool/storage/database.py`：SQLite 路径和连接辅助。
- `src/docxtool/resources/config/default-format.json`：默认公文格式配置，随 Python 包安装。
- 可选 `letterhead` 配置用于在首页正文流生成机关标志、结构化发文字号、上行文签发人和红色段落边框；默认关闭，外部或无法可靠识别的已有版头保持原样。
- `requirements.txt`：Python 运行依赖。
- `run.sh`：Linux 启动脚本。
- `run.ps1`：Windows可移动部署启动脚本，所有相对路径以项目根目录解析。
- `deploy/nginx-docxtool.conf`：服务器Nginx反向代理模板。
- `.env.example`：环境变量示例，不包含真实密钥。
- `docs/API.md`：HTTP 接口、鉴权、错误码说明。
- `docs/DEPLOY.md`：生产部署说明。
- `docs/DOCX_REGRESSION_CHECKLIST.md`：已知公文问题与批量回归检查清单。
- `docs/UPLOAD_MANIFEST.md`：AI 修改和 GitHub 上传范围清单。
- `docs/GITHUB_UPLOAD_GUIDE.md`：安全发布到 GitHub 的操作说明。
- `scripts/publish_to_github.ps1`：PowerShell 7 安全发布脚本，一条命令完成提交、推送和远程核验。

## 本地运行

支持的 Python 版本为 3.8、3.9 和 3.10。Windows 7 SP1 固定使用 Python 3.8，
Windows 8.1 及以上可使用 Python 3.8 至 3.10。面向最终用户的商业安装包应内置
Python 运行时，不要求用户自行安装或配置 Python。

Windows PowerShell 7：

```pwsh
Copy-Item .env.example .env
# 编辑 .env 后首次运行：
pwsh -NoProfile -File .\run.ps1 -InstallDependencies
# 后续运行：
pwsh -NoProfile -File .\run.ps1
# 注册为Windows计划任务，退出远程桌面后仍运行：
pwsh -NoProfile -File .\run.ps1 -InstallService
```

Windows 7 SP1 需要安装 Windows Management Framework 5.1，并使用系统自带的
Windows PowerShell 5.1 执行同一脚本；脚本会在缺少新式计划任务命令时自动改用
`schtasks.exe`：

```pwsh
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -CheckOnly
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -InstallService
```

`run.ps1`每次启动前都会核对`requirements.lock`，缺少依赖时自动下载并安装；
已满足的依赖不会重复下载。

Linux：

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export ADMIN_TOKEN='换成你的长随机管理密钥'
export PROXY_SECRET='换成你的长随机代理密钥'
./run.sh
```

生产部署应使用带哈希的锁文件：

```bash
python -m pip install --require-hashes -r requirements.lock
```

`requirements.lock` 由 Python 3.8 环境根据 `pyproject.toml` 生成，不手工维护哈希；
同一锁文件必须同时通过 Python 3.8 和 3.10 安装验证：

```bash
python -m piptools compile pyproject.toml --generate-hashes --no-emit-index-url --no-emit-trusted-host --output-file requirements.lock
```

开发、测试和打包使用同一套锁定工具版本：

```bash
python -m pip install --require-hashes -r requirements-dev.lock
python -m piptools compile --extra dev pyproject.toml --generate-hashes --no-emit-index-url --no-emit-trusted-host --output-file requirements-dev.lock
```

默认监听 `127.0.0.1:9527`。生产环境通过Nginx反向代理访问，不要将9527开放到公网。

仅在明确需要直接调试网络监听时使用：

```bash
BIND_HOST=0.0.0.0 PORT=9527 ./run.sh
```

生产环境必须显式配置 `ADMIN_TOKEN` 和 `PROXY_SECRET`，不能使用示例值。常用环境变量见 `.env.example`。

## 运行时文件

服务运行时可能生成：

- `var/logs/`
- `var/outputs/`
- `var/runtime/`
- `var/data/stats.db`

这些都是本地运行数据，不应提交到 GitHub。

如果仓库根目录已经存在旧版 `stats.db`，程序在未设置 `DATABASE_PATH` 时会继续使用旧库，避免生成第二份空数据库掩盖历史数据。人工迁移到新位置前，先停服务并备份：

```pwsh
pwsh -NoProfile -File .\scripts\migrate_legacy_database.ps1
pwsh -NoProfile -File .\scripts\migrate_legacy_database.ps1 -Execute
```

确认输出 `ok` 后，再在生产环境设置：

```text
DATABASE_PATH=var/data/stats.db
```

数据库父目录只会在实际建立 SQLite 连接时创建；仅导入包、读取默认配置或执行 `python -m docxtool --help` 不会创建 `stats.db`。源码树以仓库根目录作为运行数据根；wheel 安装后默认使用用户数据目录，避免把数据库、日志或输出写入 `site-packages`。可用 `DOCXTOOL_HOME`、`LOG_DIR`、`OUTPUT_DIR`、`RUNTIME_DIR` 和 `DATABASE_PATH` 显式覆盖。

## 测试

```pwsh
pwsh -NoProfile -Command "python -m pytest"
pwsh -NoProfile -Command "python -m ruff check src tests scripts"
pwsh -NoProfile -Command "node --test tests/worker-routing.test.mjs"
pwsh -NoProfile -Command "python -m build"
```

## 本地识别 SDK

`1.3` 起，项目提供只读识别 SDK，供 WPS/Word 加载项或其他本地软件调用。`2.0` 起，
SDK 增加 `integration-contract-v1`、JSON Schema、能力协商和独立绑定 CLI。SDK 不启动 Web
服务，也不生成结果 DOCX：

```python
from docxtool.sdk import bind_recognition_plan, recognize_docx

plan = recognize_docx("input.docx", processing_mode="structural")

binding = bind_recognition_plan(plan, {
    "host_type": "wps",
    "paragraphs": [{"host_paragraph_index": 0, "raw_text": "当前段落文字"}],
})
```

构建 wheel 后可使用 `docxtool-recognize input.docx --output plan.json` 导出脱敏识别计划。
跨语言集成推荐使用：

```pwsh
docxtool-sdk manifest
docxtool-sdk recognize --source input.docx --output plan.json
docxtool-sdk bind --plan plan.json --snapshot snapshot.json --output binding.json
docxtool-sdk validate --kind recognition-binding --input binding.json
```

详细接口、数据边界和宿主接入方式见 [docs/SDK.md](docs/SDK.md)、
[docs/INTEGRATION_CONTRACT_V1.md](docs/INTEGRATION_CONTRACT_V1.md) 和
[docs/HOST_ADAPTER_GUIDE.md](docs/HOST_ADAPTER_GUIDE.md)。本仓库只提供 wheel/SDK 通用接口，
不包含 WPS 或 Microsoft Word 宿主插件实现。

## GitHub 发布

不要直接把当前工作树整仓库推送到 GitHub。使用下列一条命令完成安全扫描、提交、推送和远程核验：

```pwsh
pwsh -NoProfile -File .\scripts\publish_to_github.ps1 -CommitMessage "说明本次修改"
```

需要先预览时增加 `-DryRun`；需要同时重跑全量测试时增加 `-Verify`：

```pwsh
pwsh -NoProfile -File .\scripts\publish_to_github.ps1 -DryRun
pwsh -NoProfile -File .\scripts\publish_to_github.ps1 -Verify -CommitMessage "说明本次修改"
```

详细规则见 `docs/GITHUB_UPLOAD_GUIDE.md`。

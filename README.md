# 公文排版 Web 服务

这是一个公文排版 Web 服务，支持 `.docx` 上传、格式识别、自动排版、任务状态查询、文件下载、管理后台和 Cloudflare Pages Worker 代理。

当前项目以 Web 服务为主。旧 PyQt 桌面端文件 `main.py`、`untitled.py`、`untitled.ui` 仍在本地保留，但不属于默认 GitHub 发布清单。

## 当前入口

- 后端入口：`server.py`
- 本地/源码前端入口：`resources/frontend/pages/index.html`
- Cloudflare Pages 部署目录：`resources/frontend/pages/`
- Pages Worker：`resources/frontend/pages/_worker.js`
- Pages 静态页面：`resources/frontend/pages/index.html`

`index1.html` 已退役，不再作为前端入口。重构前的根目录页面已保留到 `resources/frontend/legacy/index-before-restructure.html` 供人工比对。

## 主要文件

- `server.py`：兼容入口，调用 `src/docxtool/web/app.py`。
- `src/docxtool/web/app.py`：Web 服务、上传下载、任务队列、管理后台、健康检查。
- `src/docxtool/document/importer.py`：DOCX 结构识别、段落分类、元数据生成。
- `src/docxtool/document/style_config.py`：样式规则、页面设置、日志配置。
- `src/docxtool/document/engine/`：DOCX 导出和实际排版逻辑。
- `src/docxtool/security/`：上传 DOCX 安全校验。
- `src/docxtool/storage/database.py`：SQLite 路径和连接辅助。
- `src/docxtool/resources/config/default-format.json`：默认公文格式配置，随 Python 包安装。
- `requirements.txt`：Python 运行依赖。
- `run.sh`：Linux 启动脚本。
- `.env.example`：环境变量示例，不包含真实密钥。
- `docs/API.md`：HTTP 接口、鉴权、错误码说明。
- `docs/DEPLOY.md`：生产部署说明。
- `docs/UPLOAD_MANIFEST.md`：AI 修改和 GitHub 上传范围清单。
- `docs/GITHUB_UPLOAD_GUIDE.md`：安全发布到 GitHub 的操作说明。
- `scripts/publish_to_github.ps1`：PowerShell 7 安全发布脚本，默认只演练。

## 本地运行

Windows PowerShell 7：

```pwsh
pwsh -NoProfile -Command "python -m venv .venv"
pwsh -NoProfile -Command ".\.venv\Scripts\python -m pip install --upgrade pip"
pwsh -NoProfile -Command ".\.venv\Scripts\python -m pip install -r requirements.txt"
pwsh -NoProfile -Command "$env:ADMIN_TOKEN='换成你的长随机管理密钥'; $env:PROXY_SECRET='换成你的长随机代理密钥'; python server.py"
```

Linux：

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export ADMIN_TOKEN='换成你的长随机管理密钥'
export PROXY_SECRET='换成你的长随机代理密钥'
./run.sh
```

默认监听 `127.0.0.1:9527`。如需直接监听公网网卡：

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

## GitHub 发布

不要直接把当前工作树整仓库推送到 GitHub。当前本地历史里曾跟踪过 `.docx` 样例和本地文件，推荐使用：

```pwsh
pwsh -NoProfile -File .\scripts\publish_to_github.ps1
```

默认是 dry run，只演练、运行检查并展示 staged diff，不提交、不推送。

确认无误后才执行：

```pwsh
pwsh -NoProfile -File .\scripts\publish_to_github.ps1 -Push
```

详细规则见 `docs/GITHUB_UPLOAD_GUIDE.md`。

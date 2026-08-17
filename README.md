# DocxTool 公文排版服务

DocxTool 5.5.0 提供 DOCX 识别、规范化、公文排版、Web 服务、本地识别 SDK、WPS 插件和本地 TXT Reader。

文档处理主链保持单向：

```text
DOCX 物理导入
→ 逻辑分段
→ Recognition 最终语义裁决
→ Normalization
→ Final DocumentStructure / LayoutPolicy
→ Engine 渲染
```

WPS 和 Web 复用同一套 Recognition、Normalization 和 Engine，不维护第二套排版算法。Reader 完全本地运行，不接入公网账号、排版授权或文档处理链。

## 主要入口

- Web 服务：`server.py`
- Python 包：`src/docxtool/`
- Web 前端：`resources/frontend/pages/`
- WPS 客户端：`apps/wps/main.py`
- 本地 TXT Reader：`apps/reader/`
- 文档导航：[`docs/README.md`](docs/README.md)
- 当前架构：[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

重构前的旧 PyQt5 配置界面和旧前端入口已经移除。当前 WPS 登录窗口使用 `PySide2 5.15.2.1 + Qt Widgets + QSS`。

## 支持环境

- Python：`>=3.8,<3.11`
- Windows 7 SP1：Python 3.8
- Windows 8.1、10、11：Python 3.8—3.10
- Linux：用于 Web 服务部署

最终用户 WPS 客户端使用内置 Python 运行时的无控制台 GUI 单文件 EXE，不要求用户自行安装 Python。

## 本地运行

Windows PowerShell 7：

```pwsh
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
.\.venv\Scripts\python.exe server.py
```

Linux：

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install --require-hashes -r requirements.lock
export ADMIN_TOKEN='换成正式长随机密钥'
export PROXY_SECRET='换成正式长随机密钥'
python3 server.py
```

Web 服务默认监听 `127.0.0.1:9527`。生产环境中浏览器与 WPS 客户端只访问 `https://docx.toolpp.cn`；Cloudflare Pages Worker 注入 `X-Proxy-Secret` 后经 `https://origin.toolpp.cn`（仅配置 IPv4 A 记录 `43.130.232.115`）回源到 Nginx，再反向代理到 loopback 后端。Nginx 通过 Certbot 管理 Let's Encrypt HTTPS 证书。不开放 `8080` 或 `9527`，也不使用 Cloudflare Tunnel 或 Access。完整部署说明见 [`docs/DEPLOY.md`](docs/DEPLOY.md)。

## 运行数据

默认运行数据位于 `var/`：

- `var/logs/`
- `var/outputs/`
- `var/runtime/`
- `var/data/stats.db`

WPS 公网账号使用独立的 `wps_plugin.db`；本地账号、会话、设备密钥和持久结果 outbox 位于当前 Windows 用户的 DocxTool 数据目录。Reader 正文和元数据位于独立 Reader 数据目录。运行数据、用户文档、TXT 正文和 EXE 不进入 GitHub 发布范围。

## WPS 客户端

WPS 客户端每次启动都先显示登录/注册窗口。记住密码使用 Windows DPAPI；自动登录只会在窗口显示后触发一次与登录按钮相同的提交。登录成功前不启动本地服务，也不发布 WPS 加载项。

登录后启动 AccountRuntime、Control Server 和固定 `127.0.0.1:3889` 静态服务。新注册和新登录会话有效期为 7 天，心跳不续期；一键排版每次执行前必须取得公网授权，文档内容不上传公网。暂时无法上报的排版结果写入本地 SQLite 持久 outbox，心跳恢复或下一次启动后继续补报。

WPS 一键排版输出的正文和一至四级标题分别绑定 OOXML 内置 `Normal`、`Heading1`—`Heading4`，中文 WPS 顶部显示“正文、标题1、标题2、标题3、标题4”。添加版头和指定页码范围均使用本机事务，不建立第二套识别或渲染链。

WPS 开发、构建和人工验收见：

- [`apps/wps/README.md`](apps/wps/README.md)
- [`docs/WPS_REGRESSION_CHECKLIST.md`](docs/WPS_REGRESSION_CHECKLIST.md)
- [`docs/WPS_VALIDATION.md`](docs/WPS_VALIDATION.md)

构建正式客户端时必须显式传入 HTTPS Origin：

```pwsh
pwsh -NoProfile -File .\apps\wps\scripts\build-exe.ps1 -PublicApiBaseUrl https://docx.toolpp.cn
```

源码修改默认不构建 EXE；只有用户明确要求生成 EXE 时才执行冻结构建和仓库外验证。

## 本地识别 SDK

SDK 提供只读识别计划、宿主快照绑定、JSON Schema 校验和跨语言 CLI，不启动 Web 服务，也不直接修改宿主文档：

```python
from docxtool.sdk import bind_recognition_plan, recognize_docx

plan = recognize_docx("input.docx", processing_mode="structural")
binding = bind_recognition_plan(plan, {
    "host_type": "wps",
    "paragraphs": [{"host_paragraph_index": 0, "raw_text": "当前段落文字"}],
})
```

协议和宿主接入见 [`docs/SDK.md`](docs/SDK.md) 和 [`docs/INTEGRATION_CONTRACT_V1.md`](docs/INTEGRATION_CONTRACT_V1.md)。

## 验证

```pwsh
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m pytest"
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m ruff check src tests scripts"
pwsh -NoProfile -Command "node --test apps/wps/tests/run-node-tests.mjs"
pwsh -NoProfile -Command "node --test tests/frontend-format-config.test.mjs"
pwsh -NoProfile -Command "node --test tests/worker-routing.test.mjs"
```

真实 WPS、Windows 7 GUI 或视觉冒烟未运行时，不得根据自动测试填写 PASS。

## GitHub 发布

发布前先阅读 [`docs/RELEASE.md`](docs/RELEASE.md)。安全发布脚本会按白名单扫描、提交、SSH 推送并核验远端：

```pwsh
pwsh -NoProfile -File .\scripts\publish_to_github.ps1 -DryRun
pwsh -NoProfile -File .\scripts\publish_to_github.ps1 -Quick -CommitMessage "说明本次修改"
```

不要直接把当前工作树整仓库推送到 GitHub。

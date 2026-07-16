# GitHub 上传和发布指南

本文说明如何把当前项目安全发布到 GitHub。它只记录仓库地址、上传范围和命令，不保存任何 SSH 私钥、令牌或真实生产密钥。

## 1. 目标仓库

```text
git@github.com:7654321x/docxtool.git
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
pwsh -NoProfile -Command "git ls-remote git@github.com:7654321x/docxtool.git refs/heads/main"
```

只允许把 `.pub` 公钥配置到 GitHub。不要把无扩展名私钥、`.pem`、`.key`、`ADMIN_TOKEN`、`PROXY_SECRET` 或 Cookie 写进仓库。

## 3. 当前发布范围

默认发布以下类型文件：

- 项目文档：`README.md`、`docs/DEPLOY.md`、`docs/API.md`、`docs/UPLOAD_MANIFEST.md`、`docs/GITHUB_UPLOAD_GUIDE.md`、`AGENTS.md`、`CONVENTIONS.md`
- 依赖和启动：`requirements.txt`、`run.sh`
- 配置：`.env.example`、`.gitignore`、`.gitattributes`、`pytest.ini`、`ruff.toml`、`pyproject.toml`、`.github/workflows/ci.yml`
- 后端和排版核心：`server.py`、`src/docxtool/**/*.py`、`src/docxtool/resources/config/default-format.json`
- 脚本：`scripts/generate_secrets.py`、`scripts/migrate_legacy_database.ps1`、`scripts/publish_to_github.ps1`
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
- 根目录用户 `.docx`
- 未脱敏的测试 Word、用户 Word、日志正文

`.gitignore` 只影响未跟踪文件。已经被 Git 跟踪或已经进入历史的文件，不会因为写入 `.gitignore` 自动消失。

## 5. 推荐发布命令

先演练：

```pwsh
pwsh -NoProfile -File .\scripts\publish_to_github.ps1
```

演练会：

- 临时克隆 `git@github.com:7654321x/docxtool.git`
- 清空临时克隆工作区，但保留 `.git`
- 复制允许发布的真实项目文件
- 运行 `pytest`、Ruff、Node Worker 测试
- 验证 Python 包构建
- 执行 `git diff --cached --check`
- 展示 staged diff
- 不提交、不推送
- 结束后清理临时目录

确认无误后推送：

```pwsh
pwsh -NoProfile -File .\scripts\publish_to_github.ps1 -Push
```

`-Push` 才会提交并推送。脚本不会 force push；如果远端分支在临时克隆后发生变化，脚本会停止。

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

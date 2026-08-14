# DocxTool 发布指南

本文是 GitHub 发布范围、SSH 操作和安全边界的唯一说明。实际发布范围由 `scripts/publish_to_github.ps1` 的允许清单执行。

## 目标仓库与 SSH

```text
git@github.com:7654321x/docxtool.git
```

```pwsh
pwsh -NoProfile -Command "ssh -T git@github.com"
pwsh -NoProfile -Command "git ls-remote git@github.com:7654321x/docxtool.git refs/heads/main"
```

只允许把 `.pub` 公钥配置到 GitHub。私钥、`.pem`、`.key`、Token、Cookie、`ADMIN_TOKEN` 和 `PROXY_SECRET` 不得进入仓库、日志或发布参数。

## 发布范围

必须发布：

- 根入口、配置、锁文件、启动脚本、CI、CHANGELOG 和 AGENTS；
- `src/docxtool/**`、公开资源、Schema 和前端 Pages；
- `apps/wps/**` 与 `apps/reader/**` 的公开源码、资源、测试和可复现构建输入；
- `tests/**` 和正式 `scripts/**`；
- 当前 `docs/` 主文件、`docs/design/`、`docs/examples/` 和 `docs/migration/`；
- `WPS_SERVER_PRD.md`、`WPS_SERVER_TECHNICAL_DESIGN.md`、`WPS_READER_PRD.md` 和 `公文格式规范.md`。

禁止发布：

```text
.env 和真实密钥
SSH/证书私钥
*.db、*.sqlite、运行数据和日志
.venv、node_modules、缓存
build、dist、EXE、wheel 临时产物
用户 DOCX、TXT 正文和未脱敏 fixture
apps/wps/runtime/runtime-config.js
本机 WPS publish.xml、authaddin.json
local_recycle/
```

`.gitignore` 不能清除已经进入 Git 历史的敏感内容；历史清理必须单独授权。

## 发布前检查

- 核对当前分支、远端和用户要求的发布范围。
- 确认新增正式文件已加入发布脚本允许清单。
- 确认用户文档、运行数据、EXE 和私密配置未进入发布范围。
- 源码修改默认不构建 EXE；仅用户明确要求时生成冻结包。
- 当前工作树既有修改属于用户内容，不使用破坏性恢复命令。

## 命令

只预览：

```pwsh
pwsh -NoProfile -File .\scripts\publish_to_github.ps1 -DryRun
```

快速发布：

```pwsh
pwsh -NoProfile -File .\scripts\publish_to_github.ps1 -Quick -CommitMessage "说明本次修改"
```

完整门禁发布：

```pwsh
pwsh -NoProfile -File .\scripts\publish_to_github.ps1 -Verify -CommitMessage "说明本次修改"
```

脚本按允许清单创建干净发布副本，执行安全扫描、差异检查、提交、SSH 推送和远端提交号核验；不执行 force push，远端分支变化时停止。

## 发布后核验

```pwsh
pwsh -NoProfile -Command "git status --short --branch"
pwsh -NoProfile -Command "git ls-remote git@github.com:7654321x/docxtool.git refs/heads/main"
```

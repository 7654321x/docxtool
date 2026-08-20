# DocxTool 发布指南

本文是 GitHub 发布范围、SSH 操作和安全边界的唯一说明。`scripts/publish_to_github.ps1` 自动收集当前仓库全部非忽略 Git 变更，并通过禁止项扫描、部署范围检查和暂存完整性检查执行发布边界。

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

`docxtool/` 是部署包镜像，不属于普通发布范围。只有用户明确要求“发布新版本”时，才同步并将其纳入发布。

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
- 先获取最新 `origin/main`，确认本地 `main` 的提交号与其完全一致；不自动合并、变基或强制同步。
- 暂存区必须为空，避免把用户预先暂存的内容混入发布提交。
- 使用 `-DryRun` 时确认显示的全部待发布文件都属于本轮修改；新增正式文件会自动进入范围，无需维护发布清单。
- 发布脚本拒绝用户 DOCX、运行数据、EXE、wheel、压缩包、私密配置及其他禁止项，并在暂存后确认没有遗漏任何非忽略变更。
- 源码修改默认不构建 EXE；仅用户明确要求时生成冻结包。
- 当前工作树既有修改属于用户内容，不使用破坏性恢复命令。

## 命令

只预览：

```pwsh
pwsh -NoProfile -File .\scripts\publish_to_github.ps1 -DryRun
```

普通发布（默认使用）：

```pwsh
pwsh -NoProfile -File .\scripts\publish_to_github.ps1 -CommitMessage "说明本次修改"
```

发布新版本并同步部署包：

```pwsh
pwsh -NoProfile -File .\scripts\publish_to_github.ps1 -IncludeDeploymentPackage -CommitMessage "发布 vX.Y.Z"
```

完整验收发布（仅用户明确要求时使用）：

```pwsh
pwsh -NoProfile -File .\scripts\publish_to_github.ps1 -Verify -CommitMessage "说明本次修改"
```

普通发布默认即为 Quick，只需要一条带提交说明的命令；`-Quick` 参数保留为旧调用兼容入口。流程固定按以下顺序执行：

1. 核验当前本地仓库、`main` 分支、SSH 远端和本地/远端基线。
2. 自动收集全部 tracked、deleted 和未忽略 untracked 变更，检查部署范围及禁止发布内容。
3. Quick 模式自动运行 `scripts/verify_changed.ps1`；验证失败立即停止，不创建提交。
4. 完整暂存全部待发布变更，运行 staged diff 检查，并确认工作树没有遗漏文件。
5. 在本地创建提交，使 `git log` 能直接看到本次发布。
6. 通过 SSH 推送 `main`，核验远端提交号等于本地提交号，并确认工作树干净。

`-Verify` 使用全量测试、WPS 和 EXE 门禁替代 Quick changed-path 验证。除非用户明确要求，不使用完整验收发布。

禁止只在临时克隆中创建提交。脚本不执行 force push，也不在 commit 后固定执行 `git pull --rebase`：发布前基线不一致时立即停止；若远端在本地提交期间发生变化，普通 push 会安全失败并保留本地提交，等待人工审阅后再处理。提交前检查失败会撤销本轮暂存。

## 发布后核验

```pwsh
pwsh -NoProfile -Command "git status --short --branch"
pwsh -NoProfile -Command "git ls-remote git@github.com:7654321x/docxtool.git refs/heads/main"
```

脚本成功输出固定包含：commit SHA、commit message、branch、验证模式和 working tree clean 状态。

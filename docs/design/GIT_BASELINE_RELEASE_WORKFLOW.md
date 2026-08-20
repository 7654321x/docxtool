# Git 本地基线与发布流程技术设计

## 目标

修复临时发布克隆绕过本地 Git 索引的问题，使本地仓库成为每次 GitHub 发布提交的唯一来源。

## 范围

- 发布前获取最新 `origin/main`，要求当前本地 `main` 与其提交号完全一致。
- 发布脚本自动收集当前仓库全部非忽略 Git 变更，拒绝已有暂存内容、部署范围错误及敏感或构建产物。
- 暂存后再次检查工作树，任何漏掉的变更都会使发布失败。
- 先创建可在本地查询和回退的 Git 提交，再通过 SSH 推送到 GitHub。
- 推送前再次确认远端基线未变化，推送后核验远端提交号等于本地提交号。
- 本地 EXE、运行数据、用户文档和密钥不进入提交。

## 接口与兼容性

`scripts/publish_to_github.ps1` 保留 `-DryRun`、`-Quick`、`-Verify`、`-Branch` 和 `-CommitMessage` 入口。`-DryRun` 只检查和展示全部待发布差异，不修改 Git 索引；普通真实发布自动执行 changed-path 验证。默认远端使用 SSH 地址。

不修改业务 HTTP、SDK、WPS、SQLite 或文档处理协议。

## 失败边界

- 本地分支不是目标分支、本地提交落后或领先远端、暂存区已有内容、远端不是 SSH 地址时立即停止。
- 待发布变更包含禁止发布类型，或部署镜像变更未显式使用 `-IncludeDeploymentPackage` 时立即停止。
- 提交前远端发生变化时停止，不自动合并、变基或强制推送。
- 推送后远端提交号不一致时明确失败。
- 不在提交后固定执行 `git pull --rebase`；若远端在提交期间变化，普通 push 会安全失败并保留本地提交。

## 验证与验收

- Dry-run 不产生提交、不推送且不改变暂存区。
- 正式发布后 `git rev-parse HEAD`、`git rev-parse origin/main` 和远端 `refs/heads/main` 相等。
- 缺失的正式拆分模块和 WPS 资源进入 Git 跟踪，本地 EXE 保持未发布。
- 发布脚本测试、架构文档测试、聚焦 Python/Node 测试、Ruff、编译检查和 `git diff --check` 通过。

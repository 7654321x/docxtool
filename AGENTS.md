# AGENTS.md

本文件记录本项目的本地协作规则，适用于仓库根目录及其子目录。

## 基本原则

1. 先阅读相关源码、配置和测试，再修改代码。
2. 保持改动范围最小，不做与当前任务无关的重构。
3. 不为了通过测试而删除测试、降低安全限制或绕过鉴权逻辑。
4. 不修改真实密钥、真实环境变量、生产配置或用户私有数据。
5. 不执行 `git commit` 或 `git push`，除非用户明确要求。
6. 不静默忽略测试失败；失败时说明命令、错误和已排查内容。

## Windows 命令

在 Windows 上需要显式调用 PowerShell 时，固定使用 PowerShell 7：

```pwsh
pwsh -NoProfile -Command "..."
```

不要默认调用 Windows PowerShell 5.1。只有在明确要求兼容性测试时，才调用 `powershell.exe`。

## 常用检查

```pwsh
pwsh -NoProfile -Command "Get-Location"
pwsh -NoProfile -Command "git status --short --branch"
pwsh -NoProfile -Command "git log -1 --oneline"
pwsh -NoProfile -Command "python -m pytest"
pwsh -NoProfile -Command "python -m ruff check src tests scripts"
pwsh -NoProfile -Command "node --test tests/worker-routing.test.mjs"
```

## 数据和密钥保护

不要提交或上传：

- `.env`
- 真实 `ADMIN_TOKEN`、`PROXY_SECRET`
- API key、访问令牌、Cookie、会话 ID
- SSH 私钥、证书私钥
- `stats.db`、日志、生成的 Word 文件
- 用户隐私文档正文

## GitHub 发布

GitHub 发布以 `docs/GITHUB_UPLOAD_GUIDE.md` 和 `scripts/publish_to_github.ps1` 为准。默认使用临时干净克隆发布，不直接推送当前工作树。

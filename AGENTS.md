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

## 重复问题处理

1. 遇到已经出现过、或明显可能反复出现的问题时，先回看本文件和相关项目文档，确认是否已有处理约定。
2. 如果本次形成了可复用的解决方式，应在完成代码修复后，把简明规则补充到 `AGENTS.md` 或更合适的项目文档中。
3. 记录内容应包含触发场景、推荐处理方式和必要的验证命令，避免只写结论。
4. 对 `python-docx`、OOXML、页眉页脚、分节、字段、样式、关系包等问题，优先查官方文档，再决定使用高层 API 还是直接 OOXML。
5. 不为沉淀经验而下载大型资料、提交本地资料副本、或把用户私有文件内容写入文档。

## 公文结构排版回归

1. 触发场景：头部出现“区政协办公室主任  李弟弟”这类较长“职务 + 连续空格 + 姓名”时，应识别为 `role_name`，不要要求把具体人名写入格式配置。
2. 触发场景：正文后出现“责任单位：区政府责任单位：商务局”或外层带引号时，应识别为 `responsibility_line`，归一为多行 `责任单位：...`，导出时使用 `DCT-Responsibility`。
3. 触发场景：`1.测试` 后接 `（1）测试` 时，完整层级下应分别保留为 `heading3`、`heading4`；导出不得在四级标题后生成真实空段。
4. 落款单位、成文日期、附件说明和附件正文页的识别顺序按 `tests/test_signature_detection.py` 的固定结构回归维护；参考旧目录时只读代码和配置，不读取旧目录用户 DOCX。
5. 修改上述逻辑后至少运行：

```pwsh
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m pytest tests/test_signature_detection.py tests/test_structured_layout_quality.py tests/test_importer_heading_flow.py tests/test_engine_heading_spacing.py"
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m ruff check src tests scripts"
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

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

6. 触发场景：二级标题在句号后紧接行内正文时，导入和导出统一以“句号后至少 5 个非空字符”为正文阈值；标题部分使用二级标题规则，正文部分使用正文规则，不能因长度区间不同而整段加粗。
7. 触发场景：用户通过浏览器将二、三级标题设为不加粗时，导出必须尊重该配置；不要在编号后处理阶段无条件把 run 设为粗体。修改后至少运行：

```pwsh
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m pytest tests/test_structured_layout_quality.py tests/test_config_driven_styles.py tests/test_structural_styles.py"
```

8. 触发场景：一级标题无论后接下级标题还是正文，都不要写入 `keepNext` / `keepLines`；允许一级标题单独占用页末最后一行。遇到分页空白时，使用脱敏生成文档渲染 PNG 验证，不读取用户 DOCX。
9. 触发场景：文尾正文与落款单位被软换行、制表符或手动分页符混合在同一 Word 段落中，且下一可见内容以成文日期开头时，应将末行短单位名拆为 `sign_org`；分页符不得阻止该结构拆分。
10. 触发场景：标题、职务姓名或文末落款通过 Word 软换行粘在同一段时，应先利用“标题区 + 职务关键词/连续空格姓名”或“正文尾部 + 下一段日期”拆成结构行，再分类；不要维护具体人名或单位全称名单。正式尾部顺序保持“正文 → 附件说明 → 落款单位 → 日期”；附件说明首段相对正文段前 1 行，后续附件项段前为 0，落款块间距由落款单位段控制，不插入真实空段。
11. 触发场景：段落中存在 `cy=0` 或其他零尺寸 DrawingML 图片残留时，不得把整段视为图片段落而跳过文字分类；仅真实可见图片走图片保留路径。段首/段尾孤立软换行应在导入时剔除，不能通过 `inline_tokens` 写回造成标题后空行或正文首行缩进失效。
12. 尾部结构顺序不仅在导入后归一，还必须在导出前再次强制校验；遇到 `sign_org + sign_date + attachment_note + item*` 时，最终输出固定改为 `attachment_note + item* + sign_org + sign_date`，防止不同任务路径绕过导入后处理。
13. 表格当前只允许原样透传，不应用字体、列宽、边框、行高或对齐优化；复制时必须迁移表格 XML 引用的全部关系部件。任何关系无法解析或迁移时必须中止导出，禁止记录警告后继续生成可能缺数据的 DOCX。
14. 图片段落以及紧邻表格/图片下方的“表一、表1、图一、图2”等题注属于受保护对象；允许因正文重排改变位置，不得修改对象尺寸、题注文字、字体、字号、对齐或关系资源，也不得执行上标、英数字体、结构样式或清理后处理。题注段落间距是唯一例外，导出时统一显式写入段前 0、段后 0。
15. 表格单元格可能没有显式 `w:pStyle`，而依赖源文档默认段落样式；重建输出文档时必须复制表格引用样式及继承链，并为这类单元格绑定隔离后的源默认样式。仅复制 `w:tbl` 会导致其回退为输出正文样式，不属于完整保留。
16. 触发场景：开启奇偶页不同并写入外侧页码时，必须复用页脚自动创建的安全空段，不能保留空段后再追加页码段；否则 WPS 可能令偶数页正文少排一行。修改后运行 `tests/test_page_number_engine.py`，并检查奇、偶页脚均无多余空段。
17. 触发场景：16 pt 正文在 15.6 cm 版心中要求每行 28 字时，`w:docGrid/@w:charSpace` 必须按 OOXML 的“目标字距与 Normal 字号之差（磅）× 4096”计算，不能直接写 twip 差值；应读取最终 OOXML 整数页面尺寸和边距并向更窄方向取整，默认配置结果为 `-842`，避免 WPS 因临界超宽反算成 27 字。通过 `tests/test_structured_layout_quality.py` 验证。
18. 触发场景：附件说明首项和续项必须分别使用 `DCT-AttachmentNote`、`DCT-AttachmentNoteItem`；首项默认段前 1 行，续项默认段前 0。不能共用首项样式后仅靠直接格式覆盖，否则 WPS 会从样式继承段前间距，造成每个附件项之间多空一行。

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

发布安全扫描必须精确允许仓库根目录的 `.env.example`，同时继续禁止 `.env` 和其他 `.env.*` 文件；修改发布清单或脚本后，必须先执行不带 `-Push` 的演练，再执行正式推送。

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
14. 表格或纯图片段落下方紧邻的一行“表一、表1、图一、图2”等题注属于受保护对象；保护只允许覆盖这一行，题注本身不得继续充当下一行的题注锚点。含“正文文字 + 行内图片”的混合段落不是纯图片段落，不能保护下一行；未绑定对象的“表/图编号行”按正文分类并清除颜色、异常字号等直接格式。受保护对象允许因正文重排改变位置，不得修改对象尺寸、题注文字、字体、字号、对齐或关系资源，也不得执行上标、英数字体、结构样式或清理后处理。题注段落间距是唯一例外，导出时统一显式写入段前 0、段后 0。修改后运行 `tests/test_body_order_export.py`，并渲染包含“表格→表注→混合图片段→普通正文”的样本检查。
15. 表格单元格可能没有显式 `w:pStyle`，而依赖源文档默认段落样式；重建输出文档时必须复制表格引用样式及继承链，并为这类单元格绑定隔离后的源默认样式。隔离样式的 ID 和名称都不得继续使用 `Normal`，否则 WPS 可能用源文档 10.5 pt 默认样式反算文档网格并显示每行 42 字。仅复制 `w:tbl` 会导致其回退为输出正文样式，不属于完整保留。
16. 触发场景：开启奇偶页不同并写入外侧页码时，必须复用页脚自动创建的安全空段，不能保留空段后再追加页码段；否则 WPS 可能令偶数页正文少排一行。修改后运行 `tests/test_page_number_engine.py`，并检查奇、偶页脚均无多余空段。
17. 触发场景：16 pt 正文在 15.6 cm 版心中要求每行 28 字时，`w:docGrid/@w:charSpace` 必须按 OOXML 的“目标字距与 Normal 字号之差（磅）× 4096”计算，不能直接写 twip 差值；应读取最终 OOXML 整数页面尺寸和边距并向更窄方向取整，默认配置结果为 `-842`，避免 WPS 因临界超宽反算成 27 字。通过 `tests/test_structured_layout_quality.py` 验证。
18. 触发场景：附件说明首项和续项必须分别使用 `DCT-AttachmentNote`、`DCT-AttachmentNoteItem`；首项默认段前 1 行，续项默认段前 0。不能共用首项样式后仅靠直接格式覆盖，否则 WPS 会从样式继承段前间距，造成每个附件项之间多空一行。
19. 触发场景：正文前部引用“某通知（川组通〔2025〕51号）”等文件编号时，不能据此判定已有未知版头；只有整段为结构化发文字号（可同段附签发人）时才作为版头检测信号。无已有版头且配置启用时，应在首个标题前插入托管版头，并保持标题及后续内容节点的原有顺序。
20. 版头开关采用单一语义：开启时移除检测到的已有正文流版头并按当前配置重新生成；关闭时不新增、不替换，已有版头原样保留。后端必须强制执行该语义，不能依赖前端额外的“替换受管版头”开关。
21. 触发场景：多行主标题后紧接“职务 + 姓名”的 `role_name` 时，姓名职务段应显式设置段前 1 行；后接正文或标题等主体内容时段后 1 行，不插入真实空段，且下一段不得再次叠加段前间距。后接头部日期 `date_line` 时段后保持 0，使职务姓名与日期相邻。
22. 版头发文机关标志默认使用 32 pt 方正小标宋简体，标志段自身段前段后均为 0；标志上方用 3 个 `DCT-LetterheadSpacer` 固定行空段、下方用 2 个固定行空段。发文字号和每行签发人段前段后均为 0。红线前标准 4 mm 仍使用物理距离，红线后使用 2 行间距。
23. 版头仅在首页首个标题前插入正文流段落，不创建专用节，也不得重设页面尺寸、页边距或文档网格；这些参数始终复用全局页面设置。版头生成晚于通用西文字体后处理，因此生成后必须补做同一轮数字/拉丁字体扫描，并显式保持中文 `eastAsia` 字体与 `ascii/hAnsi=Times New Roman`。
24. 附件正文页的 `attachment_title` 默认段前、段后各 1 行；间距写在 `DCT-AttachmentTitle` 及段落直接格式中，不插入真实空段，也不得再通过“标题后留白”逻辑给后续 `attachment_body` 叠加一行。
25. 版头机关列表只禁止删除最后一个机关；联合发文从两个机关删至一个时，前端必须自动切回单一机关并将剩余机关设为主办机关，同时清理被删机关的签发人。添加第二个机关时必须同步切换为联合发文，避免提交与机关数量冲突的配置。两个及以上机关均应显示有效的上下移动按钮；机关跨越首位时必须同步将新的第一位设为主办机关，保证前端顺序与后端“主办机关优先”归一化结果一致。
26. 触发场景：文尾日期、附件说明、附件项和附件正文页被 Word 手动换行粘在同一物理段落时，只要前两条可见行包含成文日期且后续出现附件边界，就必须拆成独立结构行；安全标点规范化不得把 `1.测试`、`附件：2.材料` 等结构编号中的句点改为句号，否则会阻断标题和附件识别。编号后紧邻的重复句点如 `4..标题` 应安全折叠为 `4.标题`。修改后至少运行 `tests/test_punctuation_engine.py`、`tests/test_signature_detection.py` 和 `tests/test_body_order_export.py`。
27. 触发场景：独立成行的 `A：B` 键值段落（责任单位、联系人、联系电话等）统一使用三号、固定 28 磅、段前段后 0；`A：` 加粗、`B` 不加粗。单行使用首行缩进 2 字符；多条键值内容通过手动换行保存在同一段落时，使用等效的 2 字符段落左缩进，使每条可见行都对齐，不能让第二条及后续行顶格。
28. 触发场景：导入包的 `word/_rels/document.xml.rels` 含 `Target="../NULL"` 时，必须用 XML 解析器按 `Target` 属性删除关系，不能用只匹配无前缀 `<Relationship>` 的正则；序列化后的关系节点常带 `ns0:` 等命名空间前缀。修改后运行 `tests/test_importer_broken_relationships.py` 和 DOCX 完整性测试。
29. 已有外部版头检测必须限制在正文流开头的连续有界前缀；“红色机关标志 + 结构化发文字号”或“结构化发文字号 + 红色段落边框分割线”可作为强信号。开头只有整行结构化发文字号时标记为不完善版头；只有符合机关名称形态的“××文件”时，还必须通过后续独立标题或文号、签发人、红线等版头信号进行上下文验证，若其后直接进入主送机关或正文则不得按版头删除。正文中的文件编号引用和“关于……文件”标题不得触发。单个红字、图片或红色边框不足以认定版头。识别成功后，保护终点只能到发文字号/签发人及其后紧邻的分割线，后续红色、大字号或带边框的公文标题不得扩大保护范围。修改后运行 `tests/test_letterhead_engine.py`，并用含乱格式红色标题的样本确认标题仍使用 `DCT-Title`。
30. 横向分节沿用纵向页面参数时，应按物理边旋转页边距：横向上=纵向左、下=纵向右、左=纵向下、右=纵向上；不得只交换页宽页高。每个分节的 `w:docGrid/@w:charSpace` 必须依据该节最终 OOXML 页宽和左右边距单独计算，不能复用纵向 `-842`。修改后运行 `tests/test_body_order_export.py` 和 `tests/test_structured_layout_quality.py`。

## 可移动服务器部署

1. 后端入口、启动脚本、数据库、日志、输出和运行时目录不得写死盘符、用户目录、服务器 IP 或部署目录。
2. Windows 启动统一使用根目录 `run.ps1`，脚本通过 `$PSScriptRoot` 定位项目；`.env`中的相对运行路径统一相对于项目根解析。
3. Nginx模板只允许固定本机上游 `127.0.0.1:9527`，服务器公网地址通过 Cloudflare Pages 的 `BACKEND_BASE_URL`配置，不写入源码。
4. 修改路径或部署入口后至少运行 `tests/test_paths.py`，并从项目目录之外执行 `pwsh -NoProfile -File <项目目录>\run.ps1 -CheckOnly`。

## IDE 快捷方式启动失败

1. 触发场景：Codex 右上角或系统快捷方式启动 PyCharm 时出现 `Start Failed`，并指向 `AppData\Local\JetBrains\PyCharm*\.port`、`DirectoryLock` 或本地 socket 错误。
2. 先确认系统快捷方式的目标仍是有效的 `pycharm64.exe`，再检查是否存在无窗口、无响应的 `pycharm64` 残留进程；只停止已确认的残留 PID，不终止其他 IDE、Java 或 Python 进程。
3. 仅在 PyCharm 进程完全停止后删除对应版本目录中的异常 `.port` 文件，再通过正式可执行文件打开项目验证。不要删除整个 JetBrains 配置目录，也不要使用“Reset Settings & Plugins”作为默认修复方式。
4. 验证命令应确认新 `pycharm64` 进程 `Responding=True` 且出现项目窗口标题。

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

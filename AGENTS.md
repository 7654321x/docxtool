# AGENTS.md

本文件记录本项目的本地协作规则，适用于仓库根目录及其子目录。

## 基本原则

1. 先阅读相关源码、配置和测试，再修改代码。
2. 保持改动范围最小，不做与当前任务无关的重构。
3. 不为了通过测试而删除测试、降低安全限制或绕过鉴权逻辑。
4. 不修改真实密钥、真实环境变量、生产配置或用户私有数据。
5. 不执行 `git commit` 或 `git push`，除非用户明确要求。
6. 不静默忽略测试失败；失败时说明命令、错误和已排查内容。

## 需求前提与事实边界

1. 执行前根据当前源码、配置、测试和实际运行结果核实需求中的关键前提；不得把用户描述直接当作已验证事实。
2. 发现前提错误、逻辑冲突或关键信息缺失时，应明确指出证据和影响。若不影响目标，可基于正确事实继续执行；只有会实质改变结果时才停止请求确认。
3. 回答和报告应区分已验证事实、合理推断和主观建议。已验证事实必须有源码、测试、日志或官方文档支持；合理推断必须说明尚未直接验证；方案选择不得表述成客观事实。
4. 不因迎合用户而认可有明显缺陷的方案。存在正确性、数据损失、兼容性或维护风险时，应直接说明，并提供范围最小的可行替代方案。
5. 只提醒会实质影响当前目标的变量、成本和风险，不输出与任务无关的泛化警告，也不得借此扩大实现范围。

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

## 迁移专项执行规则

适用于声明为“机械迁移”或“行为保持重构”的识别、导入、分段、规范化和渲染链路工作。详细门禁、快照方法和报告格式见 `docs/migration/codex-workflow.md`；Phase A-2 当前状态见 `docs/migration/phase-a2-checklist.md`。

1. 每轮只完成一个主要职责，例如抽取一个模块、迁移一个兼容入口或补齐一组等价测试；不得在同一轮顺带开始下一阶段或行为优化。
2. 机械迁移只允许调整文件归属、导入关系、兼容 facade 和等价测试，不得改变业务规则、默认配置、公开协议、文字处理、识别结果或渲染输出。
3. 默认只运行当前职责的快速测试和相关静态检查；达到模块、阶段或发布里程碑时，按 `docs/migration/codex-workflow.md` 执行对应的扩展门禁。
4. 快照或测试发现未解释的行为差异时，立即标记为 `blocked`，保存脱敏证据并停止该迁移项；不得通过修改基线、放宽断言或夹带行为补丁继续推进。
5. 默认情况下，当前微任务通过门禁后停止。用户明确授权 Looper 时，可在同一模块内连续执行最多 3–5 个单职责微任务；每个微任务仍须独立执行快速门禁并更新日志。完成当前模块、出现未解释差异或达到停止条件后立即停止，不自动进入下一模块或下一阶段，也不自动执行 `git commit` 或 `git push`。提交、发布和下一阶段均须由用户明确要求。
6. 每轮结束后更新对应阶段清单，记录已完成项、待办项、新文件位置、执行命令和结果；不得记录用户 DOCX 正文、绝对用户路径、密钥或日志原文。

## 文档维护与扩展

1. `docs/README.md` 是 `docs` 的导航入口和文档职责索引；新增或调整项目文档前先阅读该文件，避免复制既有规范。
2. `AGENTS.md` 只保存跨任务强制规则；架构说明、发布门禁、回归问题、SDK 契约和阶段状态分别维护在其对应文档中，不在多个位置重复维护同一事实。
3. 既有文档路径视为稳定链接。除非用户明确同意迁移和更新全部引用，否则通过索引、交叉链接和目录入口整理，而不移动或重命名旧文件。
4. 新增长期维护文档时，必须在 `docs/README.md` 登记职责和阅读入口；如属于发布范围，还必须同步更新 `docs/UPLOAD_MANIFEST.md`、`docs/GITHUB_UPLOAD_GUIDE.md` 和 `scripts/publish_to_github.ps1`。
5. 每份规范文档必须明确适用范围、唯一职责、上位规则和验证入口；不得写入用户正文、真实密钥、绝对用户路径或运行日志原文。

## 接口与依赖边界回归

1. 调用可替换导出器时，只能在执行前通过 `inspect.signature()` 或明确 adapter 适配旧参数；不得捕获导出器函数体中的任意 `TypeError` 后用精简参数重试。每个任务最多调用导出器一次，内部 `TypeError` 必须进入正常任务错误边界。
2. `web.handler` 和 `web.compatibility` 必须能在全新解释器中独立导入。旧 `web.app` monkeypatch 通过中立 hook provider 在调用时同步，禁止在模块加载时读取 `sys.modules["docxtool.web.app"]`。
3. 文档层保持 `models/analysis/text → importing/segmentation → recognition → normalization → engine` 的单向依赖；`document/pipeline`、`document/recognition`不得导入`document/engine`，`document/engine`不得从 importer facade 获取共享模型。修改相关边界后运行 `tests/test_architecture_docs.py tests/test_importer_facade.py tests/test_application_process_document.py tests/test_web_app_facade.py`，并执行全模块独立导入扫描。

## 本地回收站

1. 仓库根目录 `local_recycle/` 是仅供本机使用的回收站，已整体加入 `.gitignore`，不得提交或通过发布脚本上传。
2. 只允许移入未跟踪的临时补丁、一次性快照、备份副本和可重新生成的本地产物；移动前必须确认它们不是待提交的新源码、测试、配置或文档。
3. 已被 Git 跟踪但存在修改的文件必须保留在原路径，不能通过移动到回收站来制造干净工作树；应通过正常提交、审阅或用户明确授权的恢复流程处理。
4. 回收站默认永久保留，不自动清空。每次移动后运行 `git status --short`，确认没有误删受管理文件，也没有隐藏应发布的新文件。

## 重复问题处理

1. 遇到已经出现过、或明显可能反复出现的问题时，先回看本文件和相关项目文档，确认是否已有处理约定。
2. 如果本次形成了可复用的解决方式，应在完成代码修复后，把简明规则补充到 `AGENTS.md` 或更合适的项目文档中。
3. 记录内容应包含触发场景、推荐处理方式和必要的验证命令，避免只写结论。
4. 对 `python-docx`、OOXML、页眉页脚、分节、字段、样式、关系包等问题，优先查官方文档，再决定使用高层 API 还是直接 OOXML。
5. 不为沉淀经验而下载大型资料、提交本地资料副本、或把用户私有文件内容写入文档。
6. 用户每次反馈的问题在确认根因后，都必须把脱敏后的触发场景、处理规则和必要验证命令写入 `AGENTS.md` 或明确引用的项目问题清单；不以问题大小或是否可能复现为由省略记录。

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

6. 触发场景：明确二级标题在句号后紧接行内正文时，导入和导出统一以“句号后至少 5 个非空字符”为正文阈值；若源内容位于同一个 Word 物理段落，输出必须保持一个物理段，只在句号处切换 run 格式，标题部分完整使用二级标题字体、字号和粗体配置，正文部分完整使用正文配置。只有源文件本来就是两个物理段落时才保持“二级标题段 + 正文段”，不得因内容形态自动拆段或反向合并。可见`（一）`、明确二级标题样式和原生`（%1）`模板适用；泛化列表层级不得据此升级。修改后运行 `tests/test_segment_boundaries.py tests/test_engine_inline_effects.py tests/test_engine_heading_spacing.py tests/test_native_numbering.py tests/test_sdk.py`。
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
22. 下行文版头按本地首页图解采用明确行距结构：发文机关标志上方生成 3 个固定 28 pt 空行；标志使用 32 pt 方正小标宋简体、红色、居中，必须在版心内单行完整显示；过长时仅允许在 55%～100% 范围内横向压缩，不得为了铺满版心自动放大字号，仍无法排入时明确失败。标志段固定行距必须等于实际标志字号，即默认 32 pt 字号对应 32 pt 固定行距，禁止套用 28 pt 正文行距；标志下方生成 2 个当前正文行距空行，随后紧接发文字号。上述空行、标志和下行文发文字号的段前、段后、文本之前、文本之后及首行缩进均显式为 0；空行自身固定行距和标志承载文字所需行距不属于“段前/段后”。红线前 4 mm、红线至首个标题为当前正文行距 × 2 等已有明确距离继续保留，首个标题不得再叠加段前间距。除这些版头元素外，不改页面参数、正文或其他未提及格式。
23. 版头仅在首页首个标题前插入正文流段落，不创建专用节，也不得重设页面尺寸、页边距或文档网格；这些参数始终复用全局页面设置。版头生成晚于通用西文字体后处理，因此生成后必须补做同一轮数字/拉丁字体扫描，并显式保持中文 `eastAsia` 字体与 `ascii/hAnsi=Times New Roman`。
24. 附件正文页的 `attachment_title` 默认段前、段后各 1 行；间距写在 `DCT-AttachmentTitle` 及段落直接格式中，不插入真实空段，也不得再通过“标题后留白”逻辑给后续 `attachment_body` 叠加一行。
25. 当前产品界面只启用单机关发文：Web 配置只提交一个主办机关，WPS“添加版头”表单只接受一行机关标志。Core 保留联合发文数据能力以兼容历史配置，但自动识别或 WPS 检查发现多机关源版头时必须明确返回不支持，不能把第一机关当成完整版头后覆盖原文。
26. 触发场景：文尾日期、附件说明、附件项和附件正文页被 Word 手动换行粘在同一物理段落时，只要前两条可见行包含成文日期且后续出现附件边界，就必须拆成独立结构行；安全标点规范化不得把 `1.测试`、`附件：2.材料` 等结构编号中的句点改为句号，否则会阻断标题和附件识别。编号后紧邻的重复句点如 `4..标题` 应安全折叠为 `4.标题`。修改后至少运行 `tests/test_punctuation_engine.py`、`tests/test_signature_detection.py` 和 `tests/test_body_order_export.py`。
27. 触发场景：独立成行的 `A：B` 键值段落（责任单位、联系人、联系电话等）统一使用三号、固定 28 磅、段前段后 0；`A：` 加粗、`B` 不加粗。单行使用首行缩进 2 字符；多条键值内容通过手动换行保存在同一段落时，使用等效的 2 字符段落左缩进，使每条可见行都对齐，不能让第二条及后续行顶格。
28. 触发场景：导入包的 `word/_rels/document.xml.rels` 含 `Target="../NULL"` 时，必须用 XML 解析器按 `Target` 属性删除关系，不能用只匹配无前缀 `<Relationship>` 的正则；序列化后的关系节点常带 `ns0:` 等命名空间前缀。修改后运行 `tests/test_importer_broken_relationships.py` 和 DOCX 完整性测试。
29. 已有外部版头检测必须限制在正文流开头的连续有界前缀；“红色机关标志 + 结构化发文字号”或“结构化发文字号 + 红色段落边框分割线”可作为强信号。开头只有整行结构化发文字号时标记为不完善版头；只有符合机关名称形态的“××文件”时，还必须通过后续独立标题或文号、签发人、红线等版头信号进行上下文验证，若其后直接进入主送机关或正文则不得按版头删除。正文中的文件编号引用和“关于……文件”标题不得触发。单个红字、图片或红色边框不足以认定版头。识别成功后，保护终点只能到发文字号/签发人及其后紧邻的分割线，后续红色、大字号或带边框的公文标题不得扩大保护范围。修改后运行 `tests/test_letterhead_engine.py`，并用含乱格式红色标题的样本确认标题仍使用 `DCT-Title`。
30. 横向分节沿用纵向页面参数时，应按物理边旋转页边距：横向上=纵向左、下=纵向右、左=纵向下、右=纵向上；不得只交换页宽页高。每个分节的 `w:docGrid/@w:charSpace` 必须依据该节最终 OOXML 页宽和左右边距单独计算，不能复用纵向 `-842`。修改后运行 `tests/test_body_order_export.py` 和 `tests/test_structured_layout_quality.py`。
31. 版头开关关闭时，只保留首页开头已识别的外部版头；若连续有界区域仅包含标准或兼容发文字号、可选签发人且没有红色分割线，则只在最后一行签发人后补一个 `DCT-LetterheadSeparator`，不得替换机关、文号或签发人。已有红线、正文引用文号、图片等不确定版头一律不补线。修改后运行 `tests/test_letterhead_engine.py`。
32. 触发场景：网页请求 `mode=smart` 或 `processing_mode=smart` 时，必须解析为 `structural`（结构拆分保真）策略，不得在服务端改写成 `strict_preservation=True`。该策略只拆分有充分证据的软换行结构、行内编号标题正文和可靠尾部块；保留每个可见文本片段原文，不执行标点转换、编号修复、同级合并或自动编号。尾部在边界完整时允许按“附件说明 → 附件项 → 落款单位 → 日期”重排。`strict` 继续用于完全保留物理段落，`normalize` 才允许旧的文字与编号规范化。修改后至少运行 `tests/test_processing_flags.py tests/test_style_config_features.py tests/test_recognition_decoder.py tests/test_signature_detection.py tests/test_letterhead_engine.py`。
33. 触发场景：在结构拆分保真模式中识别到成文日期、一级标题和发文字号时，成文日期仍必须转为阿拉伯数字日期，独立一级标题末尾“。”必须删除，发文字号必须使用 `DCT-DocumentNumber` 居中且无首行缩进。常见机关简称只可作为落款识别证据，禁止在没有可靠全称来源时擅自扩写文本。修改后至少运行 `tests/test_processing_flags.py tests/test_signature_detection.py tests/test_engine_heading_spacing.py tests/test_letterhead_engine.py`。
34. 触发场景：用户开启前端“序号规范”时，结构拆分保真模式也必须在最终识别完成后重建一至四级标题序号；仅替换标题前缀，不改写标题正文、标点或段落顺序。渲染前必须同时清除源前缀“一、”“（一）”“1.”“（1）”及其错误编号，防止重复编号。关闭开关时保留原始编号。修改后至少运行 `tests/test_processing_flags.py tests/test_engine_heading_spacing.py tests/test_config_driven_styles.py`。
35. 触发场景：`smart`（结构拆分保真）模式不是关闭所有修复。默认保留正文和未启用的文字改写；但用户显式开启的标点修复、序号规范、页码、版头、表格优化、清理、特殊加粗和落款版式必须按各自开关生效。标点修复关闭时不得转换任何普通文本标点；开启时按安全标点规则处理。修改后至少运行 `tests/test_processing_flags.py tests/test_punctuation_engine.py tests/test_config_driven_styles.py`。
36. 触发场景：文首“在……上的讲话”被 Word 的 Heading 1 样式或既有错误输出误标为一级标题时，必须优先识别为 `title`，不得生成“一、”。仅在首个可分类段落、无冒号且正文去除单个“一、”后仍完整符合“在……上的讲话”时，才移除该推断出的错误前缀；普通一级标题不得受影响。若讲话材料的“职务姓名”和括号日期通过软换行粘连，或编号标题后通过软换行粘连正文，`smart` 模式必须拆为独立结构段，避免职务日期继承正文样式或正文继承标题样式。修改后至少运行 `tests/test_processing_flags.py tests/test_importer_heading_flow.py tests/test_engine_heading_spacing.py tests/test_recognition_decoder.py`。
37. 触发场景：编号一级标题后紧跟不少于 5 个可见正文字符时，`smart`/`structural` 必须先拆为“一级标题 → 一段完整正文”。正文不得因后续句号、加粗或字体切换再次拆段；正文区“加粗首句 + 普通正文”保持一个 `body`，只按源 run 证据恢复首句加粗。若正文后通过软换行出现独立称呼、编号标题、日期、附件或落款等强结构，可在完整正文之后继续拆出精确结构段；普通软换行不得增加正文段。SDK 对每段继续输出可验证定位范围，所有范围必须覆盖原始可见文字且不重叠、不丢失。修改后至少运行 `tests/test_processing_flags.py tests/test_engine_heading_spacing.py tests/test_sdk.py tests/test_segment_boundaries.py`。
38. 触发场景：独立一级标题错误写成`二.标题`、`三．标题`或带重复句点时，中文序数加点号仍作为损坏的一级序号证据；标点规范化不得先将该点号转换为正文句号，开启序号规范后统一重建为`二、标题`、`三、标题`。不得将正文中的“一是、二是、三是”纳入此规则。修改后至少运行 `tests/test_importer_heading_flow.py tests/test_processing_flags.py tests/test_punctuation_engine.py tests/test_recognition_decoder.py`。
38. 触发场景：广义“任意短句以冒号结尾”不能全局作为主送机关。`recipient/addressing`只允许文首正文开始前的主送机关，或任意区域中明确的独立称呼；进入正文后，空值的“机构名称：”按 `body + no_indent` 输出，使用 `DCT-Body` 且段前段后为 0。已有责任单位、联系人等明确字段标签继续走键值段规则，禁止维护具体机构名称名单。修改后至少运行 `tests/test_recognition_decoder.py tests/test_processing_flags.py tests/test_structured_layout_quality.py`。
39. 触发场景：“姓名/姓氏或职务修饰 + 书记、主席、主任、局长、老师、同志等个人称谓 + 冒号/感叹号”的短独立行应识别为称呼，不维护具体人名。“机构名称：正文内容”和“责任单位：内容”不得因冒号生成新段落，冒号只用于段内格式。同一段中的“一是/二是/三是”或“一要/二要/三要”仅加粗各自引导句，句号后正文必须恢复普通格式，不得与 `inline_lead_bold` 重复重写。
40. 触发场景：源 DOCX 的自动列表编号可能只存在于 `w:numPr`，不出现在段落文本中。必须解析直接或样式继承的 `numPr` 及其 `num/abstractNum` 定义；定义缺失时立即失败。标题层级优先由 `numFmt + lvlText` 模板确定，同一 `ilvl` 可对应不同标题层级；自定义模板只可结合同编号族、连续序号、最近父标题、旧识别结果和 Word 标题样式推断。加粗、字体和标题样式只加分，不得把“未加粗”作为自动编号标题的否定条件。超过 40 字、完整正文句、日期、附件、键值、称呼及冒号引出的连续列表保持正文/原结构。拆分物理段时仅首个逻辑段继承原生编号；关闭序号规范时合并并重映射完整编号定义，开启时只替换最终标题，普通自动列表继续保留。批处理报告“源自动编号标题线索数/未保留数”，只记录段落号、类型、证据和文字哈希。修改后至少运行 `tests/test_native_numbering.py tests/test_segment_boundaries.py tests/test_processing_flags.py tests/test_recognition_decoder.py tests/test_sdk.py tests/test_batch_test_docx.py`。
41. 触发场景：附件说明、落款单位和落款日期在源文档中交错，或被无内容空段隔开时，非 strict 导出必须整理为“附件说明及附件项 → 落款单位 → 日期”，并删除该尾部块内部无结构含义的空段。若同一物理段落包含“编号标题 + 正文 + 多个软换行 + 末行落款单位”，且下一物理段落首个可见行是日期，也必须在标题/正文拆分后继续拆出落款单位，不能让标题正文分支吞掉尾部结构。识别到落款单位和日期后，最终渲染计划必须保证二者相邻；批处理报告“落款连续性问题数”，附件不得出现在二者之间。
42. 触发场景：讲话稿开头和正文结尾都出现独立称呼时，开场称呼继续使用“称呼”配置的段前 1 行；一旦正文流已经开始，后续 `addressing`（例如文末再次称呼）段前、段后均强制为 0，不得因共用 `DCT-Recipient` 样式再次产生空一行。源段落中的连续手动空行仍按结构拆分规则清理。修改后至少运行 `tests/test_engine_heading_spacing.py tests/test_processing_flags.py tests/test_segment_boundaries.py`，并复排讲话专项稿检查最终 OOXML 的 `w:beforeLines`。
43. 触发场景：主标题后的职务姓名和日期时间地点继承了 Word 标题样式时，全文文首分析器确认的 `role_name`、`date_line` 结构事实必须优先于 `main_title/title_continuation` 视觉候选及 Beam 的“主标题 → 标题续行”加分；旧类型或 Word 样式本身不得触发该硬约束。带空格或紧凑的“角色 + 2—4 字姓名”必须由前一标题锚点或后续日期/称呼支持；报告、总结、方案、材料等文档形态后缀和正文中的角色词是反例。数字两侧的时间或比例冒号（如 `11:00`、`1 : 2`）即使夹有普通空格、Tab、NBSP、全角空格或其他 Unicode 空白，也不是结构标签分隔符，`时间 ： 11:00`仍按第一个语义冒号识别键值。数字冒号后再出现标签时，识别与渲染必须共享原文 offset 和真实标签范围，仅加粗标签及语义冒号，不加粗前置时间或比例。以上规则不维护具体姓名、单位或地区名单。修改后至少运行 `tests/test_colon_structure.py tests/test_engine_inline_effects.py tests/test_recognition_decoder.py tests/test_processing_flags.py tests/test_segmentation_soft_breaks.py tests/test_sdk.py`，并复排讲话专项稿核验文首类型及 SDK 子范围。
44. 触发场景：正文尾部通过软换行粘连“短组织落款 + 同行日期后缀 + 附件说明/附件页”时，结构分段必须将同行落款和日期拆为独立 `sign_org`、`sign_date` 子范围，再按“附件说明及续项 → 落款单位 → 日期 → 附件正文页”整理；不得让同行日期残留在正文中。进入附件正文区后，独立“附件 N”即使紧跟上一附件标题（上一附件没有正文）也必须重新识别为 `attachment_page_mark`；其后短独立行可为 `attachment_title`，长文本或多行文本直接为 `attachment_body`。每个附件页标记由渲染器统一写入一次 `pageBreakBefore`，不得依赖自然分页或重复分页符。修改后至少运行 `tests/test_signature_detection.py tests/test_signature_attachment_detection.py tests/test_segment_boundaries.py tests/test_body_order_export.py tests/test_structured_layout_quality.py`，并复排标准集 008、028 后逐页检查附件边界。
43. 触发场景：冒号结构不得在 importer、特征提取、候选和解码器中各自维护不同规则。统一由 `recognition/colon.py` 输出结构证据：文首独立标签可成为主送机关候选，明确称呼加冒号后接正文可拆为 `addressing + body`，正文区机构标签和解释性冒号正文保持正文或正文标签，责任单位、联系人等结构字段走键值候选。标题编号重复、倒序、跳号或缺少父标题时，最终类型可按最高综合分应用，但必须进入 `review` 并记录 `HEADING_SEQUENCE_CONFLICT`；不得通过具体单位、人名或完整句子白名单修复。修改后至少运行：

```pwsh
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m pytest -q tests/test_colon_structure.py tests/test_recognition_decoder.py tests/test_segment_boundaries.py"
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m ruff check src tests scripts"
```
44. 触发场景：正文中部独立出现“附件：...”不能仅凭关键词进入附件说明区；必须同时具备正文已开始、接近尾部、后接附件项/附件页/落款日期等共享上下文证据。落款单位不得依赖具体机构名单或相似度，只能由文尾位置、后接日期、独立短行、无正文标点和通用组织形态组合确认；标题编号重复、跳号和缺父标题必须按最近父标题作用域判断，不同一级标题下的“（一）”应合法重置。修改后至少运行：

```pwsh
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m pytest -q tests/test_recognition_decoder.py tests/test_processing_flags.py tests/test_signature_detection.py tests/test_importer_heading_flow.py tests/test_segment_boundaries.py tests/test_audit_hardening.py"
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m ruff check src tests scripts"
```
45. 触发场景：职务后任意四字纯汉字短语不能仅凭前标题、后日期、后称呼、居中或 Word 标题样式单项证据认作姓名。裸姓名 fallback 也必须统一调用 `is_person_name_suffix()` 和 `person_name_shape_strength()`，不得直接用宽泛正则确认。普通四字姓名属于弱形状，必须同时具备前标题、后日期/称呼和居中；弱裸姓名自身若已有 `title/title_cont` 类型或 Title、Subtitle、Heading 样式，则保留在标题/正文裁决中，不得写入 `front_metadata role_name`。复姓、间隔点、占位符及 2—3 字姓名属于强形状，沿用既有前后结构锚点。紧凑“职务+姓名”存在多种切分时优先采用强姓名形状，文档形状后缀不得成为姓名，不得加入具体姓名或业务短语黑名单。修改后运行 `tests/test_recognition_decoder.py tests/test_processing_flags.py`。
46. 触发场景：`时间11:00 标签：内容`、`版本1:2 标签：内容`等带文字前缀的数字时间/比例后仍有语义标签时，统一冒号分析必须返回原文中的 `separator_index`、`label_start_index`和`label_end_index`；渲染只加粗真实标签及语义冒号，数字表达及其文字前缀保持普通字重。修改后运行 `tests/test_colon_structure.py tests/test_engine_inline_effects.py`。
47. 触发场景：最终识别为一至四级标题的独立标题以中文句号结尾，且句号后没有正文时，非 strict 导出必须删除该句末句号；“标题。正文”仍按既有标题正文边界处理，不得因本规则误删分界句号或正文。修改后运行 `tests/test_engine_heading_spacing.py`。
48. 版头实现与视觉验收以上位标准 GB/T 9704—2012 为准，并以广州工商学院办公室转载的《国家机关政府部门公文格式标准（2023年新版）》及“正式公文（下行文）首页版式”图作为本地操作参考。图中的机关名称、年份、字号示例和 Word 操作步骤不得作为固定业务数据或覆盖上位标准；本项目按已确认产品规则将图示顶部空白落地为 3 个固定 28 pt 空行。下行文首页至少核验：A4 页面及上 37 mm、下 35 mm、左 28 mm、右 26 mm；机关标志在版心内单行居中且不得因固定大字号换行；标志下方 2 个正文行距后紧接发文字号；发文字号居中、首行缩进 0；其下 4 mm 为与版心等宽的红色直线；标题位于红线下空二行且多行按词意完整的梯形或菱形排列；标题下空一行接主送机关，首页必须出现正文。项目扩展的五角星分隔线允许由用户显式选择，但不得宣称为严格国标直线。修改版头布局后运行 `tests/test_letterhead_engine.py tests/test_structured_layout_quality.py`，并同时渲染首页检查机关标志单行、红线宽度和各垂直间距。
49. 触发场景：WPS 可能正常显示五角星版头分隔线的两侧 VML 直线，但忽略填充的 `v:polyline` 中央星形。中央五角星必须使用闭合的 `v:shape` 路径并显式设置红色填充和轮廓，不得回退为 `v:polyline`；修改后运行 `tests/test_letterhead_engine.py apps/wps/tests/test_add_letterhead.py`，并在真实 WPS 中检查中央五角星可见。

## 可移动服务器部署

0. Python 运行基线为 3.8—3.10；Windows 7 SP1 固定使用 Python 3.8。依赖锁由 Python 3.8 生成，并在 Python 3.8、3.10 中分别验证。修改类型注解、标准库 API、依赖或启动脚本后，必须执行双版本导入和测试。
1. 后端入口、启动脚本、数据库、日志、输出和运行时目录不得写死盘符、用户目录、服务器 IP 或部署目录。
2. Windows 启动统一使用根目录 `run.ps1`，脚本通过 `$PSScriptRoot` 定位项目；`.env`中的相对运行路径统一相对于项目根解析。
3. Nginx模板只允许固定本机上游 `127.0.0.1:9527`，服务器公网地址通过 Cloudflare Pages 的 `BACKEND_BASE_URL`配置，不写入源码。
4. 修改路径或部署入口后至少运行 `tests/test_paths.py`，并从项目目录之外执行 `pwsh -NoProfile -File <项目目录>\run.ps1 -CheckOnly`。
5. Web 业务库 `DATABASE_PATH` 与 WPS 插件库 `WPS_DATABASE_PATH` 必须解析到不同文件；统一启动入口必须在初始化任一数据库前检查冲突，并以 `WPS_DATABASE_PATH_CONFLICT` 失败。不得通过 SQLite `ATTACH`、跨库 JOIN 或跨库事务合并两套业务数据。修改后运行 `tests/test_wps_server_database.py tests/test_web_admin_workspace.py`。
6. 单进程、2 核 2G 的 WPS 账号服务固定共用两个 Argon2 槽位；注册哈希、真实或虚假账号校验和哈希升级都必须经过同一进程级 `BoundedSemaphore(2)`。Argon2id 保持 `m=65536 KiB、t=3、p=4`，不得通过降低密码参数换取吞吐；改为多进程时必须按“每进程两个槽位”重新核算总内存。
7. WPS 新会话固定 7 天且心跳不续期，已有会话不得批量迁移；WPS 登录限流固定为 IP `300/600s`、账号 `10/600s`，注册为 IP `5/3600s`。网页版登录继续使用 IP `30/600s`、账号 `10/600s`。修改后运行 `tests/test_wps_server_auth.py tests/test_wps_server_routes.py tests/test_web_auth_route_handlers.py`。

## IDE 快捷方式启动失败

1. 触发场景：Codex 右上角或系统快捷方式启动 PyCharm 时出现 `Start Failed`，并指向 `AppData\Local\JetBrains\PyCharm*\.port`、`DirectoryLock` 或本地 socket 错误。
2. 先确认系统快捷方式的目标仍是有效的 `pycharm64.exe`，再检查是否存在无窗口、无响应的 `pycharm64` 残留进程；只停止已确认的残留 PID，不终止其他 IDE、Java 或 Python 进程。
3. 仅在 PyCharm 进程完全停止后删除对应版本目录中的异常 `.port` 文件，再通过正式可执行文件打开项目验证。不要删除整个 JetBrains 配置目录，也不要使用“Reset Settings & Plugins”作为默认修复方式。
4. 验证命令应确认新 `pycharm64` 进程 `Responding=True` 且出现项目窗口标题。

## 数据和密钥保护

已接收的上传原件、生成文件、任务日志和任务记录采用永久保留策略；不得通过 TTL、启动清理、后台定时清理或管理员清理入口删除它们。仅未完成、未通过校验或未入队的上传半成品可以删除。修改存储逻辑后至少验证成功任务和失败任务的原件均可保留、下载结果仍可访问。

不要提交或上传：

- `.env`
- 真实 `ADMIN_TOKEN`、`PROXY_SECRET`
- API key、访问令牌、Cookie、会话 ID
- SSH 私钥、证书私钥
- `stats.db`、日志、生成的 Word 文件
- 用户隐私文档正文

## GitHub 发布与文件收口

GitHub 发布的目标是同步**全部符合发布范围的项目修改**，而不是按临时记忆挑选几个文件，也不是直接把当前磁盘的所有内容推送。发布以 `docs/GITHUB_UPLOAD_GUIDE.md`、`docs/UPLOAD_MANIFEST.md` 和 `scripts/publish_to_github.ps1` 为准；脚本使用临时干净克隆、安全扫描、提交、推送和远程核验，禁止直接对脏工作树执行 `git add -A` 后推送。

### 应上传的项目文件

以下目录中的源码、测试、文档和配置属于可发布范围：

- `src/`、`tests/`、`docs/`、`scripts/`、`resources/`、`deploy/`、`.github/`；
- 根目录的 `AGENTS.md`、`README.md`、`CHANGELOG.md`、`CONVENTIONS.md`、`公文格式规范.md`、`server.py`、`pyproject.toml`、`requirements*.txt`、`requirements*.lock`、`run.sh`、`run.ps1`、`.env.example`、`.gitignore`、`.gitattributes`、`pytest.ini`、`ruff.toml`；
- 运行目录仅允许 `var/data/.gitkeep`、`var/logs/.gitkeep`、`var/outputs/.gitkeep`、`var/runtime/.gitkeep`。

用户明确要求“上传最新修改”时，应收口上述范围内的全部已修改、已删除和新增文件。当前发布脚本采用明确白名单：新增的可发布文件必须同步登记到 `docs/UPLOAD_MANIFEST.md` 和 `scripts/publish_to_github.ps1`；文档还必须登记到 `docs/README.md` 与 `docs/GITHUB_UPLOAD_GUIDE.md`。来源、职责或是否可公开不明确的新增文件必须先标记出来，不得静默遗漏或猜测上传。

### 永不上传的文件

以下内容无论是否未跟踪、是否本地测试成功，都不得进入 GitHub：

- `.env`、`.env.*`（仅根目录 `.env.example` 例外）、真实密钥、令牌、Cookie、会话、SSH 私钥、证书私钥；
- 用户原件、测试 DOCX、生成 DOCX、PDF、图片、压缩包、wheel、构建产物和补丁基线，例如 `test_docx/`、`wps/` 私有产物、`*.docx`、`*.whl`、`*.zip`、`phase-*.patch`；
- 数据库、日志、任务记录、运行输出和临时目录，例如 `*.db`、`*.sqlite*`、`*.log`、`var/data/*`、`var/logs/*`、`var/outputs/*`、`var/runtime/*`；
- 虚拟环境、缓存和本机工具目录，例如 `.venv/`、`__pycache__/`、`.pytest_cache/`、`.ruff_cache/`、`build/`、`dist/`、`tmp/`、`temp/`。

安全扫描必须精确允许根目录 `.env.example`，并继续拒绝其他 `.env` 文件。发现疑似敏感文件、用户内容或未归类文件时，发布必须停止并报告路径与原因。

### 发布方式

1. 用户未明确要求发布时，只完成代码、测试和文档工作；报告建议版本号、主要变更和验证结果后停止。
2. 普通推送默认使用快速模式：仍执行临时干净克隆、发布范围收口、敏感文件扫描、差异检查、远端并发保护和推送后核验，但不重复执行全量 Python、Ruff 和 Node 测试。`-Quick` 是快速模式的显式标识；省略 `-Quick` 时也保持同一快速行为，以兼容既有调用。
3. 以下情形必须使用完整验证：用户明确要求全量测试或正式发布；修改识别/导入/分段/规范化/渲染主链路、SDK 公开契约、鉴权安全、依赖锁、启动部署或 CI；或快速门禁、快照、批量 DOCX 回归存在未解释差异。完整验证使用 `-Verify`，不得与 `-Quick` 同时使用。
4. 用户明确要求发布时，先收口全部可发布修改，再更新版本与变更记录，按本规则执行快速或完整验证，通过后创建一个单一、可读的发布提交并推送；随后核验远端分支提交号和版本文件。
5. 发布提交不得混入不相关的用户本地变更。需要保留但不发布的草稿、基线补丁或运行数据保持在本地，并在发布结果中明确说明。
6. 发布前可做预览；具体参数和操作细节只维护在 `docs/GITHUB_UPLOAD_GUIDE.md`，不要在本文件复制命令。

## 版本与提交提醒

1. 对用户可见的发布版本固定使用两段编号，例如 `2.4`、`2.5`；第二段从 `9` 进位为下一主版本，例如 `2.9` 后为 `3.0`。不得使用第三段修订号，也不得复用已发布版本号。
2. 每个可发布批次只生成一个新版本。默认递增第二段；只有不兼容的公开协议、部署方式或用户明确指定的重大发布才递增第一段。
3. 发布前必须同步更新 `pyproject.toml`、`src/docxtool/version.py` 和 `CHANGELOG.md`；wheel、Web、SDK、CLI 和远端版本文件必须由测试或远端核验确认一致。
4. 完成一批可发布功能、测试和文档后，如用户未明确要求提交，先说明建议版本号、主要变更和验证结果，并询问是否提交到 GitHub。未经明确要求，不自动 commit 或 push。

## 公文测试文档批处理

执行文档批处理前必须阅读并逐项核对 `docs/DOCX_REGRESSION_CHECKLIST.md`。该清单汇总项目已经真实出现过的问题；测试结论必须分别说明文件生成、结构审计、模板差异和视觉抽查结果，不能用“处理成功”代替全部验收。

测试文档统一放在项目根目录下的 `test_docx` 目录，不得散落到项目根目录或运行时目录：

- `test_docx/tset1/test1`：标准 50 篇原始乱格式测试文档；
- `test_docx/tset1/test1正确格式`：标准 50 篇正确格式对照模板，只读；
- `test_docx/tset1/test1测试结果`：标准 50 篇排版结果、批量测试报告和视觉抽查产物；
- `test_docx/test2/test2`：长期专项回归原稿；
- `test_docx/test2/test2正确格式`：长期专项回归正确格式对照，只读；
- `test_docx/test2/测试结果`：长期专项回归排版结果、报告和视觉抽查产物；
- `test_docx/wps_validation`：WPS/宿主定位合同专项样本。

当前批处理路径以实际扫描到的 `tset1`、`test2` 和 `wps_validation` 目录为准；历史遗留的 `test_docx/测试文稿/测试目录` 不再作为专项输入或输出目录，除非用户再次明确指定。

执行批量测试时，按文件编号顺序读取 `test_docx/tset1/test1` 中全部测试 DOCX，使用 `test_docx/tset1/test1正确格式` 中按编号匹配的模板作为对照；只有一个模板时可作为统一标准。不得修改原始测试文档和模板，不得覆盖 `test_docx/tset1/test1测试结果` 中已有同名结果。单篇结果必须先写入临时文件，完成 ZIP/DOCX 完整性和文字提取检查后再改名为正式结果；单篇失败不得中断其余文件，且不得留下伪装成功的半成品。

模板对比只比较稳定结构和格式字段，不比较 DOCX 二进制、ZIP 时间戳、关系 ID、临时文件名或机器绝对路径。段落必须按版头、文首、正文、落款、附件等区域作保序对齐；不得按固定段落下标比较，以免版头或空行插入导致后续级联误报。至少对比文档模式、段落文本和顺序、标题层级、版头、发文字号、正文、落款、日期、附件、字体、字号、加粗、对齐、缩进、行距、段前段后、分页、页眉页脚、页码、表格、图片、分节和空段。每项差异记录文件编号、输出与模板段落编号、类别、实际值、模板值、匹配依据、是否预期修复和严重级别（P0 文档/数据损坏，P1 核心结构，P2 局部格式，P3 轻微视觉差异）。

`strict`中未拆分的“二级标题句 + 同段正文”整段左对齐，以及`normalize`中的结构拆分、标题句号、日期数字化和结构编号空格，只能在模式明确、结构形状匹配且规范化后字符守恒时标记为`expected_mode_difference`。原始 P1/P2 差异记录和数量必须保留；字符丢失、重复或不符合模式契约时仍按真实问题报告，禁止整体降低严重度。

批量测试必须在 `test_docx/tset1/test1测试结果` 生成 JSON 和文字报告，记录总数、成功/失败数、各级问题数、模板匹配、段落和标题统计、版头/落款/附件识别、文字新增/丢失、表格图片、空白页、处理耗时和错误信息。报告不得包含完整正文、密钥、Cookie 或完整日志。发布前或用户要求“全部测试”时，使用 `scripts/batch_test_docx.py --render-review --require-render` 抽查标准集 10 篇和专项集全部文档；渲染图、PDF 与疑似空白页清单写入对应结果目录。若没有可用渲染器，必须明确记录“未执行视觉渲染检查”，不能据此断言没有空白页。

以后生成新的标准测试 DOCX，默认放入 `test_docx/tset1/test1` 并使用连续编号；不得放入结果目录，不得覆盖原始材料或模板。临时脚本可以在仓库外或 `scripts` 目录使用，但不得复制到 `test_docx`，测试完成后清理临时文件。

除标准 50 篇外，`test_docx/test2/test2` 是长期专项回归集。每次执行“全部测试”或发布前批量验证时，必须同时处理该目录下全部 DOCX：结果写入 `test_docx/test2/测试结果`，每篇先写临时文件并通过 DOCX/ZIP 完整性和文字读取检查后再替换本轮结果。专项集正确格式位于 `test_docx/test2/test2正确格式`；没有可靠一一对应模板时，不得把不同内容的文档与标准集模板直接判为格式失败，应单独报告处理成功/失败、结构复核项、文字变化、页面渲染结果和人工抽查问题。最终总报告须分别列出标准集与专项集的数量、通过情况和未执行的视觉检查。

## 识别审核诊断

1. 候选排序分数和用户可见的审核置信度不是同一个概念。`recognition_confidence` 保留为原始候选分布诊断，不得直接据此向用户宣称“识别置信度低”。
2. 审核结论使用 `review_confidence`、`review_level`、`review_reasons` 和脱敏的 `evidence_summary`。明确编号、文号、日期、附件、题注等结构证据，或与旧分类一致的结果，应优先判为 `confirmed`；有强结构证据的重新分类只记录为 `info`。
3. 只有弱证据、候选接近且可能改变最终结构的段落，才标为 `review` 或 `critical_review` 并进入用户端人工复核列表。修改诊断规则后至少运行：

4. 识别结果是最终 `type_id` 的唯一来源；尾部规范化只能消费已确认的 `attachment_note`、`attachment_note_item`、`sign_org`、`sign_date`、`attachment_page_mark`、`attachment_title` 和 `attachment_body`，不得再用独立正则把正文重新判为尾部结构。发生尾部重排后，必须同步段落 `meta.final_type`、`recognition_*` 字段和 `DocumentData.recognition_diagnostics` 顺序。
5. 旧 importer/legacy 只允许作为弱候选和差异诊断来源，不能参与 hard veto、正文起点、文首 metadata、落款日期或附件链路的权威裁决；关闭 legacy 候选时，context、candidate、veto 和 review 均不得读取 legacy。
6. Beam Search 的候选列表、选中候选、分数、margin、provider 和 evidence 必须来自最终获胜路径；不得用临时最佳前缀的候选摘要生成最终诊断。
7. 文首扫描的 12 个有效段落只作为软阈值；未出现正文、附件、键值、编号标题等真实结构边界时继续扫描到边界或物理安全上限，软阈值后通过提高标题证据要求避免正文短行误判。
8. 文首纯姓名行必须由“前一可见行具备标题锚点 + 后一可见行是日期占位或称呼”共同确认；文尾日期可由落款单位、附件页/附件说明边界或有正文支撑的文档末尾确认，但联系人、字段标签和“以上……”等否定性短句后的日期不得自动转为 `sign_date`。

```pwsh
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m pytest -q tests/test_recognition_decoder.py tests/test_audit_hardening.py"
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m ruff check src tests scripts"
```

## WPS 物理段落定位合同

1. wheel 逻辑块序号不能当作 Word/WPS 物理段落序号。每个可定位 block 必须携带原始物理段落完整文本 SHA-256、相同物理文本出现序号、UTF-16 code unit 起止偏移、子范围 SHA-256 和 `locator_verified`。
2. 物理段落拆出多个逻辑角色时，所有块继承同一物理锚点并分别记录子范围；无法在原始物理文本中证明精确位置时 locator 留空，禁止猜测偏移。
3. SDK 默认不得返回正文。只有本机离线 `local-agent → WPS` 内存链路可显式 `include_text=True`；`recognized_text` 不得进入 command-service、日志、报告、PluginStorage 或联网接口。
4. WPS 端只允许完整物理哈希、物理出现序号、UTF-16 子范围和子范围哈希全部验证后创建目标；禁止 dense/non-empty/裸序号 fallback。没有正式表格合同前跳过表格单元格。
5. 同一物理段落包含多个角色或单一角色未覆盖整段时，只允许子 Range 预览并标记 `mixed_structure / review_only`；正式排版必须在命令生成和事务开始前返回 `MIXED_PARAGRAPH_REQUIRES_SPLIT`。
6. 尾部规范化可能把附件说明移动到落款单位和日期之前；SDK 的 block 数组保持最终排版顺序，但同一物理段落的 `segment_index`、范围重叠检查和宿主绑定顺序必须按原始 UTF-16 起止位置计算。不得因最终顺序与原文顺序不同，把本来可回读的落款、日期或附件范围误报为 `SOURCE_RANGE_OVERLAP`。

## WPS 调试进程收尾

1. 启动 `apps/wps/main.py`、`wpsjs debug` 或 WPS Control Server 前，记录本轮进程 PID 和监听端口；验证结束或任务停止时，必须关闭本轮创建的 Python、Node、PowerShell、cmd 进程树并删除生成的 `apps/wps/runtime/runtime-config.js`。
2. 收尾后检查本轮端口不再监听，且不存在命令行指向当前仓库 `apps/wps` 的残留启动器。不得默认终止用户开始前已有的 WPS 进程；只有用户明确要求关闭时才处理。
3. WPS 加载项注册只保留当前项目 `docxtool-wps-app`；清理重复项前先备份 `publish.xml` 和 `authaddin.json` 到 `local_recycle/`，不得删除项目源码或 WPS 系统加载项。

## 最终语义与布局策略边界

1. Recognition 是段落 `type_id` 的最终裁决者；Normalization 只能规范化已确认文本、编号 meta 和尾部顺序，不得通过同级标题或其他启发式改型。修改后运行 `tests/test_recognition_decoder.py tests/test_normalization_pipeline.py`。
2. `DocumentData.recognition_structure` 只在 Normalization 与一致性同步后构建，必须反映最终段落顺序和类型；不得长期保存 normalization 前结构作为最终结构。
3. `LayoutPolicy` 只在 `document/analysis/layout_policy.py` 推断。只有真实附件分页后的附件区域同时存在至少两行稳定重复人工列，才可设为 `PRESERVE_LAYOUT`；普通附件正文和键值正文保持 `NORMALIZE`，表格、图片、题注与版头对象使用 `PRESERVE_OBJECT`。
4. `PRESERVE_LAYOUT` 必须从分段前到导出守恒 Tab、连续空格、全角空格、NBSP、可见字符和物理来源顺序；Engine 可以统一字体、字号、行距和附件样式，但不得重新识别、折叠或改写人工列。结构段排版失败必须抛 `ExportError`，不得静默降级为正文。修改后运行 `tests/test_layout_policy.py tests/test_engine_heading_spacing.py tests/test_document_structure.py`。
5. 触发场景：明确二级序号（可见`（一）`或原生模板`（%1）`）后接“非空短标题 + 语义冒号 + 非空正文”时，统一识别为一个`heading2`物理段；冒号及以前使用二级标题配置，冒号后空格和正文使用正文配置。规则只依赖结构，不维护标签白名单；数字时间/比例冒号不是分界，无编号键值段沿用原语义。`structural/smart`与`normalize`应用段内格式，`strict`不新增run改写；拆分跨界run时必须保留图片、域和关系节点。修改后运行`tests/test_colon_structure.py tests/test_recognition_decoder.py tests/test_engine_inline_effects.py tests/test_engine_heading_spacing.py tests/test_native_numbering.py tests/test_sdk.py`。

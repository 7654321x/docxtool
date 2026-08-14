# Phase A-2 Looper 日志

状态：`completed`。本文只保留已执行微批次的脱敏历史记录。

## 启动状态

- HEAD：`fe0667313ee43791f2846b8574a969b6d07bec8b`
- 分支：本地 `main`，启动时落后 `origin/main` 3 个提交。
- 工作树：启动前已有多项已跟踪修改和未跟踪迁移文件；本轮均保留，未执行恢复、清理、提交或推送。
- 已完成基线：物理段 SourceTape/locator 构建已迁移到 `document/segmentation/source_locator.py`，不得重复实现。
- 已知非本轮问题：`scripts/publish_to_github.ps1` 存在启动前已有的 LF/CRLF 提示。

## Loop 1：Word numbering 物理应用

状态：passed

原位置：
- `src/docxtool/document/importing/features.py`

新位置：
- `src/docxtool/document/importing/numbering.py::apply_physical_numbering_features`

兼容入口：
- `docxtool.document.importer.extract_features`
- `docxtool.document.importing.features.extract_paragraph_features`
- `word_list_level_prefix`、`heading_style_prefix` 原导入路径

修改文件：
- `src/docxtool/document/importing/numbering.py`
- `src/docxtool/document/importing/features.py`
- `tests/test_importing_features.py`
- `docs/migration/phase-a2-checklist.md`
- `docs/migration/phase-a2-looper-log.md`

测试：
- 修改前：`python -m pytest -q tests/test_document_importing_helpers.py tests/test_importing_features.py tests/test_importing_reader.py tests/test_importer_heading_flow.py`
- 退出码 0，`24 passed`。
- 边界测试先失败：`tests/test_importing_features.py` 因新应用入口尚不存在退出码 1，`1 failed, 6 passed`。
- 修改后同组直接测试退出码 0，`27 passed`。
- `python -m compileall -q src/docxtool` 退出码 0。
- `git diff --check` 退出码 0；仅输出启动前已有的 `scripts/publish_to_github.ps1` LF/CRLF 提示，本轮文件无新增空白或行尾问题。
- 修改文件 Ruff 退出码 0，`All checks passed`。

快照：
- 样本：Word 原生 `w:numPr` 列表、无 `w:numPr` 的手写 `1.` 编号，共 2 份脱敏临时 fixture。
- 字段：`numId`、`ilvl`、abstract 映射、可用 level 定义、源/输出 `word/numbering.xml`、物理块、logical lines、source spans、locator、inline tokens、Recognition 输入、final type 和完整 package manifest。
- package part 差异：0。
- relationship 差异：0。
- normalized metadata 差异：0。
- document structure 差异：0。
- 缺失 relationship target：0。
- 说明：生产 `ParagraphFeatures` 目前只承载 `@lvl_N` / `@style_headingN`，不承载完整 Word numbering facts；本轮没有通过新增模型字段改变行为。

下一项：
- paragraph/run 剩余物理格式读取。

## Loop 2：Paragraph/run 物理格式读取

状态：passed

原位置：
- `src/docxtool/document/importing/features.py`

新位置：
- `src/docxtool/document/importing/physical_format.py::apply_physical_format_features`

兼容入口：
- `docxtool.document.importer.extract_features`
- `docxtool.document.importing.features.extract_paragraph_features`
- importer `_importing_extract_paragraph_features` monkeypatch facade

修改文件：
- `src/docxtool/document/importing/physical_format.py`
- `src/docxtool/document/importing/features.py`
- `tests/test_importing_features.py`
- `docs/migration/phase-a2-checklist.md`
- `docs/migration/phase-a2-looper-log.md`

测试：
- 修改前：`python -m pytest -q tests/test_importing_features.py tests/test_effective_format.py tests/test_audit_hardening.py`
- 退出码 0，`72 passed`，2 条既有重复 ZIP fixture 警告。
- 边界测试先失败：`tests/test_importing_features.py` 因新模块尚不存在退出码 1，`1 failed, 8 passed`。
- 修改后同组直接测试退出码 0，`74 passed`，2 条既有重复 ZIP fixture 警告。
- `python -m compileall -q src/docxtool` 退出码 0。
- 修改文件 Ruff 退出码 0，`All checks passed`。

快照：
- 样本：混合 run 直接格式、段落样式继承，共 2 份脱敏临时 fixture。
- 字段：run 数量、字体、字号、bold/italic/underline、格式来源、对齐、缩进、source runs/spans、locator、inline tokens、Recognition 输入、final type 和完整 package manifest。
- package part 差异：0。
- relationship 差异：0。
- normalized metadata 差异：0。
- document structure 差异：0。
- 缺失 relationship target：0。
- 说明：首次内存比较把 JSON list 与运行时 tuple 比较，产生 6 个 `format_sources` 类型假差异；前后快照均从 JSON 重载后归零，字段值和顺序一致。

下一项：
- importing 模块级门禁；通过后按模块完成停止。

## 模块门禁：document/importing

状态：passed

范围：
- `document/importing` 物理读取、编号、run/段落格式、图片、inline token、分节和关系修复边界。
- importer 兼容 facade、SourceTape/locator 与逻辑分段直接回归。

测试：
- `python -m pytest -q tests/test_document_importing_helpers.py tests/test_importing_features.py tests/test_importing_reader.py tests/test_effective_format.py tests/test_importer_heading_flow.py tests/test_importer_broken_relationships.py tests/test_segment_boundaries.py tests/test_segmentation_source_locator.py tests/test_section_header_footer.py`
- 退出码 0，`63 passed`，无 warning。
- `python -m ruff check` 覆盖 `src/docxtool/document/importing`、`source_locator.py` 和上述直接测试，退出码 0。
- `python -m compileall -q src/docxtool` 退出码 0。
- `git diff --check` 退出码 0；仅输出启动前已有的 `scripts/publish_to_github.ps1` LF/CRLF 提示，本轮文件无新增空白或行尾问题。

快照：
- 样本：原生 Word 编号、纯手写编号、混合 run、继承样式、纵横分节及页眉页脚、软换行与分页，共 6 份脱敏 fixture。
- 模式：`strict`、`structural`、`normalize`，共 18 个对照案例。
- 迁移前基线：通过 importer 既有 `_importing_extract_paragraph_features` facade 注入迁移前函数；当前实现通过同一 facade 执行。
- package part 差异：0。
- relationship 差异：0。
- normalized metadata 差异：0。
- document structure 差异：0。
- 缺失 relationship target：0。
- 兼容入口：旧 importer facade 仍调用新模块；旧 monkeypatch 路径仍命中真实执行；不存在两套生产实现。

停止原因：
- 已完成一个清晰模块：`document/importing`。
- 未继续进入 segmentation、normalization 或 Phase B。
- 本轮三个快照目录均位于 `%TEMP%`，未写入仓库。

## Segmentation Loop 1：Source span 与 token 保留计划

状态：passed

原位置：
- `src/docxtool/document/segmentation/pipeline.py`

新位置：
- `src/docxtool/document/segmentation/partition.py::build_logical_span_plan`

兼容入口：
- `docxtool.document.segmentation.pipeline.LogicalSpanPlan`
- `docxtool.document.segmentation.pipeline.build_logical_span_plan`
- `docxtool.document.segmentation.build_logical_span_plan`
- importer `_build_logical_lines` 及其注入回调

修改文件：
- `src/docxtool/document/segmentation/partition.py`
- `src/docxtool/document/segmentation/pipeline.py`
- `tests/test_segmentation_pipeline.py`
- `docs/migration/phase-a2-checklist.md`
- `docs/migration/phase-a2-looper-log.md`

快速测试：
- 修改前相关测试退出码 0，`47 passed`。
- 边界测试先失败：新 `partition` 模块不存在，退出码 1，`1 failed, 4 passed`。
- 修改后相关测试退出码 0，`49 passed`。
- `python -m compileall -q src/docxtool` 退出码 0。
- 修改文件 Ruff 退出码 0，`All checks passed`。

快照：
- 样本：tab token 保留、编号标题正文加分页/软换行称呼，共 2 份脱敏临时 fixture。
- 字段：physical blocks、logical lines、文字哈希、source runs/spans、raw/canonical locator、inline tokens、Recognition 输入、final type 和完整 package manifest。
- package part 差异：0。
- relationship 差异：0。
- normalized metadata 差异：0。
- document structure 差异：0。
- Recognition 输入差异：0。
- 缺失 relationship target：0。

下一项：
- source span 文字、顺序、范围守恒校验。

## Segmentation Loop 2：Source span 守恒校验

状态：passed

原位置：
- `src/docxtool/document/segmentation/boundaries.py::validate_source_span_partition`

新位置：
- `src/docxtool/document/segmentation/conservation.py::validate_source_span_partition`

兼容入口：
- `docxtool.document.segmentation.boundaries.validate_source_span_partition`
- `docxtool.document.segmentation.validate_source_span_partition`
- `docxtool.document.importer._validate_source_span_partition`

修改文件：
- `src/docxtool/document/segmentation/conservation.py`
- `src/docxtool/document/segmentation/boundaries.py`
- `tests/test_segment_boundaries.py`
- `docs/migration/phase-a2-checklist.md`
- `docs/migration/phase-a2-looper-log.md`

快速测试：
- 边界测试先失败：新 `conservation` 模块不存在，退出码 1，`1 failed, 17 passed`。
- 修改后相关测试退出码 0，`43 passed`。
- `python -m compileall -q src/docxtool` 退出码 0。
- 修改文件 Ruff 退出码 0，`All checks passed`。

快照：
- 样本：tab token 保留、编号标题正文加分页/软换行称呼，共 2 份脱敏临时 fixture。
- 字段：文字哈希、physical blocks、logical lines、source runs/spans、locator、inline tokens、Recognition 输入、final type 和完整 package manifest。
- package part 差异：0。
- relationship 差异：0。
- normalized metadata 差异：0。
- document structure 差异：0。
- Recognition 输入差异：0。
- 缺失 relationship target：0。

下一项：
- segmentation 模块级门禁；通过后按模块完成停止。

## 模块门禁：document/segmentation

状态：passed

范围：
- physical blocks 到 logical lines 的顺序编排。
- soft-break、标题正文、称呼正文和尾部粘连边界。
- source span、raw/canonical UTF-16 locator、inline token 分区与 segment ordinal。
- 可见文字、顺序、范围和 locator 守恒。
- importer facade、Recognition 输入及 SDK locator 兼容。

测试：
- `python -m pytest -q tests/test_segmentation_pipeline.py tests/test_segment_boundaries.py tests/test_segmentation_source_locator.py tests/test_importing_reader.py tests/test_processing_flags.py tests/test_sdk_binding.py tests/test_sdk.py`
- 退出码 0，`65 passed`，无 warning。
- `python -m ruff check` 覆盖 `src/docxtool/document/segmentation` 和上述直接测试，退出码 0。
- `python -m compileall -q src/docxtool` 退出码 0。
- `git diff --check` 退出码 0；仅输出启动前已有的 `scripts/publish_to_github.ps1` LF/CRLF 提示，本轮文件无新增空白或行尾问题。

快照：
- 样本：无软换行、单软换行、连续头部软换行、标题正文分页及称呼、UTF-16 代理对加多 run/tab、尾部单位日期附件，共 6 份脱敏 fixture。
- 模式：`strict`、`structural`、`normalize`，共 18 个对照案例。
- 迁移前基线：通过 `pipeline.build_logical_span_plan` 和 importer `_validate_source_span_partition` 既有 monkeypatch 边界注入迁移前函数；当前实现通过同一 facade 执行。
- source span/token 守恒：通过，丢失、重复、重叠、空洞和非法顺序变化均为 0。
- package part 差异：0。
- relationship 差异：0。
- normalized metadata 差异：0。
- document structure 差异：0。
- Recognition 输入差异：0。
- 缺失 relationship target：0。
- 兼容入口：旧 importer 和 segmentation facade 仍调用新实现；旧 monkeypatch 路径仍命中真实执行；不存在两套生产实现。

停止原因：
- 已完成一个清晰模块：`document/segmentation`。
- 未继续进入 normalization、engine、web 或 Phase B。
- 本轮 segmentation 快照目录均位于 `%TEMP%`，未写入仓库。

## Phase A-3 Importer Loop 1：处理模式与文本/token 策略

状态：passed

原位置：
- `src/docxtool/document/importer.py::DocxImporter.load` 的处理模式、标点和 token 策略构建。

新位置：
- `src/docxtool/document/pipeline/options.py::resolve_import_processing_options`

兼容入口：
- `DocxImporter.load` 继续接收原参数并注入 importer 的 `_feature_bool`、`_normalize_text`、`_normalize_quotes`、`_to_chinese_punctuation` 和 `_normalize_inline_tokens` 兼容回调。

快速门禁：
- 相关测试退出码 0，`32 passed`。
- `python -m compileall -q src/docxtool` 退出码 0。
- 修改文件 Ruff 和 `git diff --check` 退出码 0。

快照：
- 标准集 3 份、专项集 3 份，`strict`、`structural`、`normalize` 共 18 个案例。
- physical blocks、logical paragraphs、text/original_text 哈希、source spans、locator、inline tokens、Legacy/Core metadata、Recognition 输入输出、final types、package parts、relationships、document structure 和 missing relationship targets 差异均为 0。

下一项：
- Legacy 单段分类、上下文推进和 paragraph materialization。

## Phase A-3 Importer Loop 2：Legacy 分类与 paragraph materialization

状态：passed

原位置：
- `src/docxtool/document/importer.py::detect_paragraph_type`
- `src/docxtool/document/importer.py::DocxImporter.load` 的 Legacy 上下文推进和 ParagraphData 构造。

新位置：
- `src/docxtool/document/recognition/legacy/classifier.py::classify_legacy_paragraph`
- `src/docxtool/document/recognition/legacy/pipeline.py::advance_legacy_context`
- `src/docxtool/document/pipeline/paragraph_materialization.py`

兼容入口：
- `docxtool.document.importer.detect_paragraph_type` 保留原签名并注入原 scorer、Flow、Repair、metadata 和日志回调。
- `DetectionContext`、`ParagraphData` 及 importer 私有结构回调仍从旧路径可用。

快速门禁：
- Legacy、状态、文首讲话、处理模式、Importer 标题流和分段边界测试退出码 0，`65 passed`。
- `python -m compileall -q src/docxtool`、修改文件 Ruff 和 `git diff --check` 均通过。

快照：
- 同一 6 份样本、3 种模式、18 个案例。
- physical/logical 结构、文本哈希、source spans、locator、inline tokens、Legacy/Core metadata、Recognition 输入输出、final types、package、relationships 和 document structure 差异均为 0。

下一项：
- Core classifier adapter。

## Phase A-3 Importer Loop 3：Core classifier adapter

状态：passed

原位置：
- `src/docxtool/document/importer.py::DocxImporter._apply_core_classification`

新位置：
- `src/docxtool/document/recognition/core_adapter.py::apply_core_classification`

兼容入口：
- `DocxImporter._apply_core_classification` 保留并注入 importer 旧路径的 `classify_paragraphs`、`ClassificationOptions`、`ParagraphFeatures` 和 `_feature_bool`。

快速门禁：
- Core、处理模式、审计加固和 Recognition decoder 测试退出码 0，`142 passed`；仅有既存重复 ZIP fixture 警告。
- `python -m compileall -q src/docxtool`、修改文件 Ruff 和 `git diff --check` 均通过。

快照：
- 同一 6 份样本、3 种模式、18 个案例；所有结构、metadata、Recognition、package 和 relationship 差异为 0。

下一项：
- 文档主链 pipeline 与 importer facade 收口。

## Phase A-3 Importer Loop 4：文档主链 pipeline

状态：passed

原位置：
- `src/docxtool/document/importer.py::DocxImporter.load` 的导入、分段、Legacy、Core、Recognition 和 Normalization 调度主体。

新位置：
- `src/docxtool/document/pipeline/document_pipeline.py::run_document_pipeline`

兼容入口：
- `DocxImporter.load` 保留原签名并只负责 python-docx 入口检查及 pipeline 委托。
- 新 pipeline 通过 importer 模块 facade 动态读取旧 patch 点，`_repair_broken_rels`、`_read_body_blocks`、`_build_logical_lines` 和 `apply_recognition` 仍命中真实执行。

快速门禁：
- Importer、处理模式、Core、Recognition、落款和 SDK 直接上下游测试退出码 0，`116 passed`。
- `python -m compileall -q src/docxtool`、修改文件 Ruff 和 `git diff --check` 均通过。

快照：
- 同一 6 份样本、3 种模式、18 个案例；所有比较字段差异为 0。

下一项：
- importer 兼容 re-export 与 monkeypatch 收口核验。

## Phase A-3 Importer Loop 5：兼容 facade 与 monkeypatch 核验

状态：passed

范围：
- `DocxImporter.load` 单一委托。
- 稳定模型和 Legacy context 旧导入路径。
- Reader、Segmentation 和损坏关系修复旧 monkeypatch 路径。

修改文件：
- `tests/test_importer_facade.py`

快速门禁：
- facade、关系修复、Phase A 快照工具、模型和 Legacy scoring 测试退出码 0，`19 passed`。
- `python -m compileall -q src/docxtool`、修改文件 Ruff 和 `git diff --check` 均通过。

下一项：
- Module 1 统一门禁；通过后按模块完成停止。

## Phase A-3 Module 1 门禁：Importer 收口

状态：passed

范围：
- 处理模式与文本/token 策略。
- Legacy 单段分类、上下文推进和 paragraph materialization。
- Core classifier adapter。
- 文档导入、分段、Legacy/Core、Recognition、Normalization 主链编排。
- importer 稳定导入和 monkeypatch facade。

模块门禁：
- Importer、处理模式、Core、Recognition、Legacy、落款、Segmentation、Normalization、SDK 和 Phase A 快照工具共 `202 tests` 通过。
- 修改文件 Ruff、`python -m compileall -q src/docxtool` 和 `git diff --check` 通过。
- `scripts/publish_to_github.ps1` 仅保留启动前已有 LF/CRLF 提示。

快照：
- 标准集 3 份、专项集 3 份，`strict`、`structural`、`normalize` 共 18 个案例。
- physical blocks、logical paragraphs、text/original_text、source spans、locator、inline tokens、Legacy/Core metadata、Recognition input/output、final types、package parts、relationships、document structure 和 missing relationship targets 差异均为 0。
- 迁移前后快照 JSON SHA-256 均为 `e7e2fa57a75696ae4f3667c0e55b9fde65c830c4f45556095ea667152f0e1749`。

兼容入口：
- `docxtool.document.importer.DocxImporter` 及原 `load` 签名。
- importer re-export 的 DocumentData、ParagraphData、ParagraphFeatures、InlineToken、DetectionContext、ScoreBoard 和 ScoreDetail。
- importer 旧 Reader、Segmentation、关系修复、Recognition 和 Normalization patch 点。

大型文件：
- `document/importer.py`：公开基准 `658e9da` 为 1088 行，本轮后 892 行。
- `DocxImporter.load`：公开基准为 328 行，本轮后 28 行。
- 新主链文件 `document/pipeline/document_pipeline.py` 为 221 行；各职责文件均保持单一实现。

停止原因：
- Module 1“Importer 收口”已完成并通过模块门禁。
- 下一待拆模块为 Recognition 内部拆分，本轮不进入。
- 快照和导出产物均位于 `%TEMP%`，未写入仓库。

## Phase A-3 Recognition Loop 1：Candidate providers

状态：passed

原位置：
- `src/docxtool/document/recognition/candidates.py`

新位置：
- `src/docxtool/document/recognition/providers/base.py`
- `structural.py`、`key_value.py`、`numbering.py`、`semantic.py`、`compatibility.py`
- `providers/__init__.py`

兼容入口：
- `recognition/candidates.py` 保留 Candidate、CandidateContext、CandidateProvider、9 个 provider 类、私有 helper 和 DEFAULT_PROVIDERS re-export。
- DEFAULT_PROVIDERS 对象和 provider 注册顺序保持不变。

快速门禁：
- facade、decoder 和审计加固测试共 `120 tests` 通过；两条重复 ZIP fixture 警告为既存测试构造。
- 修改文件 Ruff、`compileall` 和 `git diff --check` 通过。

快照：
- 标准集 3 份、专项集 3 份，3 种模式共 18 个案例；Recognition 输入输出、候选摘要、final type、文档结构、package 和 relationship 差异均为 0。

下一项：
- `global_context.py` 全文 context 拆分。

## Phase A-3 Recognition Loop 2：Document context

状态：passed

原位置：
- `src/docxtool/document/recognition/global_context.py`

新位置：
- `src/docxtool/document/recognition/context/model.py`
- `context/numbering.py`、`front.py`、`tail.py`、`analyzer.py`
- `context/__init__.py`

兼容入口：
- `recognition/global_context.py` 保留 `DocumentContext`、`HeadingFamily`、`analyze_document_context` 和原私有 helper 的 re-export。
- 旧路径和新路径的三个公开对象保持同一对象身份。

快速门禁：
- facade 和 decoder 直接测试共 `64 passed`。
- 修改文件 Ruff、`compileall` 和 `git diff --check` 通过。

快照：
- 当前快照工具默认捕获完整 50+5 集；Module 2 基线为固定 3+3 集，因此按源 SHA-256 筛回相同 6 份输入后比较。
- `strict`、`structural`、`normalize` 共 18 个案例，结构、metadata、Recognition、package 和 relationship 差异均为 0。

下一项：
- `decoder.py` 解码状态、路径选择、复核和诊断拆分。

## Phase A-3 Recognition Loop 3：Beam decoder

状态：passed

原位置：
- `src/docxtool/document/recognition/decoder.py`

新位置：
- `src/docxtool/document/recognition/decoding/model.py`
- `candidate_selection.py`、`transitions.py`、`review.py`、`pipeline.py`
- `decoding/__init__.py`

兼容入口：
- `recognition/decoder.py` 保留 `apply_recognition` 及原私有模型和 helper 的 re-export。
- `decoder.DEFAULT_PROVIDERS` 继续作为真实执行 patch 点，由 facade 在调用时注入新 pipeline。

快速门禁：
- facade、decoder 和审计加固测试共 `122 passed`；两条重复 ZIP fixture 警告为既存测试构造。
- 修改文件 Ruff、`compileall` 和 `git diff --check` 通过。

快照：
- 固定 3 份标准集、3 份专项集，3 种模式共 18 个案例。
- 迁移前后快照 SHA-256 均为 `e7e2fa57a75696ae4f3667c0e55b9fde65c830c4f45556095ea667152f0e1749`，差异为 0。

下一项：
- Module 2 统一门禁；通过后按模块完成停止。

## Phase A-3 Module 2 门禁：Recognition 内部拆分

状态：passed

范围：
- Candidate provider 注册和实现。
- 文首、正文边界、尾部与同级标题族全文上下文。
- Beam 数据模型、候选汇集、状态转移、hard veto、review 和主解码管线。
- 旧 candidates、global_context、decoder 导入和 monkeypatch facade。

模块门禁：
- 全部 `test_recognition_*` 与导入、处理模式、分段、落款、审计、SDK 和 Phase A 快照直接上下游共 `273 tests` 通过。
- Recognition 全目录和相关测试 Ruff、`python -m compileall -q src/docxtool`、PowerShell 发布脚本语法及 `git diff --check` 通过。
- 两条重复 ZIP fixture 警告为既存安全测试构造；发布脚本 LF/CRLF 提示为开始前已有状态。

快照：
- 标准集 3 份、专项集 3 份，`strict`、`structural`、`normalize` 共 18 个案例。
- physical blocks、logical paragraphs、text/original_text、source spans、locator、inline tokens、Legacy/Core metadata、Recognition input/output、final types、package parts、relationships、document structure 和 missing relationship targets 差异均为 0。
- 迁移前后快照 JSON SHA-256 均为 `e7e2fa57a75696ae4f3667c0e55b9fde65c830c4f45556095ea667152f0e1749`。

兼容入口：
- `recognition/candidates.py`、`global_context.py`、`decoder.py`。
- `decoder.DEFAULT_PROVIDERS` 仍控制真实 `apply_recognition` 执行。

大型文件：
- `candidates.py`：拆分前 732 行，兼容 facade 56 行；最大 provider 文件 203 行。
- `global_context.py`：拆分前 828 行，兼容 facade 83 行；最大 context 文件 443 行。
- `decoder.py`：拆分前 637 行，兼容 facade 62 行；最大 decoding 文件 302 行。

停止原因：
- Module 2“Recognition 内部拆分”已完成并通过模块门禁。
- 下一待拆模块为 Web app 收口，本轮不进入。
- 快照和导出产物均位于 `%TEMP%`，未写入仓库。

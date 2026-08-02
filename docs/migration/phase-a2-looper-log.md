# Phase A-2 Looper 日志

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

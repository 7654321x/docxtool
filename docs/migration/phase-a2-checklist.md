# Phase A-2 检查清单

状态：`completed`。本文是已完成迁移的执行记录，不再作为当前待办或当前架构来源。

## 阶段范围

Phase A-2 只抽取导入后规范化编排与物理读取职责，保持现有 importer 兼容入口、处理模式和可观察 DOCX 行为不变。它不进入 Phase B 的识别规则优化，也不修改渲染、WPS 或其他宿主代码。

本清单记录阶段验证状态，不替代 Git 工作树状态或发布状态。每次迁移职责完成后，按 `codex-workflow.md` 更新本文件。

## 已完成项

- 抽取 `src/docxtool/document/importing/reader.py`，承接 DOCX 物理读取和 body 块提取职责，保留 importer 兼容 facade。
- 抽取 `src/docxtool/document/normalization/pipeline.py`，承接导入后规范化编排，保留既有处理模式语义。
- 将物理段落初始 SourceTape/locator 字段构建从 `src/docxtool/document/importing/features.py` 迁移到 `src/docxtool/document/segmentation/source_locator.py::build_physical_source_features`；`extract_paragraph_features` 和旧 importer `extract_features` facade 保持原参数、返回值和 monkeypatch 边界。
- 将现有 Word 原生列表与 Heading 样式前缀的应用顺序从 `src/docxtool/document/importing/features.py` 迁移到 `src/docxtool/document/importing/numbering.py::apply_physical_numbering_features`；仍只写入既有 `@lvl_N` / `@style_headingN` 前缀，不新增编号模型或识别事实。
- 将 run 有效格式、source run span、首个有效 run、段落对齐和首行缩进读取从 `src/docxtool/document/importing/features.py` 迁移到 `src/docxtool/document/importing/physical_format.py::apply_physical_format_features`；保留原游标、空白 run、异常吞吐、单位换算和 segment 聚合顺序。
- 将 logical source span 计划、软换行/粘连拆分选择和整段 inline token 保留策略从 `src/docxtool/document/segmentation/pipeline.py` 迁移到 `src/docxtool/document/segmentation/partition.py`；`pipeline.build_logical_span_plan` 保留同签名 facade，真实 logical-line 编排继续经过该入口。
- 将可见文字遗漏、source span 重叠和越界校验从 `src/docxtool/document/segmentation/boundaries.py` 迁移到 `src/docxtool/document/segmentation/conservation.py`；boundaries 与 importer 私有入口保留同签名转发和原异常文本。
- 保持 `src/docxtool/document/importer.py` 作为兼容入口，不改变对外导入路径。
- 新增 `scripts/phase_a_equivalence_snapshot.py`，用于脱敏比较物理块、逻辑段、provider 开关前后识别输入/输出，以及完整 OPC package 的部件和关系。
- 加固 Legacy provider 对照契约：新命令只切换 `LegacyCandidateProvider`，输入不变性和 final type、review、diagnostics、候选摘要等输出差异分别报告；旧命令保留弃用别名。
- 加固 DOCX package 等价比较：覆盖全部 package part、内容类型和 `.rels`，验证内部 relationship target，并只对 core property 时间文本执行书面字段级规范化。
- 新增物理读取与规范化编排的聚焦回归测试。

## 阶段边界

- `document/importing/` 当前授权的物理读取职责已完成并通过模块门禁。
- `document/segmentation` 已完成当前授权职责；执行模块门禁后停止，不进入 normalization 或 Phase B。
- 任何发现的未解释快照、测试或文档回归差异必须先记录为 `blocked`，不得并入下一阶段处理。
- Phase B 的识别规则、候选评分和渲染行为优化必须另行立项，不得作为 Phase A-2 的附带改动。

## 新文件位置

| 路径 | 职责 |
| --- | --- |
| `src/docxtool/document/importing/reader.py` | DOCX 物理读取、body XML 顺序、表格/图片/分节事实提取 |
| `src/docxtool/document/importing/physical_format.py` | run 有效格式、source run span、段落对齐和首行缩进物理事实 |
| `src/docxtool/document/segmentation/partition.py` | logical source span 计划、软换行/粘连拆分选择和 inline token 保留策略 |
| `src/docxtool/document/segmentation/conservation.py` | 可见文字、source span 顺序、重叠、空洞和越界守恒校验 |
| `src/docxtool/document/segmentation/source_locator.py` | 物理段初始 SourceTape/locator 构建及逻辑段 source span 映射 |
| `src/docxtool/document/normalization/pipeline.py` | 导入后规范化步骤编排，不新增识别裁决 |
| `scripts/phase_a_equivalence_snapshot.py` | 脱敏的迁移前后等价快照与比较 |
| `tests/test_importing_reader.py` | 物理读取职责回归 |
| `tests/test_normalization_pipeline.py` | 规范化编排职责回归 |
| `docs/migration/codex-workflow.md` | 迁移执行规则、门禁、快照与报告格式 |

## 已执行验证

- Python 3.8 全量测试：`1106 passed`，保留 3 条既有警告。
- Ruff：`src`、`tests` 和 `scripts` 检查通过。
- Node 前端和 worker 路由测试：`11 passed`。
- Python 3.10 干净环境：依赖安装与迁移相关测试通过。
- wheel 干净安装、SDK/CLI 冒烟和最小绑定验证通过。
- 标准集 50 篇与专项集 5 篇在 `strict`、`structural`、`normalize` 三种模式下的迁移前后快照共 165 组，无差异。
- `LegacyCandidateProvider` 开关前后的 Recognition 入口输入比较共 165 组，无差异；该实验不关闭 importer Legacy preprocessing，输出差异独立记录，真实 importer bypass 在报告中标为 `blocked`。
- 等价工具微批次直接测试：`tests/test_phase_a_equivalence_snapshot.py` 共 9 项通过；脚本与源码 `compileall` 通过，脚本和直接测试 Ruff 通过。
- 两个脱敏 WPS fixture 的 package manifest 冒烟通过：每份 17 个部件、13 条关系、缺失内部目标 0；未读取或输出正文。
- 物理段 SourceTape/locator 单职责迁移：4 个直接相关测试文件共 19 项通过，`compileall` 和本轮 Python 文件 Ruff 通过；基础标题正文与软换行空格两个脱敏 fixture 的物理块、logical lines、source runs/spans、locator、文本哈希、inline tokens、Recognition 输入及完整 package manifest 差异均为 0，缺失 relationship target 为 0。
- Word numbering 物理应用单职责迁移：4 个直接相关测试文件共 27 项通过，`compileall` 和修改文件 Ruff 通过；原生 Word 列表与纯手写编号两个脱敏 fixture 的 `numId`、`ilvl`、abstract 映射、源/输出 numbering 部件、物理块、logical lines、locator、inline tokens、Recognition 输入和最终结构差异均为 0，缺失 relationship target 为 0。当前生产模型不保存完整 `numId/abstractNumId/numFmt/lvlText`；Phase A 不新增这些字段。
- Paragraph/run 物理格式单职责迁移：3 个直接相关测试文件共 74 项通过，保留 2 条既有重复 ZIP fixture 警告；`compileall` 和修改文件 Ruff 通过。混合直接格式和样式继承两个脱敏 fixture 的 run 数量、字体、字号、粗斜体、下划线、source spans、段落对齐/缩进、locator、inline tokens、Recognition 输入和输出 package 差异均为 0，缺失 relationship target 为 0。
- Importing 模块门禁：9 个 importing/importer/locator/section 相关测试文件共 63 项通过；模块及相关测试 Ruff、`compileall` 通过。6 份脱敏 fixture 在 `strict`、`structural`、`normalize` 三种模式共 18 个迁移前后案例中，package part、relationship、normalized metadata、document structure 差异均为 0，缺失 relationship target 为 0。`document/importing/` 当前授权职责完成，按阶段停止。
- Segmentation source span 计划微任务：5 个直接相关测试文件共 49 项通过，`compileall` 和修改文件 Ruff 通过；tab token 保留及“编号标题 + 正文 + 分页/软换行称呼”两个脱敏 fixture 的 physical blocks、logical lines、source spans、locator、inline tokens、Recognition 输入和输出 package 差异均为 0，缺失 relationship target 为 0。
- Segmentation 守恒校验微任务：5 个直接相关测试文件共 43 项通过，`compileall` 和修改文件 Ruff 通过；同组两个脱敏 fixture 的文字哈希、logical lines、source spans、locator、inline tokens、Recognition 输入和输出 package 差异均为 0，缺失 relationship target 为 0。
- Segmentation 模块门禁：7 个 segmentation/importer/SDK 相关测试文件共 65 项通过；模块及相关测试 Ruff、`compileall` 通过。6 份脱敏 fixture 在 `strict`、`structural`、`normalize` 三种模式共 18 个迁移前后案例中，source span/token 守恒成立，package part、relationship、normalized metadata、document structure 和 Recognition 输入差异均为 0，缺失 relationship target 为 0。`document/segmentation/` 当前授权职责完成，按模块停止。

## 已知非阻断说明

- 两条 ZIP 重复成员警告来自安全校验 fixture，属于测试构造的预期警告。

## Phase A-3 Module 1 补记

状态：passed

- `document/importer.py` 已收口为稳定模型/私有 helper re-export、monkeypatch facade 和薄 `DocxImporter.load` 入口。
- 处理模式与文本/token 策略迁移到 `document/pipeline/options.py`。
- ParagraphData 构造迁移到 `document/pipeline/paragraph_materialization.py`。
- Legacy 单段分类和 stream 上下文推进迁移到 `recognition/legacy/classifier.py`、`recognition/legacy/pipeline.py`。
- Core adapter 迁移到 `recognition/core_adapter.py`。
- 文档主链迁移到 `document/pipeline/document_pipeline.py`；导入、分段、Legacy/Core、Recognition 和 Normalization 顺序不变。
- 模块直接与上下游门禁共 `202 tests` 通过；修改文件 Ruff、`compileall` 和 `git diff --check` 通过。
- 6 份脱敏样本在 3 种模式下共 18 个迁移前后案例，所有快照与 package/relationship 比较差异为 0。
- 下一待拆模块：Recognition 内部 `candidates.py`、`global_context.py`、`decoder.py`；本轮未进入。
- 一条 `python-docx` 样式 ID 弃用警告来自既有测试依赖，未改变阶段行为。

## Phase A-3 Module 2 补记

状态：passed

- 候选提供器迁移到 `recognition/providers/`；`candidates.py` 保留注册顺序和旧 helper facade。
- 全文上下文迁移到 `recognition/context/`；`global_context.py` 保留公开模型、分析器和旧 helper facade。
- Beam 解码迁移到 `recognition/decoding/`；`decoder.py` 保留 `apply_recognition` 和 `DEFAULT_PROVIDERS` patch 点。
- Recognition 与直接上下游统一门禁通过；修改文件 Ruff、`compileall` 和 `git diff --check` 通过。
- 固定 6 份脱敏样本在 3 种模式下共 18 个迁移前后案例，快照 SHA-256 完全一致，差异为 0。
- 下一待拆模块：Web app 收口；本轮不进入。

## Phase A-3 Final Looper 补记

状态：passed

- Web 已拆为 bootstrap、runtime state、动态 compatibility facade 和 Handler；`web.app` 保留旧 import、monkeypatch 和薄启动入口。
- Engine 已拆为共享 render context、特殊对象分派、段落渲染器、导出最终化和薄 pipeline；`engine.core.export_doc` 保留公开签名和旧 patch surface。
- Web 模块门禁 433 项通过，Node 11 项通过，HTTP 和 import-time 契约快照差异为 0。
- Engine 模块门禁 197 项通过，固定 6 篇、3 种模式完整 package 快照差异为 0。
- Phase A 最终门禁在 Python 3.8、3.10 分别完成 1138 项测试；全量 Ruff、compileall、Node、wheel/sdist、隔离 wheel 冒烟均通过。
- 固定 50 个标准稿和 5 个专项稿在 3 种模式下共 165 个迁移前后案例差异为 0；15 篇文档和 1 个模板完成视觉渲染，失败为 0。
- Phase A 文件拆分至此收口；后续功能准确率和模板 P1 归因只允许在 Phase B 独立处理。

后续每一项迁移必须在本文件补充：职责、文件位置、执行命令、结果、快照差异数和是否已停止。

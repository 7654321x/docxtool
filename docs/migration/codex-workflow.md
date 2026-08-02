# DocxTool 迁移执行工作流

## 适用范围与优先级

本规则用于声明为“机械迁移”或“行为保持重构”的任务，尤其适用于导入、识别、分段、规范化和渲染链路的文件拆分。它补充而不替代仓库根目录 `AGENTS.md`、安全约束、DOCX 回归清单和发布规则；发生冲突时，`AGENTS.md` 与安全规则优先。

机械迁移的目标是改变代码组织，而不是改变可观察行为。业务规则、默认配置、识别分类、文本处理、JSON 协议、DOCX 输出和外部接口的变化必须作为独立任务说明并单独验收。

## 永久执行原则

1. 每轮只处理一个主要职责，例如抽取一个物理读取器、迁移一个规范化编排器或建立一组等价测试。
2. 开始前先阅读被迁移模块、调用方、兼容入口、相关测试和已有快照；先明确输入、输出、异常和副作用边界。
3. 机械迁移不得修改业务行为。若必须修复业务问题，应停止当前迁移，单独记录问题和影响范围后再启动行为变更任务。
4. 默认只运行当前职责的快速门禁；达到模块、阶段或发布里程碑时再运行扩展门禁。
5. 完成当前职责并通过其门禁后停止。不得自动开始下一职责、下一阶段、提交或推送。
6. 发现未解释的行为差异、快照差异或测试回归时，立即标记为 `blocked`。不得以更新基线、跳过测试、放宽断言或临时补丁规避差异。

## 快速门禁

每个迁移职责至少执行以下检查，并以实际模块替换示例路径：

```pwsh
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m pytest -q tests/test_importing_reader.py tests/test_normalization_pipeline.py"
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m ruff check src/docxtool/document/importing src/docxtool/document/normalization tests/test_importing_reader.py tests/test_normalization_pipeline.py"
```

还必须运行被迁移模块现有调用方的测试。快速门禁只适用于尚未完成的单一职责；它不能替代项目级回归。

## 模块门禁

完成一个模块抽取时，应同时确认：

- 原兼容入口仍可导入，公开函数、参数、返回值和异常边界保持不变；
- 调用方不再依赖被迁移模块的内部细节；
- 新模块只承担声明的职责，不反向引入业务裁决；
- 原模块与新模块的相关单元测试全部通过；
- 对 DOCX 链路，严格、结构拆分保真和规范化三种处理模式均有覆盖。

涉及导入、分段、识别、规范化或渲染的模块，还应运行最小等价快照并检查物理块、逻辑段、定位、最终类型、审核结果，以及完整 OPC package 的部件、内容类型和关系。

## 里程碑门禁

在完成一个 Phase、准备发布或用户要求完整验证时，执行：

```pwsh
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m pytest -q"
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m ruff check src tests scripts"
pwsh -NoProfile -Command "node --test tests/frontend-format-config.test.mjs"
pwsh -NoProfile -Command "node --test tests/worker-routing.test.mjs"
```

如改动触及 DOCX 主链路，还必须遵守 `docs/DOCX_REGRESSION_CHECKLIST.md`：执行相应批量文档处理、结构审计、模板对齐和可用时的视觉抽查。发布前的完整流程以 `docs/RECOGNITION_RELEASE.md` 和 `scripts/publish_to_github.ps1 -Verify` 为准。

## 快照比较方法

1. 在隔离的迁移前工作树执行 `scripts/phase_a_equivalence_snapshot.py capture`，生成脱敏的 before 快照。
2. 在当前工作树以相同输入、相同配置和相同处理模式生成 after 快照。
3. 使用 `compare` 比较两份快照，并使用 `legacy-provider-input-invariance` 检查 `LegacyCandidateProvider` 开关是否意外改变 Recognition 入口输入；该实验不关闭 importer Legacy preprocessing。
4. 快照只能记录长度、哈希、类型、定位、诊断，以及 package part 和 relationship 的脱敏 manifest，不得写入正文、绝对用户路径、密钥或日志原文。
5. 任一未解释差异都必须在当前职责内恢复或得到用户明确批准；否则状态为 `blocked`，不得进入后续职责。

示例：

```pwsh
$work = Join-Path $env:TEMP "docxtool-phase-a"
python .\scripts\phase_a_equivalence_snapshot.py capture --output "$work\after.json"
python .\scripts\phase_a_equivalence_snapshot.py compare `
  --before "$work\before.json" `
  --after "$work\after.json" `
  --output "$work\comparison.json"
python .\scripts\phase_a_equivalence_snapshot.py legacy-provider-input-invariance `
  --output "$work\legacy-provider-input.json"
```

## 每轮报告格式

每轮结束仅报告以下内容：

1. 当前职责和状态：`completed` 或 `blocked`。
2. 修改的模块和兼容边界。
3. 执行的快速门禁、模块门禁或里程碑门禁及结果。
4. 快照比较范围、差异数量及其解释；`blocked` 时给出脱敏证据和下一步所需条件。
5. 阶段清单更新位置和未启动的后续职责。

除非用户明确要求，报告后停止，不提交、不推送，也不开始下一阶段。

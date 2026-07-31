# 文档识别架构

导入流程现在按以下顺序工作：

```text
DOCX 块抽取 -> 统一特征 -> 文档模式 -> 候选提供器 -> 硬约束 -> Beam Search
-> 结构树 -> 结构校验 -> 兼容 type_id -> 现有渲染器
```

## 目录

`src/docxtool/document/recognition/` 包含识别层：

- `features.py`：保留原文的块模型和共享特征。表格、图片、空段和分页标记不会被静默丢弃。
- `model.py`：`DocumentMode`、`SectionKind`、`ParagraphType` 三层模型。
- `candidates.py`：结构、键值、编号、语义、旧分类器和样式候选提供器。旧分类结果只作为兼容候选。
- `decoder.py`：硬结构否决和宽度可配置的确定性 Beam Search；默认宽度为 12。
- `compatibility.py`：内部段落类型到旧渲染 `type_id` 的唯一映射边界。
- `validators.py`：有限结构序列校验。
- `diagnostics.py`：只输出结构信息，不输出源文档正文、OOXML 或敏感字段。
- `config.py` / `version.py`：集中管理 Beam 宽度、候选上限、诊断开关和引擎/schema 版本。

## 关键规则

- 结构化发文字号优先于标题续行；`dispatch_number` 不会被标题视觉样式覆盖。
- 会议纪要通过标题、会议元数据和正文信号联合判断；带可选编号的 `出席/缺席/列席` 仍属于会议元数据。
- 签发日期或来源说明后的独立规划、方案、报告等标题可识别为被印发文件标题。
- 非 `REPORT` 模式不会设置 `report_first_sentence_bold`。
- Docxtool 自身样式不能单独否决文本结构，幂等复跑保留相同类型和诊断结果。

## 诊断

导入后的 `DocumentData.recognition_diagnostics` 可用于日志或测试；通过
`diagnostics_to_json()` 序列化时只保留模式、块索引、类型、板块、候选来源和校验结果，
不会包含原文。

诊断结构版本为 `1.0`，识别引擎版本为 `3.0`。关闭诊断只省略候选轨迹，
不会改变候选、排序或最终类型；文本预览使用 SHA-256 短哈希。

## 性能

执行 `python scripts/benchmark_recognition.py` 可获得 25、200、800 段文档的
块抽取、特征提取、模式识别、解码/校验/结构树和总耗时 JSON。脚本只使用内存对象，
不会写入 DOCX 或修改仓库文件。

## 回归

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests scripts
node --test tests/worker-routing.test.mjs
node --test tests/frontend-format-config.test.mjs
```

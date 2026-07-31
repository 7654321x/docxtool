# 识别来源定位与宿主绑定

## 问题与根因

DOCX 的一个物理段落可含标题、正文、日期或附件等多个逻辑结构。旧流程在
拆分逻辑文字后使用 `find()` 回查原文；重复短语、空白规范化或软换行会使
该回查指向错误 occurrence。分类正确并不等于文字绑定正确。

## SourceTape

导入器为每个物理段落创建不可变 `SourceTape`：

- `raw_text`：DOCX 物理段落的原始文字视图；
- `canonical_text`：仅统一 CR/LF、普通/全角/NBSP 空格及 Unicode NFKC 的
  宿主比较视图；
- raw 与 canonical 的 UTF-16 边界映射。

逻辑拆分先计算 raw 字符范围，再从范围产生识别文本。范围不可由第三方
DOCX 的段落号推断。`raw_*_utf16` 和 `canonical_*_utf16` 仅属于各自的
字符串坐标系，均不是 WPS/Word API Range。

每个 `RecognitionBlock` 提供物理段落哈希、同文本出现序号、片段序号和
片段总数。确认定位必须满足范围读回、哈希、顺序与非重叠校验。失败会返回
`SOURCE_RANGE_UNRESOLVED`、`SOURCE_RANGE_OVERLAP`、
`SOURCE_TEXT_HASH_MISMATCH` 或 `SOURCE_OCCURRENCE_AMBIGUOUS`，不会退回裸
逻辑段落编号。

## SDK 协议

`locator_version="source-locator-v2"` 增加以下稳定字段：

- `raw_start_utf16` / `raw_end_utf16`；
- `canonical_start_utf16` / `canonical_end_utf16`；
- `segment_index` / `segment_count`；
- `source_locator_status`、`source_locator_evidence`、`source_locator_warnings`；
- raw/canonical 片段、物理段落和上下文哈希。

`RecognitionPlan` 还包含 `package_version` 和
`host_text_contract_version=host-text-v1`。`segment_format` 从与 raw span
相交的 DOCX run 按可见字符权重统计；一个 run 跨越标题和正文时，其格式
权重分别归入两个逻辑片段。

旧 `range_start_utf16` / `range_end_utf16` 保持存在，固定为 raw source
offset 的兼容别名。分类证据使用 `classification_confidence`、
`classification_evidence` 与 `review_*` 字段；来源定位和宿主绑定使用独立
的状态、证据和置信度，二者不能混用。

正文默认脱敏。`include_text=True` 才会返回识别文本，`include_raw_text=True`
才会返回原始片段；这两项只允许本机受控调用，禁止写普通日志。

## 宿主绑定

`bind_recognition_plan(plan, host_snapshot)` 只读接收通用快照：宿主类型、
可选文档标识和 main story 非表格物理段落的 raw 文本。它先用动态规划进行
全文保序对齐，再按每个物理段落的 raw 或 canonical 全文匹配验证片段。

- raw 完全一致：输出 `confirmed`，并给出 host snapshot raw UTF-16 范围；
- canonical 完全一致：通过 host 自身 `SourceTape` 重新映射 raw 范围，输出
  `review` 并标记 `RAW_TEXT_NORMALIZED`；
- 重复文本无法由顺序消歧、范围/哈希不匹配或任一片段重叠：输出
  `unresolved`。

返回的 host offset 仍不是 WPS Range。WPS 端应重新读取目标段落后验证哈希，
再按自身 API 生成 Range。同一物理段落有多个片段时，必须联合、保序验证；
混合段无法安全拆分时，WPS 命令层应拒绝应用并返回
`MIXED_PARAGRAPH_REQUIRES_SPLIT`。

## HostParagraphTextContract V1

宿主传入的 `raw_text` 只能表示可见段落内容。`host-text-v1` 将 CRLF、CR、
LF 和垂直制表符统一为 LF，保留 Tab 与分页符，归一 NBSP、全角空格和 NFKC
字符。末尾 `U+0007` 表格单元格标记不进入 canonical 文本并产生警告。
`canonicalize_host_paragraph_text()` 返回 raw/canonical UTF-16 映射；未知
版本返回 `UNSUPPORTED_HOST_TEXT_CONTRACT`。

## 局部歧义与计数

全文对齐仍是保序动态规划，但每个 source 物理段落独立输出
`matched_unique`、`matched_review`、`ambiguous` 或 `unmatched`。重复文本只在
本段落组出现多个最优候选时返回 `unresolved`，不污染其他唯一段落。

`segment_count_total` 为全部逻辑片段数，`segment_count_located` 为拥有合法
来源范围的数量，`segment_count_confirmed` 为确认可读回的数量。计数不完整时，
WPS 端只能预览，不能自动应用格式。

## 回归与边界

自动测试覆盖同段标题与正文、重复文字、宿主插入段落、NBSP、Emoji/UTF-16
代理对、canonical 回写范围、CLI 快照绑定和歧义拒绝。当前不调用或验证真实
WPS API；WPS 插件只能消费上述只读契约，不能复制识别规则。

验证命令：

```pwsh
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m pytest -q tests/test_sdk.py tests/test_sdk_binding.py tests/test_recognition_decoder.py tests/test_importer_heading_flow.py"
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m ruff check src tests scripts"
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m build"
```

# 本地识别 SDK

`docxtool.sdk` 是面向本机集成的只读 DOCX 识别接口。它不启动 Web 服务、不建立用户会话、不写任务数据库，也不生成排版后的 DOCX。

SDK 的设计用途是让 WPS、Word 加载项或其他本地软件先取得文档结构判断，再由宿主软件调用自身 API 修改当前打开的文档。

## 安装

```pwsh
python -m build
pip install dist/docxtool-*.whl
```

支持 Python 3.8 到 3.10。

## Python 调用

```python
from docxtool.sdk import recognize_docx

plan = recognize_docx(
    "input.docx",
    processing_mode="structural",
    recognition_mode="authoritative",
)
print(plan.to_dict())
```

`processing_mode` 的含义与网页端一致：

- `strict`：保留物理段落；
- `structural`：默认，仅拆分有充分证据的结构边界；
- `normalize`：允许更多文字与编号规范化。

`recognition_mode` 支持 `legacy`、`shadow`、`authoritative`。生产集成默认使用 `authoritative`。

可通过 `format_config` 传入与网页端相同的格式配置对象；未传入时使用软件内置默认配置。

## 返回结果

`RecognitionPlan` 是版本化 JSON 安全对象，包含：

- 文档模式与识别引擎版本；
- 每个块的类型、板块、格式角色和段落锚点；
- 原始物理段落与逻辑片段的 raw/canonical UTF-16 来源范围；
- 原文、前邻、后邻的 SHA-256 短哈希；
- 需要人工复核的脱敏依据。

计划默认不含正文文字、原始路径、Cookie、密钥、日志或数据库信息。

`range_start_utf16`、`range_end_utf16` 为兼容字段，语义固定为
`source_raw_text_utf16`。它们只描述 SDK 从 DOCX 提取的原始物理段落
文字，**不是 WPS/Word Range 坐标**。新接口同时返回：

- `raw_start_utf16` / `raw_end_utf16`；
- `canonical_start_utf16` / `canonical_end_utf16`；
- `segment_index` / `segment_count`；
- `segment_count_total` / `segment_count_located` / `segment_count_confirmed`；
- `source_locator_status`、证据和警告；
- `segment_format`，包含以 run 交集统计的字体、字号、粗体比例和混排标记；
- `segment_format.font_name_east_asia`、`font_name_ascii`、`font_size_pt`、
  粗体/斜体/下划线字符比例、直接格式/继承格式比例、可见字符数、格式覆盖率、
  来源层级及警告。有效格式依次解析 run 直接 `rPr`、字符样式、段落样式、
  `basedOn`、`docDefaults` 和主题字体；未知格式不会被当作 `false`；
- `text_length_utf16`，即识别文字片段的 UTF-16 code unit 长度；
- raw/canonical 片段及前后上下文的哈希。

`source_locator_status` 为 `confirmed` 时，raw 片段能够从原始物理段落
范围读回；`review` 或 `unresolved` 均不得被宿主自动修改。

`segment_count` 是完整逻辑片段组的兼容计数。新调用方应使用
`segment_count_total`、`segment_count_located` 和 `segment_count_confirmed`
确认片段组完整；任一片段未确认时不得直接一键写入。

默认不返回文字。仅本机受控链路可使用 `include_text=True` 返回
`recognized_text` 与 canonical 片段；`include_raw_text=True` 会额外返回
原始片段，可能包含敏感正文，调用方不得写入普通日志或上传到网络。

## 宿主快照绑定

WPS、Word 或其他编辑器应先取得当前文档的本地段落快照，再调用
`bind_recognition_plan()`。该函数不依赖任何编辑器 API，也不会修改文档：

```python
from docxtool.sdk import bind_recognition_plan, recognize_docx

plan = recognize_docx("snapshot.docx")
binding = bind_recognition_plan(plan, {
    "host_type": "wps",
    "document_identity": "optional-local-id",
    "paragraphs": [
        {"host_paragraph_index": 0, "raw_text": "当前物理段落文字"},
    ],
})
```

绑定按完整物理段落 raw 文本、canonical 文本、哈希、全文单调顺序、重复
occurrence 及同段逻辑片段顺序交叉验证。结果为：

- `confirmed`：可以由宿主进一步转换为自身 Range；
- `review`：仅可供人工预览；
- `unresolved`：必须跳过，不能猜测段落或 Range。

`host_raw_start_utf16` / `host_raw_end_utf16` 只描述传入快照的 `raw_text`，
同样不是 WPS Range 坐标。WPS 端必须再次验证当前段落文本后才能换算和
应用格式。绑定结果还提供 `host_canonical_start_utf16` /
`host_canonical_end_utf16`，它们只属于 host canonical text，不能与 raw
offset 互换。混合物理段落必须按所有 `segment_index` 联合验证；正式排版前如
仍无法拆分，应返回 `MIXED_PARAGRAPH_REQUIRES_SPLIT`。

### HostParagraphTextContract V1

`RecognitionPlan.host_text_contract_version` 和绑定结果均声明
`host-text-v1`。宿主 `raw_text` 是可见段落文字，不应包含编辑器隐式段落
结束标记或表格单元格结束标记。canonical 规则为：

- `\r\n`、`\r`、`\n` 和手动换行 `\v` 统一为 `\n`；
- Tab `\t` 与分页符 `\f` 保留；
- NBSP、全角空格统一为普通空格，并执行 Unicode NFKC；
- 行尾 `U+0007` 表格单元格标记不参与 canonical 文本，并返回警告；
- raw 与 canonical offset 均为 UTF-16 code unit，必须经契约映射转换。

SDK 提供 `canonicalize_host_paragraph_text(raw_text)`。未知版本返回
`UNSUPPORTED_HOST_TEXT_CONTRACT`。绑定状态含义如下：

- `confirmed`：raw 文本、片段读回、哈希与顺序都精确匹配；
- `review`：canonical 精确但 raw 表达不同，只能预览；
- `unresolved`：歧义、缺失、越界或哈希不一致，必须跳过。

Python 与 WPS TypeScript 端共用的脱敏金标为
[`HOST_TEXT_V1_GOLDEN.json`](HOST_TEXT_V1_GOLDEN.json)。它覆盖 CRLF、手动
换行、分页符、Tab、NBSP、全角空格、表格末尾标记、Emoji、已确认/复核/未定位
绑定以及不完整片段组；集成方应使用同一文件验证 canonical 文本和边界映射。

重复文本歧义按物理段落组局部处理。`binding.physical_paragraphs` 会列出
每组候选宿主段落、最终状态与证据，不会让一个歧义组污染其他唯一段落。

## 命令行

```pwsh
docxtool-recognize input.docx --mode structural --output recognition-plan.json
```

`--config format.json` 可传入格式配置文件。命令行输出同样不包含正文。
`--include-text` 与 `--include-raw-text` 均需显式开启；后者仅限本机调试。
使用 `--host-snapshot snapshot.json` 可在同一次调用中输出脱敏绑定结果。

`2.0` 起新增跨语言统一入口：

```pwsh
docxtool-sdk manifest
docxtool-sdk recognize --source input.docx --request request.json --output plan.json
docxtool-sdk bind --plan plan.json --snapshot snapshot.json --output binding.json
docxtool-sdk validate --kind recognition-plan --input plan.json
docxtool-sdk validate --kind host-snapshot --input snapshot.json
docxtool-sdk validate --kind recognition-binding --input binding.json
```

所有新命令都使用统一 envelope：

```json
{"ok": true, "data": {}}
```

失败时返回：

```json
{"ok": false, "error": {"schema_version": "sdk-error-v1", "code": "INVALID_HOST_SNAPSHOT", "message": "简短错误", "retryable": false, "details": {"path": "snapshot_id"}}}
```

## Integration Contract v1

公共跨语言协议为 `integration-contract-v1`，由以下对象组成：

- `SdkManifest`
- `RecognitionRequest`
- `RecognitionPlan`
- `HostSnapshot`
- `RecognitionBinding`
- `SdkError`

JSON Schema 是正式协议来源，随 wheel 安装在：

```text
docxtool/resources/schemas/
```

Python dataclass 只是该协议的一种实现。宿主不能通过包版本猜测能力，应先调用
`get_sdk_manifest()` 或 `docxtool-sdk manifest` 检查支持的 contract、schema、
locator、host-text 和 offset encoding 版本。

## Stable IDs

新调用方应优先使用以下稳定 ID：

- `RecognitionPlan.plan_id`
- `RecognitionBlock.block_id`
- `RecognitionBlock.physical_group_id`
- `HostSnapshot.snapshot_id`
- `HostParagraph.host_paragraph_id`
- `RecognitionBinding.binding_id`

`block_index`、`host_paragraph_index`、`source_paragraph_index` 继续作为兼容字段保留，
但不能作为长期唯一标识。

`plan_id` 由来源文件 SHA-256、协议版本、识别模式和配置摘要确定性生成，不含路径
或正文。`block_id` 由 `plan_id`、物理段落组、片段序号和片段哈希生成。`snapshot_id`
由宿主生成；旧输入缺失时 SDK 仅为兼容绑定合成临时 ID，但正式 v1 schema 校验会拒绝。

## Binding Preconditions

`RecognitionBinding` 不是可直接执行的编辑器 Range。`confirmed` 块只表示宿主可以继续
执行真实 Range 读回验证。每个 confirmed 结果都带有：

- `plan_id`
- `snapshot_id`
- `document_identity`
- `document_revision`
- `host_paragraph_id`
- 宿主物理段落 raw/canonical SHA-256
- raw/canonical fragment SHA-256
- `text_contract_version`
- `offset_encoding`

宿主写入前必须重新读取当前段落、按 `host-text-v1` 生成 raw/canonical 文本、校验物理
段落哈希和片段哈希，再创建真实 Range 并读回确认。`review` 只能预览，`unresolved`
必须跳过。

## WPS 集成边界

SDK 只负责识别，不直接操作 WPS。未来 WPS 加载项应：

1. 保存或导出当前文档的临时 DOCX 快照；
2. 调用本机 SDK 获取 `RecognitionPlan`；
3. 校验段落锚点未变化；
4. 使用 WPS API 将类型和格式角色写回当前打开的文档。

这样不会通过云端上传文档，也不需要让最终用户自行管理 Python wheel。

同样，SDK 不调用 Office.js、VSTO、COM 或 WPS 原生 API。Word/WPS 适配器需要自行实现：

1. 从当前打开文档生成 `HostSnapshot`；
2. 调用 SDK；
3. 根据 `RecognitionBinding` 找到候选段落；
4. 通过宿主 API 创建真实 Range；
5. 读回 Range.Text 并验证 preconditions；
6. 验证通过后写入格式。

详细协议见 [INTEGRATION_CONTRACT_V1.md](INTEGRATION_CONTRACT_V1.md)，宿主伪代码见
[HOST_ADAPTER_GUIDE.md](HOST_ADAPTER_GUIDE.md)。

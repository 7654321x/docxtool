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
- `source_locator_status`、证据和警告；
- raw/canonical 片段及前后上下文的哈希。

`source_locator_status` 为 `confirmed` 时，raw 片段能够从原始物理段落
范围读回；`review` 或 `unresolved` 均不得被宿主自动修改。

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
应用格式。混合物理段落必须按所有 `segment_index` 联合验证；正式排版前如
仍无法拆分，应返回 `MIXED_PARAGRAPH_REQUIRES_SPLIT`。

## 命令行

```pwsh
docxtool-recognize input.docx --mode structural --output recognition-plan.json
```

`--config format.json` 可传入格式配置文件。命令行输出同样不包含正文。
`--include-text` 与 `--include-raw-text` 均需显式开启；后者仅限本机调试。
使用 `--host-snapshot snapshot.json` 可在同一次调用中输出脱敏绑定结果。

## WPS 集成边界

SDK 只负责识别，不直接操作 WPS。未来 WPS 加载项应：

1. 保存或导出当前文档的临时 DOCX 快照；
2. 调用本机 SDK 获取 `RecognitionPlan`；
3. 校验段落锚点未变化；
4. 使用 WPS API 将类型和格式角色写回当前打开的文档。

这样不会通过云端上传文档，也不需要让最终用户自行管理 Python wheel。

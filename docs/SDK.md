# 本地识别 SDK

`docxtool.sdk` 是面向本机集成的只读 DOCX 识别接口。它不启动 Web 服务、不建立用户会话、不写任务数据库，也不生成排版后的 DOCX。

SDK 的设计用途是让 WPS、Word 加载项或其他本地软件先取得文档结构判断，再由宿主软件调用自身 API 修改当前打开的文档。

## 安装

```pwsh
python -m build
pip install dist/docxtool-1.3-py3-none-any.whl
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
- 原文、前邻、后邻的 SHA-256 短哈希；
- 需要人工复核的脱敏依据。

计划默认不含正文文字、原始路径、Cookie、密钥、日志或数据库信息。宿主程序应保留当前文档，并在应用格式前验证块序号和哈希锚点。

## 命令行

```pwsh
docxtool-recognize input.docx --mode structural --output recognition-plan.json
```

`--config format.json` 可传入格式配置文件。命令行输出同样不包含正文。

## WPS 集成边界

SDK 只负责识别，不直接操作 WPS。未来 WPS 加载项应：

1. 保存或导出当前文档的临时 DOCX 快照；
2. 调用本机 SDK 获取 `RecognitionPlan`；
3. 校验段落锚点未变化；
4. 使用 WPS API 将类型和格式角色写回当前打开的文档。

这样不会通过云端上传文档，也不需要让最终用户自行管理 Python wheel。

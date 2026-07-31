# WPS 用户验收

本次验收由 WPS 桌面版用户执行。文档内容为脱敏测试材料；请不要用真实文件替代。

## 当前验收构建

- wheel：`docxtool 1.8`
- classified-offline build ID：`20260731071239-bfadf7f2905b`
- classified-offline asset hash：`bfadf7f2905b5a214fe0c6388679e4f36a3de4a40f59066bc01bcf39984f8052`
- `host-runtime.js` SHA-256：`AD3C93BEBB2568E66DDE8121D5280EC7F39AF7729561C735CC793E40D00F7B97`

build ID 或 asset hash 不一致时，不要继续本轮验收；先重新加载当前 `classified-offline/dist` 加载项。

## 准备

1. 加载 WPS 涉密离线插件构建目录中的加载项，并确认顶部显示 `预览排版`、`一键排版`、`功能检测` 三个按钮。
2. 打开 `test_docx/wps_validation` 中对应的验收 DOCX。
3. 先点击 `功能检测`。预期：本地识别 wheel、来源定位和 `host-text-v1` 显示为通过；缺少字体可以显示警告，不应修改文档、批注或选区。

## 验收步骤

以下批注数量由 wheel `1.8` 对当前脱敏 fixture 的公开识别与 host binding 链路计算得出。数量只用于验收当前 build；若加载了其他 build 或 wheel，先停止验收并记录版本差异。

| 文件 | 预览批注数与锚点 | 点击一键排版后应看到 |
| --- | --- | --- |
| `01-basic-heading-body.docx` | 3 条：第 1 段文首说明、第 2 段一级标题、第 3 段正文 | 3 个已确认的独立段落改变格式；再次按一次撤销应恢复格式 |
| `02-inline-mixed-segments.docx` | 2 条：同一物理段落中的标题子范围、正文子范围；两条均显示“需要复核” | 不得修改该物理段落的任何部分 |
| `03-duplicate-paragraphs.docx` | 5 条：5 个物理段落各 1 条；两个重复段落必须分别锚定其原位置 | 5 个 binding 已确认的独立段落允许改格式，批注不得跳到另一处重复段落 |
| `04-soft-break-and-spaces.docx` | 2 条：软换行前的标题子范围、软换行后的正文子范围；范围不得截断 Tab、空格或 Emoji | 混合物理段落必须跳过，不得整段改格式 |
| `05-eastasia-style-inheritance.docx` | 1 条：唯一正文段 | 已确认时仅修改目标格式，不改文字；功能检测不复制字体文件 |
| `06-user-comment-protection.docx` | 2 条：第 1 段正文和第 2 段一级标题；另有 1 条用户原有批注必须保留 | 清理 DocxTool 预览和一键排版后，用户原有批注仍存在 |
| `07-review-and-unresolved.docx` | 4 条：4 个独立物理段落各 1 条；两处重复文字应由前后上下文分别定位 | 已确认的独立段落允许改格式；不允许用“首次匹配”定位重复文字 |
| `08-section-page-format.docx` | 3 条：文首说明、纵向节正文、横向节正文；另有 1 个空物理段落只在摘要中跳过，不插入批注 | 预览不修改页面设置；已确认的页面设置读回通过，横向节保持横向 |

预览批注数只统计 DocxTool 本次创建的批注，不计第 6 份文件中用户原有批注。`unresolved`、空段和没有安全唯一 Range 的内容不得插入批注；它们只能出现在结果摘要中。

## 每份文件的固定检查

1. 点击 `预览排版`，确认批注只锚定对应文字，不移动光标，也不改变正文格式。
2. 确认 `review` 批注明确写明“需要复核”；没有安全位置的 `unresolved` 只出现在结果摘要中。
3. 点击 `一键排版`。只有 `source locator=confirmed`、`binding=confirmed` 且片段组完整的独立段落可以改格式。
4. 确认标题、正文、用户批注、正文文字和段落顺序没有被意外删除。
5. 立即执行一次 WPS 撤销，确认本次格式写入整体恢复。
6. 保存为验收副本，记录截图编号和实际错误码到 `USER_WPS_VALIDATION_RESULT.md`。

出现问题时，只记录插件 build ID、wheel 版本、稳定错误码、验收文件编号和截图编号。不要上传文档正文、完整路径、Cookie、令牌或日志正文。

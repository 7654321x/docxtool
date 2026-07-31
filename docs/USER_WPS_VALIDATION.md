# WPS 用户验收

本次验收由 WPS 桌面版用户执行。文档内容为脱敏测试材料；请不要用真实文件替代。

## 准备

1. 加载 WPS 涉密离线插件构建目录中的加载项，并确认顶部显示 `预览排版`、`一键排版`、`功能检测` 三个按钮。
2. 打开 `test_docx/wps_validation` 中对应的验收 DOCX。
3. 先点击 `功能检测`。预期：本地识别 wheel、来源定位和 `host-text-v1` 显示为通过；缺少字体可以显示警告，不应修改文档、批注或选区。

## 验收步骤

| 文件 | 点击预览后应看到 | 点击一键排版后应看到 |
| --- | --- | --- |
| `01-basic-heading-body.docx` | 标题和一级标题、正文各有对应预览批注 | 已确认的独立段落改变格式；再次按一次撤销应恢复格式 |
| `02-inline-mixed-segments.docx` | 同一物理段落的标题和正文分别有批注，并标记需要复核 | 不得修改该物理段落的任何部分 |
| `03-duplicate-paragraphs.docx` | 两个重复段落应按前后上下文分别定位，批注不跳到错误段落 | 只有 binding 已确认的独立段落允许改格式 |
| `04-soft-break-and-spaces.docx` | 软换行、Tab、空格和 Emoji 的批注范围不得截断或漂移 | 未确认的混合段落应跳过 |
| `05-eastasia-style-inheritance.docx` | 批注可显示识别类型；功能检测不复制字体文件 | 已确认时仅修改目标格式，不改文字 |
| `06-user-comment-protection.docx` | 用户原有批注仍存在；DocxTool 只新增自身预览批注 | 清理预览后用户原有批注仍存在 |
| `07-review-and-unresolved.docx` | 可安全定位的 review 可显示“需要复核”；无法定位内容不插入任意位置 | review 和 unresolved 均跳过，不能猜测位置 |
| `08-section-page-format.docx` | 预览不修改页面设置 | 已确认的页面设置读回通过；横向节保持横向 |

## 每份文件的固定检查

1. 点击 `预览排版`，确认批注只锚定对应文字，不移动光标，也不改变正文格式。
2. 确认 `review` 批注明确写明“需要复核”；没有安全位置的 `unresolved` 只出现在结果摘要中。
3. 点击 `一键排版`。只有 `source locator=confirmed`、`binding=confirmed` 且片段组完整的独立段落可以改格式。
4. 确认标题、正文、用户批注、正文文字和段落顺序没有被意外删除。
5. 立即执行一次 WPS 撤销，确认本次格式写入整体恢复。
6. 保存为验收副本，记录截图编号和实际错误码到 `USER_WPS_VALIDATION_RESULT.md`。

出现问题时，只记录插件 build ID、wheel 版本、稳定错误码、验收文件编号和截图编号。不要上传文档正文、完整路径、Cookie、令牌或日志正文。

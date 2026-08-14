# WPS 内置快捷样式映射技术设计

## 1. 文档信息

- 适用版本：DocxTool 5.4。
- 适用范围：WPS 插件“一键排版”生成的当前 DOCX。
- 唯一职责：定义 WPS 一键排版如何让正文和一至四级标题使用 WPS 内置快捷样式，同时保持其他导出入口和特殊公文样式不变。
- 上位规则：仓库根 `AGENTS.md`、`apps/wps/AGENTS.md`、`docs/ARCHITECTURE.md`。
- 验证入口：Engine 样式测试、WPS 事务测试、DOCX OOXML 检查和真实 WPS 样式库截图。

## 2. 背景与现状

Engine 当前新建输出 `Document()`，在输出包中保留 python-docx 模板自带的
`Normal`、`Heading1` 至 `Heading4`，同时创建 `DCT-Body`、
`DCT-Heading1` 至 `DCT-Heading4`。正式排版段落实际引用 DCT 样式，因此
WPS 顶部虽然仍能显示“正文、标题1、标题2、标题3、标题4”，选中排版后的
段落时却不一定把对应内置按钮识别为当前样式。

`Normal`、`Heading1` 等是 OOXML 内部样式 ID，不是要求展示给用户的英文文案。
中文 WPS 应继续把这些内置 ID 本地化显示为“正文、标题1～4”。本设计禁止新增
`Docxtool Heading 1` 等快捷样式按钮，也禁止把顶部五个按钮改成英文。

## 3. 目标与非目标

### 3.1 目标

1. WPS 一键排版后的普通正文使用 `Normal`。
2. 一至四级标题分别使用 `Heading1`、`Heading2`、`Heading3`、`Heading4`。
3. 选中排版后的段落时，中文 WPS 顶部显示对应的“正文”或“标题1～4”。
4. 网页、SDK、CLI、批处理等既有 Engine 调用继续使用 DCT 样式。
5. 版头、主标题、发文字号、落款、附件和其他特殊结构继续使用 DCT 样式。
6. 排版成功后结果永久保留；取消、失败或事务回滚时恢复原文档。

### 3.2 非目标

- 不修改 WPS 全局模板、注册表、用户默认样式或其他已打开文档。
- 不在插件退出、任务窗格关闭或 WPS 退出时恢复成功排版结果。
- 不修改 Recognition、Normalization、SDK Schema、HTTP 协议、服务端数据库或 Token。
- 不改变文字、编号、段落顺序、定位范围、表格、图片、题注和关系部件。
- 不生成 EXE，不在本任务中提交或推送。

## 4. 设计方案

### 4.1 显式样式 Profile

Engine 增加两个固定内部 profile：

- `docxtool`：默认值，保持当前 DCT 样式行为。
- `wps_builtin`：仅由 WPS 一键排版显式启用。

公开 Python 导出入口增加向后兼容的关键字参数：

```python
export_doc(..., style_profile="docxtool")
```

该值沿 `export_pipeline -> RenderContext -> paragraph renderer -> finalize` 单向传递。
所有段落样式 ID 必须由同一个 `style_id_for_type(type_id, style_profile)` 解析，
标题正文拆分和最终 fallback 不得再硬编码 `DCT-Body`。

无法识别的 profile 使用稳定错误码 `WPS_STYLE_PROFILE_INVALID` 终止当前导出，
不得静默回退到另一套样式。

### 4.2 样式映射

| 最终段落类型 | `docxtool` | `wps_builtin` |
| --- | --- | --- |
| `body`、`meeting_meta`、未知类型 fallback | `DCT-Body` | `Normal` |
| `heading1`、`heading1_report` | `DCT-Heading1` | `Heading1` |
| `heading2`、`title2` | `DCT-Heading2` | `Heading2` |
| `heading3` | `DCT-Heading3` | `Heading3` |
| `heading4` | `DCT-Heading4` | `Heading4` |

其他类型沿用现有 DCT 映射。Recognition 的兼容 `STYLE_ID_MAP` 不参与本次
渲染 profile 选择，不作修改。

### 4.3 内置样式定义

`wps_builtin` 不创建第二套快捷按钮，而是更新输出 DOCX 已有的五个内置样式：

- `Normal` 使用正文 StyleRule（索引 5）。
- `Heading1` 至 `Heading4` 使用标题 StyleRule（索引 1 至 4）。
- 字体、字号、粗体写入 `w:rPr`。
- 对齐、缩进、固定行距、段前段后和大纲级别写入 `w:pPr`。
- 标题继续遵守项目现有“不强制 keepNext/keepLines”的规则。

更新时必须保留内置样式的身份与快捷样式元数据，包括：

- `w:styleId`、`w:name`、默认样式标记；
- `w:qFormat`、`w:uiPriority`；
- `w:basedOn`、`w:next`、`w:link`；
- `w:unhideWhenUsed`、`w:semiHidden` 等既有宿主元数据。

如果当前输出模板缺少任一必需内置样式，使用
`WPS_BUILTIN_STYLE_MISSING` 中止导出，不创建同名猜测样式。

页面设置阶段当前会修改 `Normal`。实现时必须让该阶段感知 profile，确保
`wps_builtin` 已按正文 StyleRule 写入的 `Normal` 不再被固定值覆盖；
文档网格、页边距和当前 16 pt 基准计算保持原有语义。

### 4.4 渲染和不变量

- 普通渲染段落使用 profile 解析后的唯一 `w:pStyle`。
- 一级标题拆出的正文使用当前 profile 的正文样式；末尾完整性校验使用同一预期 ID。
- 最终正文不变量检查把当前 profile 的五个样式视为受管样式；未知段落 fallback
  使用当前 profile 的正文样式。
- 直接 run 格式继续写入，保证输出视觉效果与当前 StyleRule 一致。
- 受保护表格、图片、题注、已有版头和范围外段落不参与样式重映射。
- 范围排版只给选中范围内新渲染的正文/标题使用内置样式，范围外源 XML 原样透传。

### 4.5 WPS 接入与生命周期

`apps/wps/control/format_current_document.py` 调用 Engine 时固定传入：

```python
style_profile="wps_builtin"
```

预览、识别、版头检查和阅读模式不改变样式 profile。现有文档事务仍负责：

```text
临时输出 -> 完整性校验 -> WPS 关闭源文档 -> 原子替换 -> 重新打开确认
```

- 成功并 finalize：删除备份，保留格式化文档。
- 取消、失败或 reopen 失败：按现有事务恢复原文档。
- 插件退出：不读取或恢复样式，不修改任何 WPS 全局状态。

日志只增加 `style_profile=wps_builtin` 这一非敏感诊断，不记录正文、路径、账号或 Token。

## 5. 接口与兼容性

- Python `export_doc()` 新增可选关键字参数；既有调用无需修改。
- HTTP、SDK、WPS Control 请求体和响应结构不变。
- `docxtool` profile 的输出及既有 DCT 测试基线必须保持不变。
- WPS 一键排版输出的正文/标题 `style_id` 是预期的兼容性变化。
- 特殊 DCT 样式 ID、原生编号和源样式隔离复制规则不变。

## 6. 测试与验收

### 6.1 自动测试

1. Profile 解析：默认和 `docxtool` 返回现有 DCT ID；`wps_builtin` 返回五个内置 ID；非法值失败。
2. OOXML：五个内置样式保留快捷样式元数据，并包含当前 StyleRule 的 `w:pPr/w:rPr`。
3. 渲染：正文和一至四级标题只引用一套内置样式；特殊段落继续引用 DCT。
4. 标题正文拆分：拆出的正文为 `Normal`，文字和相邻关系校验不变。
5. 范围排版：选中范围使用内置样式，范围外和受保护对象保持源样式。
6. 默认回归：未传 profile 的 Web、SDK、CLI 和批处理输出仍使用 DCT。
7. 事务：成功保留格式化结果；取消、失败和 reopen 失败恢复原文件；插件退出无额外恢复动作。

### 6.2 真实 WPS 验收

用脱敏样本文档执行一次一键排版并重新打开：

1. 选中正文，顶部显示“正文”。
2. 选中一至四级标题，分别显示“标题1”至“标题4”。
3. 顶部五个按钮没有显示 `Normal`、`Heading 1` 或 `Docxtool Heading 1`。
4. 打开另一份未排版文档，其样式库未被 DocxTool 改变。
5. 退出插件后，已成功排版的文档保持不变。

未在真实宿主执行时必须报告：

```text
WPS_STYLE_GALLERY_SMOKE = NOT_RUN
```

### 6.3 门禁

```pwsh
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m pytest -q tests/test_engine_paragraph_styles.py tests/test_structural_styles.py tests/test_structured_layout_quality.py tests/test_engine_heading_body_split.py tests/test_engine_heading_spacing.py tests/test_processing_flags.py"
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m pytest -q apps/wps/tests/test_wps_app.py apps/wps/tests/test_host_bridge.py"
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m ruff check src tests apps/wps"
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m compileall -q src/docxtool apps/wps"
pwsh -NoProfile -Command "git diff --check"
```

## 7. 实施顺序

1. 增加 profile 常量、验证和统一样式 ID 解析。
2. 将 profile 贯穿导出上下文、渲染、拆分和最终不变量。
3. 为 WPS profile 写入五个内置样式定义并处理 `Normal` 覆盖顺序。
4. WPS 一键排版显式启用 `wps_builtin`。
5. 补齐自动测试、文档回归规则和真实 WPS 验收记录。

任何阶段发现默认 `docxtool` 输出出现未解释差异，应停止实施并先定位差异，
不得通过修改快照或放宽断言继续推进。

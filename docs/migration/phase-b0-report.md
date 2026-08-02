# Phase B-0 功能基线与边界修复报告

## Looper 状态

状态：`completed`。B0-1 至 B0-5 均完成；未触发无法解释差异、文字守恒失败、
Schema 破坏性变化或连续 blocked。固定输入、配置、版本、输出和报告哈希见
`phase-b0-manifest.json`。

| Finding | 状态 | 结论 |
|---|---|---|
| B0-1 2.6 → 2.7 功能差异 | fixed | 源范围对齐后只有四组预期差异，非预期差异为 0 |
| B0-2 文首角色/姓名宽匹配 | fixed | 角色词必须与姓名 suffix 相邻，并由标题、日期或称呼结构锚点支持 |
| B0-3 数字冒号与冒号加粗 | fixed | 识别和渲染共享最早有效语义冒号位置 |
| B0-4 SDK 部分 locator 排序 | fixed | 已定位范围始终按源顺序；未定位片段不污染有效 locator |
| B0-5 60 项 P1 聚类 | already_fixed | 一次附件分页状态回退被旧比较器放大为 60 条；当前 50 篇报告 P1 为 0 |

## 2.6 到 2.7

直接按数组下标比较得到 8128 个路径差异；按物理段和 source span 对齐后，
语义差异只剩以下四组：

| 分组 | 样本和模式 | 2.6 | 2.7 / 人工期望 |
|---|---|---|---|
| front-role-date | 专项讲话稿，structural/normalize | 职务姓名为标题续行，日期时间地点为正文 | `role_name`、`date_line` |
| attachment-pagination | 50 篇标准稿，structural/normalize | 一个附件页标记为 `attachment_body` | `attachment_page_mark` |
| same-line-signature-date | 标准稿 021–030，structural | 同行落款和日期留在正文范围 | 正文缩短并增加 `sign_org`、`sign_date` |
| sdk-source-order | 上述同物理段拆分结果 | locator 序号和状态受最终块顺序影响 | 源范围序号、可回读状态和计数一致 |

`strict` 模式无语义差异；package relationships 差异为 0；源范围对齐后的
unexpected 差异为 0。

## 角色姓名矩阵

正例均保持 `role_name`：普通空格、全角空格、2/3/4 字姓名、多个角色组合、
紧凑角色姓名、后接日期、后接称呼、仅前接主标题锚点。角色和姓名均使用脱敏
占位，未维护姓名或单位名单。

反例均保持标题或正文：角色词出现在履职报告、工作方案、年度总结、调研报告中；
角色词出现在正文描述中；错误 Legacy `role_name` 但全文结构明确为标题。

## 冒号矩阵

| 输入形态 | 语义位置 | 结果 |
|---|---:|---|
| `11:00`、`1:2` | 无 | 不生成标签候选，不加粗 |
| `时间：11:00` | 第一个中文冒号 | 键值结构，标签加粗 |
| `标签:内容` | 英文冒号 | 现有键值/正文条件不变 |
| 数字冒号后再有语义冒号 | 后一个冒号 | 跳过数字冒号 |
| 中英文冒号同时存在 | 最早有效位置 | 识别与渲染一致 |
| 外层引号包裹 | 保留原 offset | 标签范围不偏移 |

## SDK Locator

- `block_index` 保持最终文档顺序。
- 已定位片段按 `(raw_start, raw_end, stable_index)` 计算 `segment_index`。
- 未定位片段排在已定位片段之后，并保持自身 `block_index` 相对顺序。
- “后段、未定位、前段”的 segment 序号为 `[1, 2, 0]`。
- “前段、未定位、后段”的 segment 序号为 `[0, 2, 1]`。
- 两个未定位片段的案例为 `[1, 2, 0, 3]`，有效 locator 均保持 confirmed。
- 真实 overlap 只降级冲突的已定位范围；未定位片段不参与 overlap 扫描。
- 全定位尾部重排、UTF-16 surrogate pair、同行落款日期、Plan/Binding JSON
  round-trip 和 confirmed binding 均通过。

## 60 项 P1 聚类

021–030 每篇均有同一物理段 44、同一组 source span 和同样六条 P1，总计 60。

| 根因 cluster | 条数 | 范围摘要 | 最早阶段 | 产品判断 |
|---|---:|---|---|---|
| recognition type | 20 | 第三附件页标记 raw span `761..764` | 2.6 尾部附件状态转换 | 真实共享问题，2.7/current 已修复 |
| output added / missing | 20 | 同一 `8f42...` 哈希同时被记新增和缺失 | 模板保序对齐 | 比较归因级联，不是真实增删 |
| text loss / duplication | 20 | 同一 `ad5a...` 哈希同时被记新增和丢失 | source-preservation 对齐 | 比较归因级联，文字实际守恒 |
| normalization reorder | 0 | 无 | 无 | 无 |
| template expectation | 0 独立项 | 旧报告把错位后的期望类型记为 attachment title | 比较归因 | 不应作为独立产品修复 |
| other | 0 | 无 | 无 | 无 |

版本行为：2.2 将该范围识别为 `attachment_page_mark`；2.6 回退为
`attachment_body`；2.7 恢复 `attachment_page_mark`。正确模板使用附件页标记样式，
人工真值明确。旧报告中的 60 条可由一个共享状态修复解决，不能逐样本加补丁。
`attachment-pagination-fix-20260802-2245` 和本轮当前批次均为 P1=0。

## 修改文件

本轮行为修改：

- `src/docxtool/document/role_shape.py`
- `src/docxtool/document/recognition/context/front.py`
- `src/docxtool/document/recognition/colon.py`
- `src/docxtool/document/engine/inline_effects.py`
- `src/docxtool/sdk/recognition.py`

本轮测试和契约说明：

- `tests/test_recognition_decoder.py`
- `tests/test_colon_structure.py`
- `tests/test_engine_inline_effects.py`
- `tests/test_sdk_binding.py`
- `AGENTS.md`
- `docs/DOCX_REGRESSION_CHECKLIST.md`
- `docs/RECOGNITION_SOURCE_LOCATORS.md`
- `docs/SDK.md`
- `docs/migration/phase-b0-manifest.json`
- `docs/migration/phase-b0-report.md`

这些文件中的 Phase A 拆分及其他开始前改动仍属于既有 dirty worktree；本轮只增加
上述边界修复、测试和说明，没有恢复或覆盖开始前修改。

## 验证结果

- 直接相关模块：142 tests passed。
- 全量 Python：1164 tests passed，3 个已知 warning。
- Ruff：`src tests scripts` 全部通过。
- `compileall`：通过。
- Node：11 tests passed。
- `git diff --check`：通过，仅有既有 LF/CRLF 提示。
- 标准稿：50/50 成功，P0/P1/P2/P3 均为 0，源标题线索未保留 0，落款连续性 0。
- 专项稿：5/5 成功，结构复核和关键结构复核均为 0。
- wheel-only：Python 3.8 干净环境通过 SDK 导入、Schema、CLI、最小识别、
  Plan/Binding JSON 往返和 confirmed 绑定。
- wheel：`docxtool-2.7-py3-none-any.whl`，SHA-256
  `01093c16860dfff199ccf0ab663ff8f4bfb549d7eac5c25204fc926f36a7aaf2`。

当前批次未请求视觉渲染，不能据此断言没有页面级空白、裁切或 WPS 显示差异。

本轮未继续拆分文件。
本轮未加入具体姓名、单位或样本白名单。
本轮未执行 git commit。
本轮未执行 git push。

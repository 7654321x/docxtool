# Phase B-0 / B-0.1 / B-0.2 功能基线与收口报告

## Looper 状态

状态：`completed`。正式 2.9 clean wheel、四字姓名边界、带前缀数字冒号、
三模式差异分类和受影响页面抽查均已收口。

| Finding | 状态 | 结论 |
|---|---|---|
| F-001 发布制品证据 | fixed | 已从正式 2.8 commit/tree 构建并验证 wheel；当前未提交目标 wheel 另行标记，不冒充 clean release |
| F-002 公开 fixture 元数据 | fixed | 公开 manifest 和报告只保留匿名 ID、数量和聚合哈希，发布扫描为 0 finding |
| F-003 角色姓名邻接 | fixed | 角色表达必须在姓名边界结束，并由文首结构锚点支持 |
| F-004 空白数字冒号 | fixed | 检查冒号两侧最近非空白字符，原文 offset 和真实标签范围均保留 |
| F-005 正式 2.9 制品绑定 | fixed | clean commit、tree 和 wheel 已形成正式 2.9 manifest 节点 |
| F-006 四字姓名边界 | fixed | 普通四字后缀使用更强上下文，紧凑写法优先强姓名切分 |
| F-007 带前缀数字冒号 | fixed | 统一输出真实 label start/end，前置数字表达不加粗 |
| F-008 模式差异严重度 | fixed | strict 400、normalize 550 保留记录并按字符守恒归为预期模式差异 |

## 公开元数据

- 公开 fixture 使用 `standard-001`至`standard-050`及 5 个结构类别匿名 ID。
- 公开文件不包含源文件名、测试目录、源文档哈希、绝对路径或正文。
- 私有映射仅保留在 Git 忽略的本地回收站中，发布脚本不会上传。
- 发布扫描已覆盖 DOCX 名、私有测试路径、Windows/POSIX 绝对路径、源哈希和业务化 fixture 名称。

## Git 历史说明

当前分支内容已清理；旧提交历史仍包含已发布元数据；本轮未擅自重写 Git 历史。

## Wheel 制品

| 制品 | 版本 | SHA-256 | 证据 |
|---|---:|---|---|
| 正式 release wheel | 2.8 | `0def6d8382e4f58ca1451d4ff8798262ee958ede00677a93db50921b53be83f0` | commit `63908cf137bf779c59e8b37581e222b2ad7d5922`，tree `9232389d1329b0a44aefa0321ff48dbc5626af82` |
| 正式 release wheel | 2.9 | `a8a1c779110075de0a226782e929f892fe58254af231d6e85e40252f930abea6` | commit `597138dd3e6b75b2abde839d7b99dff144b61e9e`，tree `d45080bf5c9db6b6e7480f894970f08cfb0bead8` |
| B-0.2 工作树验证 wheel | 2.9 | `1ff4dd9589a40a6882eed3997ba4037b24883ed3d303a2392c5598db042fb87f` | 仅用于未提交改动的隔离测试，不是正式发布制品 |

正式 2.9 wheel 与旧目标 wheel 的 225 个成员、METADATA、RECORD 和逐文件内容
SHA 完全相同；整包 SHA 不同仅因 225 个 ZIP 成员时间戳不同，无新增、删除或代码差异。

## B-0.2 四字姓名边界

| 形状与上下文 | 结果 |
|---|---|
| 2/3 字、复姓四字、间隔点、占位符；前标题或后元数据 | 强姓名，可确认 `role_name` |
| 普通四字；前标题 + 后日期/称呼 + 居中 | 弱姓名，可确认 `role_name` |
| 普通四字；仅前标题、仅日期、仅称呼、仅居中或仅标题样式 | 非 `role_name` |
| 紧凑“多职务 + 二字姓名” | 优先二字强姓名切分，不被更长弱后缀截断 |

反例矩阵覆盖 4 种通用“角色表达 + 四字业务短语”形状与 6 种上下文组合，
共 24 项均未进入 `role_name`；未加入具体姓名、单位或业务短语黑名单。

## B-0.2 冒号范围

| 输入形状 | label range |
|---|---:|
| `时间11:00 标签：内容` | `(8, 10)` |
| `版本1:2 标签：内容` | `(6, 8)` |
| `会议时间 11 : 00 标签：内容` | `(13, 15)` |
| `序号1：2 标签：内容` | `(6, 8)` |
| `时间：11:00` | `(0, 2)` |
| `1 : 2 标签：内容` | `(6, 8)` |

Recognition 与 Engine 共用 `separator_index/label_start_index/label_end_index`；
渲染后的 run 检查和 PNG 人工查看均确认仅真实标签及语义冒号加粗。

## B-0.2 模式差异

| 模式 | 原始差异 | 预期模式差异 | 真实 P1/P2 |
|---|---:|---:|---:|
| strict | 400 项 alignment | 400 | 0 |
| normalize | 250 source_text_addition + 250 source_text_loss + 50 output_addition | 550 | 0 |

strict 差异全部来自未拆分“二级标题句 + 同段正文”的整段左对齐；normalize
差异来自结构拆分、标题句号、日期数字化和附件编号空格。全部 50 篇逐篇重算，
仅在规范化后字符守恒时分类；真实字符丢失测试仍保持 P1。专项 5 篇全部生成成功，
normalize 复核 0；strict 保留 14 项结构复核、2 项标题线索差异，但 critical review、
落款连续性和 DOCX 失败均为 0。

## B-0.2 验证

- Python 3.8：1246 passed；Python 3.10：1246 passed；各 3 条既有 warning。
- Node：10 passed；Ruff、compileall、`git diff --check`通过。
- 当前工作树 wheel-only：8 个 Schema、CLI、Plan/Binding 往返、confirmed binding、
  partial locator `[1, 2, 0, 3]`、8 个角色和 6 个冒号用例通过。
- 三模式均为标准 50/50、专项 5/5，失败 0；structural P0-P3 全零。
- 脱敏角色与冒号合成稿各渲染 1 页，疑似页 0，人工视觉检查通过。

## B-0.1 Wheel-only 验证（历史）

在仓库外 Python 3.8 干净环境中只安装 wheel 及其声明依赖，源码目录未进入
`PYTHONPATH`。以下全部通过：

- B-0.1 目标包元数据版本、`package_version()` 和 SDK manifest 均为 `2.9`；
- 8 个 Schema 资源可读，`docxtool-sdk --help` 和 `manifest` 通过；
- 最小 RecognitionPlan、Plan JSON 往返、RecognitionBinding 和 Binding JSON 往返通过；
- 部分 locator 顺序为 `[1, 2, 0, 3]`，`block_index` 保持最终文档顺序；
- 5 类角色姓名正例、4 类反例、5 类空白数字冒号和 4 类语义冒号通过；
- 前置比例后的标签范围为 `(6, 8)`，仅标签及冒号加粗。

## B-0.1 角色姓名矩阵（历史）

| 类别 | 结果 |
|---|---|
| 普通/全角空格 | `role_name` |
| 2、3、4 字姓名，复姓和间隔点 | `role_name` |
| 多角色、组织限定语、紧凑角色姓名 | `role_name` |
| 前接主标题、后接日期或称呼 | `role_name` |
| 角色词后仍有履职、制度、工作或调研结构 | 标题/正文，非 `role_name` |
| 仅 Word 标题样式或居中 | 不足以成为 `role_name` |

## B-0.1 冒号矩阵（历史）

| 输入形态 | 结果 |
|---|---|
| 数字冒号无空白 | 非语义分隔，不加粗 |
| 普通空格、Tab、NBSP、全角空格包围数字冒号 | 非语义分隔，不加粗 |
| 标签冒号后接数字时间/比例 | 使用第一个语义冒号 |
| 数字冒号后再出现语义冒号 | 跳过数字冒号，保留后一冒号原始 offset |
| 前置数字表达后接标签 | 前置表达不加粗，仅真实标签范围加粗 |
| 外层引号 | 返回相对原文的 offset，不压缩文本 |

## B-0.1 三模式原始统计（重分类前）

| 模式 | 标准/专项 | P0 | P1 | P2 | P3 | 标题线索未保留 | 落款连续性 | 缺失关系目标 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| strict | 50/50，5/5 | 0 | 0 | 400 | 0 | 0 / 2 | 0 | 0 |
| structural | 50/50，5/5 | 0 | 0 | 0 | 0 | 0 / 0 | 0 | 0 |
| normalize | 50/50，5/5 | 0 | 550 | 0 | 0 | 0 / 0 | 0 | 0 |

`strict` 的 400 项是源对齐与规范模板的左对齐/两端对齐差异；`normalize`
的 550 项是比较器将主动文字规范化仍按 source-preservation 记为新增/丢失。
用正式 Release 2.8 和同一固定输入复跑后，三模式的计数与归因完全相同，
因此两组不是 B-0.1 新回归。`structural` 仍为 P0–P3 全零。

三模式各 55 个输出包的 ZIP 完整性、关系 XML 解析和内部目标存在性均通过。
输出聚合 SHA 和两份报告 SHA 见公开 manifest。

## B-0.1 视觉抽查（历史）

- LibreOffice + PyMuPDF 成功渲染 10 个标准匿名样本、5 个专项匿名样本和
  1 个模板，共 239 页；转换失败 0，自动疑似页 0。
- 人工查看了角色/日期文首、时间冒号、附件起页、同行落款日期和稀疏签名页，
  未见文首类型错位、页面裁切、文字重叠或异常空白。
- 额外渲染 1 页脱敏合成空白数字冒号样例：数字比例保持普通字重，
  时间标签和比例后语义标签的加粗范围正确。该页因为仅有 30 个可见字符
  被阈值标记为稀疏页，人工复核为预期测试布局。

## B-0.1 修改文件（历史）

本轮直接修改：

- `src/docxtool/document/role_shape.py`
- `src/docxtool/document/recognition/context/front.py`
- `src/docxtool/document/recognition/colon.py`
- `src/docxtool/document/engine/inline_effects.py`
- `tests/test_recognition_decoder.py`
- `tests/test_colon_structure.py`
- `tests/test_engine_inline_effects.py`
- `scripts/check_public_metadata.py`
- `tests/test_public_metadata_scan.py`
- `scripts/publish_to_github.ps1`
- `.gitignore`
- `AGENTS.md`
- `docs/DOCX_REGRESSION_CHECKLIST.md`
- `docs/GITHUB_UPLOAD_GUIDE.md`
- `docs/UPLOAD_MANIFEST.md`
- `docs/migration/phase-b0-manifest.json`
- `docs/migration/phase-b0-report.md`

`src/docxtool/sdk/recognition.py` 等 Phase B-0 与 Phase A 文件在开始前已处于 dirty/untracked
状态，本轮未恢复、删除或覆盖这些既有修改。

## B-0.1 验证结果（历史）

- Python 3.8：`1206 passed, 3 warnings`。
- Python 3.10：`1206 passed, 3 warnings`。
- 直接冒号/渲染测试：26 passed。
- 角色姓名、解码、软换行和处理策略相关测试：通过。
- Ruff：`src tests scripts` 通过。
- `compileall`、`git diff --check`：通过；仅有既有 LF/CRLF 提示。
- Node：11 passed。
- 公开元数据扫描：0 finding。
- wheel-only SDK 与正式 2.8 wheel 元数据验证：通过。

本轮未继续拆分文件。
本轮未加入具体姓名、单位或样本白名单。
本轮未重写 Git 历史。
B-0.1 实现阶段未直接执行 git commit 或 git push；后续发布由独立安全脚本执行。

B-0.2 未执行 git commit 或 git push；正式 2.9 制品绑定和当前工作树验证制品已明确分开。

# Phase B-0 / B-0.1 功能基线与收口报告

## Looper 状态

状态：`completed`。公开元数据、正式 2.8 制品证据、角色姓名邻接、
空白数字冒号、三模式回归和受影响页面抽查均已收口。

| Finding | 状态 | 结论 |
|---|---|---|
| F-001 发布制品证据 | fixed | 已从正式 2.8 commit/tree 构建并验证 wheel；当前未提交目标 wheel 另行标记，不冒充 clean release |
| F-002 公开 fixture 元数据 | fixed | 公开 manifest 和报告只保留匿名 ID、数量和聚合哈希，发布扫描为 0 finding |
| F-003 角色姓名邻接 | fixed | 角色表达必须在姓名边界结束，并由文首结构锚点支持 |
| F-004 空白数字冒号 | fixed | 检查冒号两侧最近非空白字符，原文 offset 和真实标签范围均保留 |

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
| 当前目标 wheel | 2.9 | `0b969548123231c7168ef06209ea499a96545da3767b55c367deaf9ea2949545` | 未提交目标树聚合 SHA `f44ae8affafe7486e668953c3f1281b8684a76fb95dabf339db9d96c8c180335` |

正式 2.8 wheel 用于证明 Release 2.8 的 clean commit/tree；当前 2.9 wheel
用于验证 B-0.1 修复和新版本一致性。

## Wheel-only 验证

在仓库外 Python 3.8 干净环境中只安装 wheel 及其声明依赖，源码目录未进入
`PYTHONPATH`。以下全部通过：

- 当前目标包元数据版本、`package_version()` 和 SDK manifest 均为 `2.9`；
- 8 个 Schema 资源可读，`docxtool-sdk --help` 和 `manifest` 通过；
- 最小 RecognitionPlan、Plan JSON 往返、RecognitionBinding 和 Binding JSON 往返通过；
- 部分 locator 顺序为 `[1, 2, 0, 3]`，`block_index` 保持最终文档顺序；
- 5 类角色姓名正例、4 类反例、5 类空白数字冒号和 4 类语义冒号通过；
- 前置比例后的标签范围为 `(6, 8)`，仅标签及冒号加粗。

## 角色姓名矩阵

| 类别 | 结果 |
|---|---|
| 普通/全角空格 | `role_name` |
| 2、3、4 字姓名，复姓和间隔点 | `role_name` |
| 多角色、组织限定语、紧凑角色姓名 | `role_name` |
| 前接主标题、后接日期或称呼 | `role_name` |
| 角色词后仍有履职、制度、工作或调研结构 | 标题/正文，非 `role_name` |
| 仅 Word 标题样式或居中 | 不足以成为 `role_name` |

## 冒号矩阵

| 输入形态 | 结果 |
|---|---|
| 数字冒号无空白 | 非语义分隔，不加粗 |
| 普通空格、Tab、NBSP、全角空格包围数字冒号 | 非语义分隔，不加粗 |
| 标签冒号后接数字时间/比例 | 使用第一个语义冒号 |
| 数字冒号后再出现语义冒号 | 跳过数字冒号，保留后一冒号原始 offset |
| 前置数字表达后接标签 | 前置表达不加粗，仅真实标签范围加粗 |
| 外层引号 | 返回相对原文的 offset，不压缩文本 |

## 三模式 50+5

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

## 视觉抽查

- LibreOffice + PyMuPDF 成功渲染 10 个标准匿名样本、5 个专项匿名样本和
  1 个模板，共 239 页；转换失败 0，自动疑似页 0。
- 人工查看了角色/日期文首、时间冒号、附件起页、同行落款日期和稀疏签名页，
  未见文首类型错位、页面裁切、文字重叠或异常空白。
- 额外渲染 1 页脱敏合成空白数字冒号样例：数字比例保持普通字重，
  时间标签和比例后语义标签的加粗范围正确。该页因为仅有 30 个可见字符
  被阈值标记为稀疏页，人工复核为预期测试布局。

## 修改文件

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

## 验证结果

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

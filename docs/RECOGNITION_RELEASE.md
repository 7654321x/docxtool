# 识别发布候选说明

## 发布前

在仓库根目录执行：

```powershell
python --version
.\.venv\Scripts\python.exe -m pytest -rA --tb=short
.\.venv\Scripts\python.exe -m ruff check src tests scripts
node --test tests/worker-routing.test.mjs
node --test tests/frontend-format-config.test.mjs
.\.venv\Scripts\python.exe scripts/benchmark_recognition.py
```

基准脚本只输出 JSON，不创建 DOCX、日志或临时文件。对本地样本进行重复识别时使用：

```powershell
.\.venv\Scripts\python.exe scripts/compare_recognition_runs.py <docx-or-directory> --repeat 3 --fail-on-type-drift
```

差分结果只包含文件名、索引、哈希、长度、类型、板块、分数和差异类别，不包含正文或绝对路径。

## 发布门禁

以下任一项失败时停止发布：

- Python 全量测试、Ruff、Worker 或前端格式测试失败；
- 三次复跑出现类型漂移；
- 发文字号、会议元数据或附件/落款结构发生未审查变化；
- DOCX 完整性检查失败；
- 输出路径、文件名、表格、图片、页眉页脚或页面参数出现非预期变化。

差异工具退出码约定为：`0` 无阻塞差异，`1` 发现被选中的阻塞差异，`2` 输入或参数错误，`3` 识别执行失败。
支持的阻塞开关包括 `--fail-on-type-drift`、`--fail-on-section-drift`、
`--fail-on-mode-drift` 和 `--fail-on-layout-drift`。目录扫描按文件名排序并跳过 `~$` 临时文件。

当前仓库没有提交真实用户语料或黄金 DOCX 二进制；无敏感结构样本由专项测试在临时目录生成。
生产发布前仍需使用脱敏或仅哈希登记的内部样本执行同一套快照门禁。

## 回滚

回滚使用上一份已验证的发布包或上一版本部署目录，不在生产机执行 `git reset --hard`、`git clean` 或强制 checkout。

回滚后重新运行 `/health`、一次安全样本识别和下载完整性检查。保留失败样本的哈希、类型差异和诊断摘要，禁止上传原文。

## 版本

识别引擎版本和诊断 schema 版本分别由
`src/docxtool/document/recognition/version.py` 集中管理。升级诊断字段必须提高 schema 版本，
不得依赖 Git 提交号、绝对路径或机器信息。

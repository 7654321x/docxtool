# DocxTool Codex 工作流与测试体系优化技术设计

## 目标

减少重复阅读、重复规划、重复测试和重复发布确认，同时保持复杂任务的设计、回归和发布安全边界。

## 当前事实

- 根目录 Agent 同时包含通用规则和项目规则，存在重复上下文。
- 测试入口需要按改动范围选择，普通任务不应默认运行完整 WPS/EXE 门禁。
- WPS Node 测试已有统一入口方向；CI、WPS 验证脚本和发布清单必须使用同一入口。
- 当前工作树包含既有业务/API改动和测试优化改动，本设计不覆盖或回退既有业务改动。

## 任务分级

- S 级：单文件、样式、文字、简单测试或明确小修复。只使用短计划和聚焦检查，不新增技术设计文档。
- M 级：模块功能、WPS UI、Reader 或测试结构调整。先给出短设计；只有形成长期架构决策时才新增正式设计文档。
- L 级：识别、排版、账号、鉴权、协议、数据库、发布流程或架构边界。必须先写正式技术设计，明确接口、兼容性、失败边界和验收。

## 技能路由

不把所有领域技能合并为一个大文件。按任务触发最小技能集合：

- DOCX 识别、规范化和排版使用 DocxTool 专项技能；
- Codex 设置、技能和工作流问题使用 OpenAI 官方文档技能；
- 网页调研使用一个网络检索路由，避免同一问题重复搜索；
- GitHub 发布直接使用项目 Quick 发布流程；
- 复杂审阅、重构和方案评估才使用通用代码审阅准则。

## 验证策略

`verify_changed.ps1` 根据工作树、暂存区和未跟踪文件选择最小验证集，并输出 `SELECTED_CHECKS`、`SKIPPED_CHECKS` 和 `NOT_RUN`。它不生成 EXE，不修改源码，不替代完整 WPS 门禁。

- 文档/Agent：文档测试、链接检查和差异检查；
- Recognition/Importer/Segmentation/Normalization：识别和分段聚焦测试；
- Engine/编号/版头/页码：对应 Engine 和 DOCX 回归；
- WPS Python：WPS Python 聚焦测试；
- WPS HTML/CSS/JS/Reader：统一 Node 入口；
- 发布脚本、Manifest 和构建配置：发布 dry-run、架构测试和静态检查。

完整 WPS/EXE 验收只在用户明确要求或 `-Verify` 发布时执行。

## 测试结构

- 只删除已确认被新版覆盖的重复数据库/IP测试；
- 保持按生产模块组织的小测试文件；
- 已将 WPS Python 聚合测试拆分为事务、Control/格式、诊断和启动器四类；WPS Node 聚合测试已拆为 Host Runtime、TaskPane Runtime 和共享 harness，并由统一入口执行；Recognition Decoder 聚合测试已按基础解码、标题编号、版前角色三类拆分，共享稳定构造函数放入显式 `tests/support/`；
- 完全重复的稳定辅助函数进入显式 `tests/support/` 或 `apps/wps/tests/support/`，不引入隐式全局 fixture。

## 发布与兼容性

- 默认使用 Quick 发布；完整验证只在用户明确要求时使用；
- 新增正式源码、资源、测试和文档立即加入发布允许清单；新增长期文档立即登记 `docs/README.md`；
- 发布先在当前本地仓库创建提交，再通过 SSH 推送；
- 默认不生成 EXE，不自动更新版本号；只有明确发布新版本时才更新版本文件和 CHANGELOG；
- HTTP、SDK、SQLite、WPS 协议和业务功能不因本优化改变。

## 验收指标

- WPS 三组 Node 测试由一个入口执行，缺失测试文件直接失败；
- CI 不在 Python 矩阵中重复执行 Node 测试或 Recognition 回归；
- S 级任务不新增正式设计文档；L 级任务在源码改动前存在设计文档；
- Quick 验证不构建 EXE、不运行完整 WPS 门禁；
- 真实 WPS 未执行时明确报告 `REAL_WPS_SMOKE = NOT_RUN`；
- 当前工作树既有修改全部保留。

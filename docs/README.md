# DocxTool 文档导航

本文件是 `docs` 目录的唯一导航入口。现有文档路径保持稳定，按职责分组而不移动历史文件；新增文档先在这里登记，避免同一规则在多处重复维护。

## 阅读顺序

| 场景 | 先阅读 | 继续阅读 |
| --- | --- | --- |
| 任意代码或文档修改 | [`../AGENTS.md`](../AGENTS.md) | 本表对应的专项文档 |
| 查找项目文件或理解目录职责 | [`PROJECT_FILE_TREE.md`](PROJECT_FILE_TREE.md) | [`ARCHITECTURE_DAG.md`](ARCHITECTURE_DAG.md)、[`RECOGNITION_ARCHITECTURE.md`](RECOGNITION_ARCHITECTURE.md) |
| 识别、导入、分段、规范化或渲染 | [`RECOGNITION_ARCHITECTURE.md`](RECOGNITION_ARCHITECTURE.md) | [`DOCX_REGRESSION_CHECKLIST.md`](DOCX_REGRESSION_CHECKLIST.md)、[`RECOGNITION_RELEASE.md`](RECOGNITION_RELEASE.md) |
| 机械迁移或行为保持重构 | [`migration/README.md`](migration/README.md) | [`migration/codex-workflow.md`](migration/codex-workflow.md)、当前阶段清单 |
| Web API、前端或部署 | [`API.md`](API.md) 或 [`DEPLOY.md`](DEPLOY.md) | [`ARCHITECTURE_DAG.md`](ARCHITECTURE_DAG.md) |
| SDK、WPS、Word 或其他宿主 | [`SDK.md`](SDK.md) | 协议、定位和宿主适配文档 |
| 批量 DOCX 回归或问题复查 | [`DOCX_REGRESSION_CHECKLIST.md`](DOCX_REGRESSION_CHECKLIST.md) | [`RECOGNITION_RELEASE.md`](RECOGNITION_RELEASE.md) |
| GitHub 发布 | [`GITHUB_UPLOAD_GUIDE.md`](GITHUB_UPLOAD_GUIDE.md) | [`UPLOAD_MANIFEST.md`](UPLOAD_MANIFEST.md)、`scripts/publish_to_github.ps1` |

## 文档分组

### 项目与运维

- [`../README.md`](../README.md)：项目功能、启动方式和对外入口。
- [`API.md`](API.md)：Web HTTP 接口、鉴权、错误格式和前端接入。
- [`DEPLOY.md`](DEPLOY.md)：生产部署、环境变量、Nginx 和验证。
- [`GITHUB_UPLOAD_GUIDE.md`](GITHUB_UPLOAD_GUIDE.md)：安全发布到 GitHub 的唯一操作说明。
- [`UPLOAD_MANIFEST.md`](UPLOAD_MANIFEST.md)：发布文件清单与各文件职责，不替代发布命令。

### 文档识别与公文排版

- [`RECOGNITION_ARCHITECTURE.md`](RECOGNITION_ARCHITECTURE.md)：识别主链路、职责边界、状态和兼容 facade。
- [`PROJECT_FILE_TREE.md`](PROJECT_FILE_TREE.md)：项目根目录、生产源码、SDK、Web、脚本、文档和测试的逐文件中文职责树。
- [`ARCHITECTURE_DAG.md`](ARCHITECTURE_DAG.md)：Web、任务队列、SDK 和宿主适配的数据流图。
- [`DOCX_REGRESSION_CHECKLIST.md`](DOCX_REGRESSION_CHECKLIST.md)：已确认问题、回归场景和批量测试要求。
- [`RECOGNITION_RELEASE.md`](RECOGNITION_RELEASE.md)：发布门禁、快照比较、回滚和发布前验证。
- [`../公文格式规范.md`](../公文格式规范.md)：公文格式标准和排版配置依据。

### SDK 与宿主适配

- [`SDK.md`](SDK.md)：wheel 安装、Python 调用、CLI 和隐私边界。
- [`INTEGRATION_CONTRACT_V1.md`](INTEGRATION_CONTRACT_V1.md)：宿主无关 JSON 协议、状态、坐标和错误契约。
- [`RECOGNITION_SOURCE_LOCATORS.md`](RECOGNITION_SOURCE_LOCATORS.md)：来源定位、UTF-16 范围和安全绑定规则。
- [`HOST_ADAPTER_GUIDE.md`](HOST_ADAPTER_GUIDE.md)：WPS、Office.js 和 VSTO/COM 的宿主职责与伪代码。
- [`HOST_TEXT_V1_GOLDEN.json`](HOST_TEXT_V1_GOLDEN.json)：脱敏 host-text-v1 金标数据。
- [`examples/sdk-contract-examples.md`](examples/sdk-contract-examples.md)：SDK 协议示例。
- [`USER_WPS_VALIDATION.md`](USER_WPS_VALIDATION.md) 与 [`USER_WPS_VALIDATION_RESULT.md`](USER_WPS_VALIDATION_RESULT.md)：WPS 人工验收流程和记录模板。

### 迁移

- [`migration/README.md`](migration/README.md)：迁移文档目录说明、状态更新方式和新阶段模板。
- [`migration/codex-workflow.md`](migration/codex-workflow.md)：机械迁移的快速门禁、模块门禁、里程碑门禁、快照与报告格式。
- [`migration/phase-a2-checklist.md`](migration/phase-a2-checklist.md)：Phase A-2 已完成项、待办项、文件位置和验证记录。
- [`migration/phase-a3-final-looper-log.md`](migration/phase-a3-final-looper-log.md)：Phase A-3 Web、Engine 与最终门禁 checkpoint。

## 唯一职责

| 内容 | 唯一维护位置 |
| --- | --- |
| 跨任务强制协作规则 | `AGENTS.md` |
| 文档导航与归档位置 | 本文件 |
| 项目文件树和逐文件职责 | `PROJECT_FILE_TREE.md` |
| 识别链路和模块职责 | `RECOGNITION_ARCHITECTURE.md` |
| 运行时数据流 | `ARCHITECTURE_DAG.md` |
| 已知 DOCX 问题与回归要求 | `DOCX_REGRESSION_CHECKLIST.md` |
| 发布门禁和回滚 | `RECOGNITION_RELEASE.md` |
| 机械迁移执行方法 | `migration/codex-workflow.md` |
| 单个迁移阶段状态 | `migration/phase-*-checklist.md` |
| SDK 对外协议 | `INTEGRATION_CONTRACT_V1.md` |
| SDK 使用说明 | `SDK.md` |

## 扩展规则

1. 新文档先判断是否属于现有唯一职责；能补充现有文档时不新建重复文件。
2. 需要长期维护且主题独立的文档，放入明确子目录，例如 `docs/migration/` 或 `docs/examples/`；阶段状态使用 `phase-<name>-checklist.md` 命名。
3. 新建后同步更新本导航、发布清单和发布白名单。既有稳定路径不移动；需要重组时先添加导航链接或兼容说明，再由单独任务处理迁移。
4. 每份规范文档使用清晰的一级标题，并说明适用范围、非目标、权威来源和必要验证；示例和报告必须脱敏。

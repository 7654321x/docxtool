# DocxTool 文档导航

本目录只保留当前入口、外部契约、架构、回归、验收、发布和测试金标。专题设计、协议示例和迁移记录分别放在子目录中。

## 主文档

| 场景 | 文档 |
| --- | --- |
| Web HTTP 接口、鉴权和错误码 | [`API.md`](API.md) |
| 生产部署和环境变量 | [`DEPLOY.md`](DEPLOY.md) |
| 项目结构、文档主链、Web 与 SDK 数据流 | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| SDK 使用、来源定位和宿主适配 | [`SDK.md`](SDK.md) |
| SDK 正式 JSON 协议 | [`INTEGRATION_CONTRACT_V1.md`](INTEGRATION_CONTRACT_V1.md) |
| 公文识别、排版和发布回归 | [`DOCX_REGRESSION_CHECKLIST.md`](DOCX_REGRESSION_CHECKLIST.md) |
| WPS 登录、TaskPane、事务和宿主回归 | [`WPS_REGRESSION_CHECKLIST.md`](WPS_REGRESSION_CHECKLIST.md) |
| 真实 WPS 操作步骤和结果 | [`WPS_VALIDATION.md`](WPS_VALIDATION.md) |
| GitHub 发布范围、SSH 和安全边界 | [`RELEASE.md`](RELEASE.md) |
| Codex 工作流、任务分级和验证路由 | [`design/CODEX_WORKFLOW_OPTIMIZATION.md`](design/CODEX_WORKFLOW_OPTIMIZATION.md) |
| Ubuntu 直接 HTTPS Origin 部署 | [`design/UBUNTU_DIRECT_ORIGIN_DEPLOYMENT.md`](design/UBUNTU_DIRECT_ORIGIN_DEPLOYMENT.md) |
| 文首会议日期与会议说明识别 | [`design/MEETING_TITLE_METADATA_RECOGNITION.md`](design/MEETING_TITLE_METADATA_RECOGNITION.md) |
| 后台工作台、网页业务和 WPS 管理台设计 | [`design/ADMIN_WORKSPACE_WPS_TECHNICAL_DESIGN.md`](design/ADMIN_WORKSPACE_WPS_TECHNICAL_DESIGN.md) |
| SDK host-text-v1 测试金标 | [`HOST_TEXT_V1_GOLDEN.json`](HOST_TEXT_V1_GOLDEN.json) |

根目录 [`../公文格式规范.md`](../公文格式规范.md) 维护公文格式依据；`WPS_SERVER_PRD.md`、`WPS_SERVER_TECHNICAL_DESIGN.md` 和 `WPS_READER_PRD.md` 分别维护 WPS 公网产品、实现和 Reader 产品边界。

## 子目录

- [`design/`](design/)：WPS Reader UI、内置快捷样式、WPS 格式设置、Git 本地基线发布流程和 Codex 工作流等专题技术设计。
- [`examples/`](examples/)：脱敏 SDK 协议示例。
- [`migration/`](migration/)：已完成机械迁移和基线记录，不是当前架构来源。

## 唯一职责

1. 跨项目规则写入根 `AGENTS.md`，WPS 和 Reader 局部规则写入最近的目录级 AGENTS。
2. 当前架构只写入 `ARCHITECTURE.md`，不维护逐文件职责副本。
3. HTTP 契约只写入 `API.md`；SDK JSON 协议只写入 `INTEGRATION_CONTRACT_V1.md`。
4. 具体故障和验证命令写入对应 regression checklist。
5. 发布范围和操作只写入 `RELEASE.md`，可执行允许清单由 `scripts/publish_to_github.ps1` 维护。
6. 新增长期文档必须先确认现有主文档无法承载；专题设计放入 `design/`，不增加主目录文件。

## 文档验证

```pwsh
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m pytest tests/test_architecture_docs.py -q"
pwsh -NoProfile -Command "git diff --check"
```

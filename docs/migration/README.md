# 迁移文档目录

本目录保存已经完成的机械迁移和功能基线记录，不是当前架构或产品规则来源。当前架构见 `../ARCHITECTURE.md`，当前回归规则见对应 checklist。

本目录只存放行为保持重构和代码职责迁移的规则、阶段清单和脱敏验证记录。它不用于记录一般业务缺陷、用户 DOCX 内容、构建产物或发布日志。

## 入口

- [`codex-workflow.md`](codex-workflow.md)：所有机械迁移必须遵守的职责边界、门禁、快照比较和报告格式。
- [`phase-a2-checklist.md`](phase-a2-checklist.md)：已完成 Phase A-2 的状态和验证结果。
- [`phase-a2-looper-log.md`](phase-a2-looper-log.md)：Phase A-2 连续微批次的脱敏执行记录和等价验证摘要。
- [`phase-b0-report.md`](phase-b0-report.md)：Phase B-0 功能基线、边界修复、P1 根因聚类和验证结论。
- [`phase-b0-manifest.json`](phase-b0-manifest.json)：2.2/2.6/2.7/current 的固定样本、配置、版本和制品哈希。

## 新阶段的建立方式

1. 先在根目录 `AGENTS.md` 和 [`../README.md`](../README.md) 确认现有规则与文档职责。
2. 为新阶段新增 `phase-<name>-checklist.md`，至少包含“阶段范围、已完成项、当前待办项、新文件位置、已执行验证、阻断项”。
3. 在 [`../README.md`](../README.md) 登记入口；如该文件属于发布范围，同步更新上传清单和发布白名单。
4. 机械迁移期间只推进一个职责。未解释快照差异或测试差异立即标记为 `blocked`，停止进入下一职责。

## 边界

阶段清单只记录已验证的事实和下一项明确工作，不作为 Git 提交记录或发布公告。业务规则调整、识别质量优化、SDK 契约修改和 WPS 宿主开发均应建立各自的专项文档与验收标准。

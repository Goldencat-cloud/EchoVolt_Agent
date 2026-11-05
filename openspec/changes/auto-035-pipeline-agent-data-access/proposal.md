# Proposal

- Change ID：auto-035-pipeline-agent-data-access
- Owner：本会话用户（负责第一阶段，具体署名待补）。
- 开发分支：change/auto-035-pipeline-agent-data-access；交付 PR 待创建。
- 用户授权：2026-10-30 本会话用户确定动态数据、保留分析方法、统一全量口径及逐次大纲审查后自动发布，并指示取消其他负责人审阅、继续实施。此为用户对本次工作明确授权，不虚构其他负责人的审阅。最终代码审阅与合并仍待人类处理；用户署名待补。

## Why

现有 Agent 查询依赖旧报告快照；未来分析应直接读取持续更新的新离线管道数据，并支持正式报告自动更新。

## What Changes

- **BREAKING**：直接只读访问动态更新的新管道数据库；新数据入库后影响下一次分析，不要求维护固定版本，也不把每次查询转换为旧快照。
- **BREAKING**：本次分析统一使用全量主张口径，不再保留 core/potential 精选子集口径；现有分析方法继续保留，标明过滤条件、范围和未归属数据。
- 使用 06 报告引文匹配规则并标注状态；不明确归属的多运行产品链接拒绝查询；保持大纲审查、数字溯源和 Claim–Evidence 回查。
- **BREAKING**：正式报告每次生成均由人审查大纲，通过后自动执行并发布；自动触发与异常处理的具体设计待审阅。
- 不运行全量抽取或全量归一，不扩展多品牌能力；运行一例真实 Deep Agents 分析并对账。

## Capabilities

### New Capabilities

- `pipeline-agent-data-access`：动态数据读取、单次分析一致性、证据追踪及自动报告更新。

### Modified Capabilities

无。正式 specs 当前为空；本变更涉及未归档的 auto-030、auto-031、auto-032 契约，用户已取消其他负责人审阅，实施时须验证兼容性。

## Impact

预计涉及 08_semantic_services 的 research/service.py、db_mirror.py、agent_tools.py、任务简报与相关测试；实际文件与接口在 design 中进一步限定。已定位 pipeline-01-06 的 04–05 数据库，报告所记数据库哈希与当前文件不同，须独立对账。

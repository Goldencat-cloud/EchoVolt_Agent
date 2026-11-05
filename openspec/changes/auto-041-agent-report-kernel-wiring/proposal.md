# Proposal

- **Change ID**: `auto-041-agent-report-kernel-wiring`
- **Human Owner**: Llewyn Davis（2026-11-03 确认无并行改动方，选择"先立项再一次改完"的方案 A）
- **规格评审状态**: 已授权实施（Owner 2026-11-03 指令"开始"）；逐条规格评审记录与审阅 commit 仍待补
- **工程状态**: `REVIEW_READY`（实施与本地回归完成，待人工代码评审）
- **端到端**: 已执行（2026-11-03，job `1cf920cb7e964b61b11f52c159af4ba9`，113 秒，14 字段齐全，`metrics.gate_rejections=1`）
- **分支**: `change/auto-041-agent-report-kernel-wiring`（自 `change/auto-040-agent-kernel-wiring` 开出）
- **依赖**: `auto-038-agent-kernel-unification`（内核）、`auto-040-agent-kernel-wiring`（问答链路已接线）
- **关联 Issue/PR**: 无（本仓库尚无远端门禁）

## Why

`auto-040` 只把问答链路接到内核；交付链路（深度分析报告）仍在 `agent_engine.report_outcome` 里自行拼装响应，`kernel.derive.to_report_view` 至今只被测试调用。同一套"账本 → 响应"的映射因此仍是两处实现：报告字段的命名、截断与计数规则会随时间再次分叉，而 `auto-040` 已证明这类分叉只能靠人眼发现。

## What Changes

- `kernel.context.RunContext` 新增 `gate_rejections` 字段，`metrics()` 返回真实计数而非硬编码 `0`。
- `agent_engine.report_outcome` 改为构造 `RunContext` 快照后调用 `kernel.derive.to_report_view`；`charts` / `evidence_index` / `tool_log` 仍由既有协作者产出后注入，不在内核里重复实现。
- `report_session.ReportSession` 的上下文由 `dict` 迁移到 `RunContext`（既有工具经 `tool_context()` 桥接）；`outline_approved`、`outline_decision`、`delivery_spec` 迁入声明字段或 `EXTRA_KEYS` 白名单。
- 保持深度分析结果的响应字段逐键不变：`ok`、`report_id`、`title`、`report_md`、`key_findings`、`publication_status`、`data_version`、`charts`、`evidence_index`、`final_message`、`tool_log`、`tool_errors`、`metrics`、`elapsed_ms`。
- **BREAKING**：无。

### 明确排除

1. 不改 `app.py` 的 HTTP 契约、限流与任务调度。
2. 不接入 `routing/gates.py`（属独立决策，`auto-040` 亦未纳入）。
3. 不改提示词、工具描述、预算数值，不改图表与证据索引的产出逻辑。
4. 不统一"工具预算双来源"（图 `recursion_limit` vs `Budget`），留待后续变更。
5. 不产生 spec delta：本次是纯实现替换，对外行为不变。

## Capabilities

### New Capabilities

无。本次不引入新的系统行为。

### Modified Capabilities

无。响应契约、字段取值与错误提示均保持不变，故不写 delta spec；`.openspec.yaml` 标记 `skip_specs: true`。

## Impact

- **修改**：`kernel/context.py`（字段与 `metrics`）、`agent_engine.py`（`report_outcome`）、`report_session.py`（会话上下文）、`kernel/README.md`（接线状态与字段表）
- **受影响测试**：`test_kernel_derive.py`（对照基准需改成构造快照）、`test_report_charts.py`、`test_report_gate_consistency.py`、`test_kernel_wiring.py`（扩展报告侧断言）
- **风险**：报告链路没有接线前的端到端录像基准，等价性只能由 derive 层字段对照加一次真实模型端到端运行来证明；后者成本为 81–111 秒/次、约 20–30 万 tokens，本机当前不具备已批准的数据传输环境
- **回滚**：三处函数级改动，无数据或 schema 迁移，`git revert` 即可恢复

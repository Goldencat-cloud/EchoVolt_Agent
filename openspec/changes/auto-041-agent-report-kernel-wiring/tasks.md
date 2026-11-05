# Tasks

前置：`auto-038` 内核与 `auto-040` 问答链路接线已交付到本分支历史。本变更只改交付链路，实施顺序见 `design.md` D7。

## 1. 内核字段（D1 / D2）

- [x] 1.1 `kernel/context.py` 的 `RunContext` 新增 `gate_rejections: int = 0`、`outline_approved: bool = False`、`outline_decision: dict | None = None`，`metrics()` 返回真实 `gate_rejections`。验证：`tests/test_kernel_context.py` 新增用例断言三个默认值与 `metrics()` 真实计数，既有用例保持不变。
- [x] 1.2 `ToolContext` 的键集合覆盖新增字段，使工具侧 `context.get("outline_approved")` 与 `context["gate_rejections"] += 1` 可用。验证：扩展 `tests/test_kernel_wiring.py` 的键覆盖断言；未登记键仍抛 `KeyError`。
- [x] 1.3 更新 `kernel/README.md` 的字段表与接线范围说明。验证：字段表与 `dataclasses.fields(RunContext)` 逐项一致。

## 2. 报告组装接线（D4 / D5 / D6）

- [x] 2.1 `agent_engine.report_outcome` 增加 `_as_context()` 窄转换（接受 `RunContext | Mapping`），成功路径改调 `kernel.derive.to_report_view`；保留缺提交时的原 `RuntimeError` 与最近工具调用尾部。验证：`tests/test_kernel_derive.py` 的 11 字段对照仍通过，新增用例断言缺提交时消息仍含工具日志。
- [x] 2.2 `charts` / `evidence_index` / `tool_log` 仍由 `report_charts`、`service`、langgraph state 产出后注入，不在内核重复实现。验证：`tests/test_report_charts.py` 两个用例通过。
- [x] 2.3 在 `tests/test_kernel_wiring.py` 增加报告侧断言：dict 入参与 `RunContext` 入参产出同一视图；`to_report_view` 缺提交抛 `KernelContractError`（`RuntimeError` 子类，不破坏既有 `except RuntimeError`）。验证：新增用例全部通过。

## 3. 会话状态迁移（D3 / D2）

- [x] 3.1 `ReportSession._context` 改为 `RunContext`，`build_tools` 传入 `tool_context()`，构造时带入 `progress`、`live_context`、`interactive`。验证：`tests/test_interrupt_gate_spike.py`、`tests/test_outline_gate.py` 通过。
- [x] 3.2 `resume()` 的 `pop("outline_decision")` 改为 `ctx.outline_decision = None`，`set_delivery_spec` 写 `extras["delivery_spec"]`。验证：新增用例覆盖"未审批时工具读到 `None`"与"审批后写入 decision"。
- [x] 3.3 `close()` 释放 `live_context` 的时机不变（会话级，不随 `RunContext` 生命周期改变）。验证：`tests/test_live_session_lifecycle.py` 通过。
- [x] 3.4 闸门拒绝计数经字典桥写入后，`metrics.gate_rejections` 为真实值。验证：`tests/test_report_gate_consistency.py` 既有断言不变，另加一条基于 `tool_context()` 的等价用例。

## 4. 集成验证

- [x] 4.1 全量回归：`unittest tests.test_kernel_context tests.test_kernel_profile tests.test_kernel_registry tests.test_kernel_runner tests.test_kernel_gates tests.test_kernel_derive tests.test_kernel_equivalence tests.test_kernel_wiring tests.test_api tests.test_frontend_contract tests.test_agent_workflow tests.test_intent tests.test_auto030_contracts tests.test_report_charts tests.test_report_gate_consistency tests.test_interrupt_gate_spike tests.test_outline_gate tests.test_live_session_lifecycle tests.test_live_agent_tools`。验证：记录实际 `Ran N tests` 与 `OK`。
- [x] 4.2 深度分析链路端到端：`POST /api/agent/report` → 轮询 `/api/agent/report/{id}` → 大纲 confirm → 轮询至终态，确认 `result` 的 14 个字段（`ok`/`report_id`/`title`/`report_md`/`key_findings`/`publication_status`/`data_version`/`charts`/`evidence_index`/`final_message`/`tool_log`/`tool_errors`/`metrics`/`elapsed_ms`）齐全且 `metrics.gate_rejections` 为真实计数。验证：记录 job_id、终态与字段快照；仅此链路会经过 `report_outcome`（`report_session._outcome` 是唯一生产调用方），对话链路的 `/api/question` 测不到本变更。

## 证据（2026-11-03 实际执行）

| 项 | 检查 | 结果 |
|---|---|---|
| 1.1 | `ReportGateStateTests`：三个字段默认值、`metrics()` 真实计数 | 通过 |
| 1.2 | `ContextBridgeTests.test_bridge_exposes_report_gate_keys`、`test_bridge_exposes_no_undeclared_key`、`test_bridge_length_matches_iteration` | 通过；键集合与长度自洽 |
| 1.3 | `kernel/README.md` 字段表与接线范围 | 通过 |
| 2.1 | `ReportOutcomeWiringTests.test_missing_submission_keeps_tool_log_in_message`；`test_kernel_derive` 字段对照 | 通过 |
| 2.2 | `tests/test_report_charts.py`（含 `test_report_outcome_delivers_charts`） | 通过 |
| 2.3 | `ReportOutcomeWiringTests`（dict 与 `RunContext` 同视图、`KernelContractError` 是 `RuntimeError`） | 通过 |
| 3.1 | `test_interrupt_gate_spike`、`test_outline_gate`、`test_live_session_lifecycle` | 通过（1 skipped 为既有跳过） |
| 3.2 | `ReportSessionGateStateTests`（approve/edit/reject 三条） | 通过 |
| 3.3 | `test_live_session_lifecycle` | 通过 |
| 3.4 | `test_gate_rejection_count_survives_kernel_context` | 通过；`metrics.gate_rejections == 1` |
| 4.1 | 19 个模块 | `Ran 228 tests`，`OK (skipped=1)` |
| 4.2 | job `1cf920cb7e964b61b11f52c159af4ba9`：clarifying → awaiting_review → confirm → done（113 秒） | 14 字段齐全；`charts=2`、`evidence_index=20`、`key_findings=5`、`tool_log=24`、`tool_errors=0`；`metrics={"successful_tool_calls":9,"tool_errors":0,"code_failures":0,"submit_attempts":2,"gate_rejections":1}` |

**4.2 的关键含义**：`gate_rejections=1` 与 `submit_attempts=2` 表明该 job 确实被大纲闸门拒绝过一次后重提——这正是 D1 的直接证据：若 `RunContext` 缺该字段，`agent_tools.py:796` 写入即 `KeyError`；若 `metrics()` 仍是硬编码 `0`，此处会显示 `0`。`data_version` 为完整 `snapshot_version()`，未经过 `_present()` 覆盖（`agent_report_status` 返回裸 job），与 D8 的分析一致。

## Workflow follow-up

- AI 生成代码需人工评审，不由实现者自行验收。
- 端到端补测完成后回写 `tasks.md` 证据表与 `proposal.md` 状态。
- 交付 PR 合并且 Owner 验收后，再通过独立维护变更同步规格与归档。

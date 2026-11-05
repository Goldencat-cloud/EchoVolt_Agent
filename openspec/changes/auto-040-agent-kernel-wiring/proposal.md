# Proposal

- **Change ID**: `auto-040-agent-kernel-wiring`
- **Human Owner**: Llewyn Davis（2026-11-03 明确指示"现在就接线"）
- **规格评审状态**: 已批准（Owner 口头指令即授权；本变更不改对外契约，见下）
- **依赖**: `auto-038-agent-kernel-unification`（内核已就绪，30/30 任务完成）
- **工程状态**: `REVIEW_READY`（接线与本地回归完成，待人工代码评审）
- **待人工补测**: 任务 2.2 / 2.3 需要真实模型调用与重启后的服务，未在本机执行；synthetic fixture 不能替代端到端字段比对
- **未验证项**: 无远程操作、未开分支/PR、未跑真实数据端到端

## Why

`auto-038` 只建内核不接线，`kernel/` 尚未被生产路径引用。要让已经证明等价的内核真正生效，必须把交互链路的上下文、工具白名单与派生改为经由内核，否则内核会长期作为"影子实现"存在，两份逻辑继续各自演化。

## What Changes

- `agent_engine._run_agent_conversation` 改为：用 `kernel.RunContext` 承载状态、用 `kernel.profile.INTERACTIVE` 过滤工具、用 `kernel.derive.to_answer_view` 生成响应。
- 保持**返回字典逐字段不变**（已由 20 条 fixture 证明等价）。
- **不改**：HTTP 契约、提示词、工具描述、预算数值、交付链路（`report_session.py`）、模型调用方式。
- **BREAKING**：无。

### 明确排除

1. 不接线交付链路（`ReportSession` / `deepagents`），它由 `auto-030` 主导，冲突面最大。
2. 不改 `agent_tools.py`（工具仍按 dict 接口工作，经 `ToolContext` 桥接）。
3. 不改 `app.py`，不接入 `routing/gates.py`（属独立决策）。
4. 不删除 `routing/intent.py`。

## Capabilities

纯内部接线，不改变任何系统行为，故不产生 spec delta（`.openspec.yaml` 标记 `skip_specs: true`）。

### New Capabilities

无。

### Modified Capabilities

无。

## Impact

- **修改**：`offline_analysis_pipeline/08_semantic_services/agent_engine.py`（`_run_agent_conversation` 一个函数）
- **新增**：`tests/test_kernel_wiring.py`（接线后的等价与回归守卫）
- **并行风险**：`agent_engine.py` 同时被 `auto-025/028/030` 修改。本变更把改动压缩到单函数内部，尽量缩小合并面；若与在建变更冲突，以 Owner 协调结果为准，不静默覆盖。
- **回滚**：单函数改动，`git revert` 即恢复原实现。

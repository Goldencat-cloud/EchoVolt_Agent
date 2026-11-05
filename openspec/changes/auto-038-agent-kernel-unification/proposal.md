# Proposal

- **Change ID**: `auto-038-agent-kernel-unification`
- **Human Owner**: Llewyn Davis（当前项目使用者本人，2026-11-03 确认为本变更 Owner）
- **规格评审状态**: 已批准（见下方记录）
- **阶段**: Phase 1（只建内核，不接线）

### 规格评审记录

| 字段 | 内容 |
|---|---|
| Reviewer | Llewyn Davis（Human Owner） |
| 日期 | 2026-11-03 |
| Reviewed commit | `4f70ba74`（工作区产物未提交，评审对象为 `openspec/changes/auto-038-agent-kernel-unification/` 下的 proposal/design/tasks） |
| 结论 | 批准进入 Phase 1 实现 |
| 未决事项 | Phase 2（接线）不批准，需单独立项；`create_agent`/`create_deep_agent` 统一留待 spike |
| AI 评审 | 无独立 AI 评审记录；本次评审为 Owner 自审，AI 协助不构成评审 |

## Why

`08_semantic_services` 的交互链路（`/api/question`）与交付链路（`/api/agent/report`）各自维护一份上下文结构、预算常量、agent 装配与结果派生逻辑。同一语义存在两份实现：上下文 dict 两份且字段集合已漂移；`verified_steps` 有两种消费方式且字段映射规则只存在于其中一支；工具集按黑名单裁剪导致语义失效的工具仍暴露；工具预算与图递归上限互相矛盾。结果是新增能力必须改两处，漏改一处即静默失效。

现在做这件事而不是继续叠加功能，是因为：八份在建变更正在同一批文件上并行，继续叠加只会让重复面积扩大；且 Phase 2（接线）必须先有等价性证据，否则无法证明重构没有改变对外行为。

## What Changes

- 新增 `kernel/` 包（全新文件，不改动任何现有模块）：`context`（唯一上下文 schema）、`profile`（预算/递归/中间件/工具白名单/产物/失败策略的声明式配置）、`builder`（唯一 agent 装配入口）、`runner`（统一状态机 `run`/`resume`）、`derive`（`verified_steps` 到输出的唯一派生层）、`registry`（工具能力登记）。
- 新增 `routing/gates.py`：输入硬门（长度、空输入、注入特征），只返回拦截原因，不做话题分类。
- 新增内核契约测试与**影子等价比对**框架：用录制的 fixture 回放旧实现与新内核，逐字段比对，证明等价。
- **不改动**：`app.py`、`agent_engine.py`、`report_session.py`、`agent_tools.py`、`prompts.py`、`jobs.py` 的任何行为与内容——本变更对它们只读。
- **BREAKING**：无。本变更不改变任何对外契约，生产路径不被调用。

### 明确排除（Out of Scope）

1. 不接线：老模块不改薄壳、不转调内核。接线属于后续变更，依赖在建变更交付。
2. 不扩普通问答能力：不放开 `python_analyze`、不新增结构化输出、不新增升级（escalation）机制。
3. 不改预算数值、递归上限、提示词文案、工具描述、错误码。
4. 不统一 agent 构造库（`create_agent` 与 `create_deep_agent` 并存），该决策留待 Phase 2 独立验证。
5. 不删除或归档 `routing/intent.py`，也不归档任何在建变更。
6. 不写入 `openspec/specs/`（正式规格）。

## Capabilities

本变更为**纯结构重构，不改变任何系统行为**，因此不产生 spec delta：内核的模块划分、接口与约束属于工程实现约束，记录在 `design.md`，不作为能力需求。

按 `openspec/config.yaml` 的约定，零 delta 的变更需在 `.openspec.yaml` 标记 `skip_specs: true`；本次已标记，且不虚构需求以满足校验。

### New Capabilities

无。

### Modified Capabilities

无。

## Impact

- **新增代码**：`offline_analysis_pipeline/08_semantic_services/kernel/*`、`routing/gates.py`、`tests/test_kernel_*.py`（均为新文件）
- **只读依赖**：`agent_engine.py`、`report_session.py`、`agent_tools.py`、`app.py`、`prompts.py`、`jobs.py`、`agent_tools.py` 所用到的 `research/`、`sandbox.py`、`report_gate.py`
- **不受影响**：HTTP API 契约、提示词与工具描述、预算数值、数据快照与 `snapshot_version` 语义、MCP 适配器、前端
- **并行约束**：`auto-025`、`auto-027`、`auto-028`、`auto-030`、`auto-031`、`auto-032`、`auto-033`、`auto-034` 正在修改上述只读文件，其中 `auto-030` 占用六份文件。本变更以新增文件规避冲突，接线须待相关变更交付合并并由 Owner 验收后再立项。
- **风险**：等价性验证依赖录制的模型响应 fixture；真实模型非确定性会使直接比对失效，故不在验证路径中调用真实模型。

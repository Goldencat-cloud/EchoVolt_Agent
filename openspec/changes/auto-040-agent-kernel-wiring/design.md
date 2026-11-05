# Design

## Context

`auto-038` 产出的 `kernel/` 已通过 20 条 fixture 的字段级等价验证，但生产路径未引用。现网交互链路的上下文、工具过滤与派生仍内联在 `agent_engine._run_agent_conversation`（见 `auto-038/design.md` 的事实清单）。

接线目标是最小侵入：**只替换该函数内部的三段逻辑，不改函数签名与返回值**。

## Goals / Non-Goals

**Goals:**

1. 交互链路的状态、工具白名单、派生全部经由 `kernel/`。
2. 对外响应逐字段不变（以 fixture 与既有测试为判据）。
3. 改动集中在单函数，便于与在建变更协调与回滚。

**Non-Goals:**

1. 不接线交付链路（`ReportSession`）——`auto-030` 主战场。
2. 不改工具实现（`agent_tools.py` 保持 dict 接口）。
3. 不接入 `routing/gates.py`、不改 `app.py`。

## Decisions

### D1 用 `ToolContext` 桥接而不是改工具签名

**选择**：`agent_tools.build_tools(ctx.tool_context())`。

**理由**：9 个工具都以 `dict` 读写上下文（`context.setdefault("verified_steps", []).append(...)` 等）。改签名会同时触碰 `agent_tools.py`（`auto-030/025/028` 正在改）。桥接层让工具零改动，且写入仍落回同一个 `RunContext`。

**代价**：`StepLedger.raw()` 成为账本的旁路写入通道；已在 `kernel/README.md` 标注"新代码必须用 `record_step`"，并由 C5 源码断言限制新增代码。

### D2 工具过滤改为白名单，但保持集合等价

**选择**：`[t for t in build_tools(...) if INTERACTIVE.allows(t.name)]`。

**理由**：旧实现用 `CONVERSATION_EXCLUDED_TOOLS` 黑名单。白名单必须产出同一集合（7 个工具），否则行为会变。等价性由 `test_kernel_equivalence.test_tool_whitelist_matches_legacy_exclusion` 与新增接线测试共同守住。

### D3 派生改调 `derive.to_answer_view`，参数显式传入

**选择**：`data_version` / `snapshot_hash` / `source_mode` / `live` / `sanitizer` / `citation_parser` 在调用点传入，派生层不 import `service` 或 `report_source`。

**理由**：保持 `derive.py` 纯函数性质（可离线测试）；同时保证与旧实现的调用顺序一致（先去未知引用，再解析引用）。

### D4 预算取 `INTERACTIVE.budget`（tool_calls=14）

**理由**：与旧实现的真实可达轮次一致（递归 32 节点 → 约 14 次）。注意：旧代码的预算计数由 `agent_tools` 内部常量（18）约束，本变更不改 `agent_tools.py`，因此**运行期实际仍是 18 的软上限 + 32 节点递归硬上限**；`RunContext` 的预算在此阶段只用于记录与断言，不替代工具的计数逻辑。该不一致在 Phase 3（改造工具预算来源）解决。

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| 与 `auto-030/025/028` 在同一文件冲突 | 改动只限一个函数内的三段，合并面最小；冲突时不静默覆盖，交 Owner 协调 |
| 预算存在两处来源（`RunContext.budget` 与 `agent_tools` 常量） | 本阶段只记录不替换，已在 D4 说明；Phase 3 统一 |
| `report_hits` 等键经桥接写入，漏映射会导致字段丢失 | fixture 已覆盖 `report_hits` 上限；接线后再跑 e2e 复核 |
| 派生参数顺序错误导致 citations 变化 | 参数与原实现一一对应；fixture 全字段比对会立即暴露 |

## Migration Plan

1. 改 `_run_agent_conversation` 的三段逻辑。
2. 跑 `test_kernel_*` + 既有回归（`test_api` / `test_frontend_contract` / `test_agent_workflow` / `test_intent`）。
3. 重启服务，复跑端到端问答（含工具路径与报告语料路径）。
4. 回滚：单函数 `git checkout -- agent_engine.py`。

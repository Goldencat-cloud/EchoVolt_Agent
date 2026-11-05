# Design

## Context

动机见 `proposal.md - Why`。这里只记录实现所依赖的现状事实。

**已验证的现状（读代码确认，2026-11-03，基线 `ab9a100b`）：**

| 事实 | 位置 |
|---|---|
| 交付链路的运行期状态是一个 dict，且被动态塞入未声明的键 | `report_session.py:92-99`、`:163-171`、`:186` |
| 该 dict 直接交给工具层按 dict 读写 | `report_session.py:103` `agent_tools.build_tools(self._context)` |
| 工具读取 `outline_approved` 与 `outline_decision` | `agent_tools.py:742`、`:807` |
| 工具写入 `gate_rejections`，而内核没有对应字段 | `agent_tools.py:796` |
| `RunContext.metrics()` 的 `gate_rejections` 是硬编码 `0` | `kernel/context.py:174` |
| 字典桥不支持删除键 | `kernel/context.py:237-238` `__delitem__` 抛错 |
| `report_outcome` 自行组装 14 个响应字段，未走 `to_report_view` | `agent_engine.py:114-165` |
| `to_report_view` 已存在且与 `report_outcome` 有 11 字段对照测试 | `kernel/derive.py:88-120`、`tests/test_kernel_derive.py:72-94` |
| `report_outcome` 在缺提交时抛 `RuntimeError`，消息含最近工具调用尾部 | `agent_engine.py:120-125` |
| `KernelContractError` 继承 `RuntimeError` | `kernel/context.py:23` |
| 工具的实际调用上限来自 `agent_tools` 常量，不经过 `Budget.spend_*` | `agent_tools.py:41-42`、`:190-220` |

**尚未验证（本机不具备条件）：** 真实模型下的端到端报告运行；`report_session` 在暂停/恢复过程中与外层 job 存储的交互时序只能靠既有测试与代码阅读推断。

## Goals / Non-Goals

**Goals:**

- 交付链路的运行期状态与问答链路使用同一个 `RunContext`，不再各自维护 dict schema。
- `report_outcome` 的响应组装只保留 `to_report_view` 一处实现，字段映射、截断与计数不再分叉。
- 迁移过程中对外响应逐字段不变，缺提交时的错误提示内容不变。

**Non-Goals:**

- 不统一"工具预算双来源"（`agent_tools` 硬编码上限 vs `RunContext.budget`）。迁移后 `budget` 仍只作声明，工具侧照旧读常量；这条不一致在 `kernel/README.md` 中已标为 Phase 3 之后的独立事项。
- 不把 `report_charts` 与 `service` 下沉进内核，内核继续通过参数接收它们的结果。
- 不改 `agent_tools.py` 的任何一行。
- 不改 `app.py`、任务队列、HTTP 契约与限流。

## Decisions

### D1：`gate_rejections` 作为 `RunContext` 的显式字段

`agent_tools.submit_report` 被大纲闸门拒绝时会写 `context["gate_rejections"]`，而字典桥对未声明的键抛 `KeyError`。这不是"可能出问题"，而是**接线第一步必炸**。

- 采用：`RunContext` 新增 `gate_rejections: int = 0`，`metrics()` 返回该字段而非 `0`。
- 备选：放进 `extras` 白名单。否掉——它是计数器，与 `tool_errors` / `submit_attempts` 同级，放辅助键会让 `metrics()` 变成"一半字段一半 extras"。
- 副作用：`metrics.gate_rejections` 从"恒为 0"变为真实计数。生产路径原本读的是 dict 里的真实值（`agent_engine.py:111`），所以对外数值不变；变的只是内核自己不再撒谎。

### D2：`outline_approved` / `outline_decision` 作为显式字段，删除改为置空

`resume()` 里有 `self._context.pop("outline_decision", None)`，而字典桥禁止删除。两个键都被工具读取，属于"决定报告能否发布"的核心状态。

- 采用：新增 `outline_approved: bool = False`、`outline_decision: dict | None = None`；`pop` 改为 `ctx.outline_decision = None`。
- 等价性论证：工具侧只用 `context.get(...)`，键不存在与值为 `None` 的返回结果相同，因此置空与删除对该读取路径等价。
- 备选：加入 `EXTRA_KEYS`。否掉——`EXTRA_KEYS` 的定位是"既有工具的非核心辅助键"，把发布闸门状态混进去会让白名单失去意义。

### D3：`ReportSession` 持有 `RunContext`，工具仍走字典桥

- 采用：`self._context: RunContext | None`，`build_tools(self._context.tool_context())`；工具代码零改动。
- 备选：把 `agent_tools` 全部改成接收 `RunContext`。否掉——改动面覆盖 9 个工具、900 余行，且与"本变更只做接线"的范围冲突。
- 已知代价：字典桥是迁移期适配层，`ToolContext` 的 `__iter__` 只有固定的键集合，任何新键仍需先登记。

### D4：`report_outcome` 接受 `RunContext | Mapping`，并在内部做一次窄转换

- 采用：签名放宽为 `report_outcome(context: RunContext | Mapping[str, Any], state, question, started)`；内部 `_as_context()` 把 mapping 转成 `RunContext`。生产路径直接传 `RunContext`，离线脚本与既有测试传 dict 仍然可用。
- 备选：只接受 `RunContext`。否掉——`tests/test_kernel_derive.py:85` 与可能的离线脚本会直接断掉，且没有收益。
- `_as_context()` 只映射已声明字段与 `EXTRA_KEYS`；遇到不认识的键**忽略而非报错**，因为它是兼容层，不是新的 schema 入口。这一点与 `RunContext` 构造期严格报错（C2）不冲突：严格性保留在真正的状态源上。

### D5：缺提交的错误与工具日志留在 `agent_engine`

`to_report_view` 抛 `KernelContractError`，消息只含最终消息前 500 字符；而现有 `report_outcome` 的消息还带最近工具调用尾部（1500 字符），这是排查"报告为什么没交"的主要线索。

- 采用：在调用 `to_report_view` 之前保留原有的 `submission is None` 检查与原消息，`to_report_view` 只负责成功路径的组装。
- 备选：给 `to_report_view` 加 `error_detail` 参数。否掉——内核不必知道 `_tool_log` 这种 state 形状。

### D6：`charts` / `evidence_index` / `tool_log` 仍由 `agent_engine` 产出后注入

它们依赖 `report_charts`、`service.evidence_details`、`live_evidence` 与 langgraph state，属于协作者而非派生逻辑。`to_report_view` 已经把这些设计成参数。

### D7：文件归属与集成顺序

| 顺序 | 文件 | 内容 | 单独可验证 |
|---|---|---|---|
| 1 | `kernel/context.py` | 三个字段 + `metrics()` 修正 | 是（新字段默认值，既有测试不变） |
| 2 | `kernel/README.md` | 字段表补充 | 是（文档） |
| 3 | `agent_engine.py` | `report_outcome` 改走 `to_report_view` | 是（`test_kernel_derive` 对照测试） |
| 4 | `report_session.py` | `_context` 迁移 | 是（既有会话测试） |
| 5 | `tests/test_kernel_wiring.py` | 增加报告侧断言 | 是 |

第 3 步不依赖第 4 步（`_as_context()` 让两者解耦），因此即使第 4 步回退，第 3 步仍然成立。这是刻意设计的降级路径：状态机迁移出问题时，可以只回退第 4 步。

无并行工作方，同一物理文件只有一个写入者。

### D8：验证路径映射（先有链路，再写断言）

端到端场景必须由被改代码的调用链反推，而不是复用上一个变更的场景。本次经代码确认的链路：

| 改动点 | 唯一生产调用方 | 外部入口 | 可观测字段 |
|---|---|---|---|
| `report_outcome` | `report_session._outcome`（`report_session.py:208`） | `POST /api/agent/report` → 轮询 `/api/agent/report/{id}` | `job["result"]` 的 14 个字段 |
| `ReportSession._context` | 同上（`run` / `resume` 共用同一实例） | 同上，含 `POST /api/agent/report/{id}/outline` | `job["status"]`、提交后的 `result` |
| `RunContext.gate_rejections` | `agent_tools.submit_report`（`:796`）写入 → `metrics()` 读出 | 同上 | `result["metrics"]["gate_rejections"]` |

反例（本次修正）：`/api/question` 走 `_run_agent_conversation`，只覆盖 `to_answer_view`，与 `report_outcome` 无关；`/api/ask` 走 `ask_core` 的报告问答 RAG，两条内核路径都不经过。用它们验证本变更会得到"全绿但没测到"的假结论。

另注：`_present()`（`app.py:445`）只在 `/api/analyze`、`/api/question` 的返回上覆盖 `data_version` 为 `display_version()`；`agent_report_status` 返回裸 job，因此深度分析 `result.data_version` 仍是完整的 `snapshot_version()`。两个入口的版本字符串本来就不同，不能互相作为基准。

## Risks / Trade-offs

- **没有接线前的端到端录像基准** → 等价性由 `test_kernel_derive.py` 的字段对照（11 个确定性字段）+ 新增接线断言保证；端到端仍需一次真实运行，本次不把它算作已完成。
- **报告失败语义是 terminal，出错代价高** → 按 D7 分五步，第 3、4 步互相独立；每步完成后跑全量回归，任一步失败只回退该步。
- **`pop` 改置空可能影响"未审批"判断** → `agent_tools.py:742` 与 `:807` 都是 `context.get(...)`，置 `None` 与缺失等价；新增断言直接覆盖该路径。
- **`_as_context()` 忽略未知键可能掩盖拼写错误** → 只在兼容入口使用，真正的状态源仍是 `RunContext`；新增测试断言 `ToolContext` 遇到未登记键仍抛错。
- **状态机迁移引入时序问题** → `ReportSession` 只在 `_ensure_agent` 中构造一次 `RunContext`，`run`/`resume` 复用同一实例；与原先"复用同一 dict"的时序一致，不新增生命周期。

## Migration Plan

1. 在 `change/auto-041-agent-report-kernel-wiring` 分支上按 D7 顺序实施，每步单独提交。
2. 每步后执行：`unittest` 全量（内核 8 模块 + `test_kernel_wiring` + `api`/`frontend_contract`/`agent_workflow`/`intent`/`auto030_contracts` + `report_charts`/`report_gate_consistency`）。
3. 全部通过后，请求人工评审。
4. 回滚：第 4 步与第 3 步可独立 `git revert`；第 1 步的字段是纯增量，回退需同时回退其使用点。

## Open Questions

- 端到端哪三条场景用于人工补测（工具路径 / 报告语料路径 / 纯澄清路径这类组合）尚未确定，由 Owner 在执行时选；不影响本设计的分步方案。

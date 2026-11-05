# Design

## Context

### 已验证事实（读码所得，非推断）

| 事实 | 位置 |
|---|---|
| 交互链路与交付链路各有一份上下文初始化 | `agent_engine.py:196-199`、`report_session.py:65-70` |
| 图递归上限与工具预算分属两个模块，且数值互斥 | `agent_engine.py:32`（32）、`:35`（128）、`agent_tools.py:31`（18） |
| 工具集按黑名单裁剪，新增工具默认进入交互链路 | `agent_engine.py:43` `CONVERSATION_EXCLUDED_TOOLS = {"submit_report","python_analyze"}` |
| 两套 agent 构造器 | `agent_engine.py:217` `create_agent(...)`、`report_session.py:72` `create_deep_agent(...)` |
| 预算计数写在工具闭包内部 | `agent_tools.py:183-214` |
| 存在一条自动批准门禁的旧路径 | `agent_engine.py:163` `run_agent_report`（自注 NOT for production） |
| 八份在建变更正在修改上述只读文件 | `openspec list --json` + 变更内文件引用；`auto-030` 占用六份 |

### 工作区状态（写入前必须知晓）

- 当前分支为 `change/auto-030-analysis-capability-triggers`，**本变更尚无独立分支**；按 `AGENTS.md` 每个 Change 一个 `change/<change-id>` 分支，需在实现前新建并迁入本目录。
- 未提交改动：`routing/intent.py`、`tests/test_intent.py`（上一次路由重构，未提交）、`docs/`（未跟踪）、本变更目录（未跟踪）。这些不属于本变更的实现范围，实现开始前须由 Owner 决定归属。

### 不可用检查（明确未完成）

- 全量 `unittest discover -s tests` 未跑完（超过 100 秒被终止），沙箱子进程类用例状态未知。
- 已通过：`tests.test_intent` + `tests.test_api` + `tests.test_frontend_contract` + `tests.test_agent_workflow` 共 87 项。
- `create_agent` 是否支持与 `create_deep_agent` 等价的 middleware/interrupt 装配：**未验证**（见 Open Questions）。

## Goals / Non-Goals

**Goals:**

1. 上下文只有一份 schema，字段集合不再漂移。
2. 只有一处能构造 agent，预算/递归/中间件/技能/工具白名单成为配置数据。
3. `verified_steps` 到输出的派生只有一条路径，字段映射集中。
4. 上述等价性可被**机械验证**，不依赖人工 review。
5. 全程以新增文件实现，对八份在建变更零文件冲突。

**Non-Goals:**

1. 接线：不改 `app.py` / `agent_engine.py` / `report_session.py` / `agent_tools.py` 的任何行为（设计级边界，非范围复述）。
2. 不统一 `create_agent` 与 `create_deep_agent`（该决策需要独立的 spike 结论）。
3. 不为新内核增加任何重试、缓存、并发、追踪能力——先证明等价，再谈增强。
4. 不改变"失败即失败"的语义，也不引入新的降级链。

## Decisions

### D1 用 `RunContext` 取代散落 dict

**选择**：`@dataclass` 定义唯一上下文，字段固定，写入必须经过受控方法（`spend_tool_call`、`record_step`）。

**理由**：现状两份 dict 的键集合已经漂移（一支有 `report_hits`，另一支有 `progress`/`interactive`），这是"漏改一处就静默失效"的根源。dataclass 让未知字段在构造期就报错，而不是运行时被 `dict.get` 吞掉。

**替代方案**：`TypedDict`（运行时不校验，达不到目的）；pydantic（引入依赖，且本项目当前无此依赖）。

### D2 `Profile` 是配置数据，不是子类

**选择**：`Profile` 为 frozen dataclass，`interactive` / `deliverable` 是两份实例，导入期校验自洽性。

**理由**：两个子类会把"差异"变成"代码差异"，新增第三个 profile 就要写新类；配置数据让差异可被穷举、可被测试逐字段断言。

**替代方案**：继承 + 覆写方法（差异藏在继承链里，比现状更难看清）。

### D3 `builder.build_runner(profile, ctx)` 是唯一装配入口

**选择**：任何构造 agent 的代码只能出现在 `kernel/builder.py`。

**理由**：约束 C1 可以用一行源码断言守住（`create_agent` 只允许出现在这一个文件），这是"防回退"的最低成本手段。

**替代方案**：约定式（靠 code review 维持）——历史上已经失效，现状就有两处。

### D4 `Runner.run` / `Runner.resume` → `Outcome` 统一状态机

**选择**：三条终态 `done / awaiting_review / failed`，交互与交付共用；`awaiting_review` 只可能由 profile 声明了 `requires_approval` 时出现。

**理由**：现状交互链路返回 dict、交付链路返回 outcome dict，调用方各自解析；统一后"是否等人"成为状态而不是约定。

**替代方案**：保留两种返回值（调用方继续分叉，与目标矛盾）。

### D5 `derive.py` 收口 `verified_steps` 的两条派生路径

**选择**：`to_answer_view` 与 `to_report_view` 都在 `derive.py`，字段映射（含 `negative_share → negativeShare`）只允许出现在此。

**理由**：这是当前最隐蔽的隐式契约——交互链路里那段驼峰映射如果与报告侧不一致，用户会看到同一个指标两个名字。

### D6 工具按 capability 登记，profile 用白名单引用

**选择**：`registry.py` 登记 `{tool_id: capability}`，profile 声明 `tools: frozenset[str]`。

**理由**：现状黑名单导致 `submit_analysis_plan` 仍暴露给交互链路（该工具在无 interrupt 的链路上语义失效）。白名单下"新增工具默认不可见"，安全性来自默认值而不是记忆。

### D7 预算与递归必须自洽，导入期校验

**选择**：校验 `tool_calls * 2 + 4 <= recursion_limit`，不满足直接抛错。

**理由**：现状 `18` 与 `32` 互相矛盾，名义预算永远达不到。这类矛盾必须在启动期暴露，不能靠人记住两个数字。

### D8 分两期，Phase 1 只建不接

**选择**：本变更只产出内核与验证手段，生产路径不引用内核。

**理由**：`agent_engine.py` 等六份文件正被 `auto-030` 修改；同时改同一文件会产生语义合并冲突。新增文件是唯一零冲突路径。

**替代方案**：先合后在旧文件上重写——冲突面覆盖整函数，且无法在不破坏在建变更的前提下回滚。

### D9 等价性用录制 fixture 的 golden master，不调真模型

**选择**：录制"输入 + 模型响应"为 fixture，回放旧实现与新内核，逐字段比对。

**理由**：模型非确定性会让任何直接比对失效，这是等价性验证最常见的失败原因。

## 接口定义与数据流

```
TurnRequest
   |
   v
+----------------------+     +---------------------------+
| kernel.builder       |---->| Runner(profile, ctx)      |
| build_runner(profile)|     |  .run(req)                |
+----------------------+     |  .resume(decision)        |
                             +------------+--------------+
                                          |
                        +-----------------+-----------------+
                        v                                   v
                 +--------------+                   +---------------+
                 | agent 装配    |                   | 预算/账本      |
                 | (两种库均可)  |                   | kernel.context |
                 +------+-------+                   +-------+-------+
                        |                                   |
                        v                                   v
                 +-------------------------------+  +------------------+
                 | Outcome                       |  | StepLedger       |
                 |  status: done/awaiting/failed |  | verified_steps   |
                 |  view: Answer|Report|None     |  +------------------+
                 |  pending: PlanCard|None       |          |
                 |  error, metrics               |          v
                 +-------------------------------+  +------------------+
                                                    | kernel.derive    |
                                                    | to_answer_view   |
                                                    | to_report_view   |
                                                    +------------------+
```

```python
# kernel/context.py
@dataclass
class Budget:
    tool_calls: int = 18
    errors: int = 6
    submits: int = 4
    code_failures: int = 3
    recursion_limit: int = 128

@dataclass
class RunContext:
    budget: Budget
    ledger: StepLedger
    submissions: list[Submission] = field(default_factory=list)
    evidence_ids: set[str] = field(default_factory=set)
    progress: ProgressFn | None = None

    def spend_tool_call(self) -> None: ...   # 越界抛 BudgetExhausted
    def spend_error(self) -> None: ...
    def record_step(self, step: Step) -> None: ...   # 唯一落账入口

# kernel/profile.py
@dataclass(frozen=True)
class Profile:
    name: Literal["interactive", "deliverable"]
    tools: frozenset[str]
    budget: Budget
    middleware: tuple[str, ...]
    skills: tuple[str, ...]
    artifact: Literal["answer", "report"]
    failure: Literal["retryable", "terminal"]
    timeout_s: int

    @property
    def requires_approval(self) -> bool: ...

# kernel/builder.py
def build_runner(profile: Profile, ctx: RunContext) -> Runner: ...

# kernel/runner.py
@dataclass(frozen=True)
class Outcome:
    status: Literal["done", "awaiting_review", "failed"]
    view: AnswerView | ReportView | None
    pending: PlanCard | None
    error: KernelError | None
    metrics: RunMetrics

class Runner(Protocol):
    def run(self, req: TurnRequest) -> Outcome: ...
    def resume(self, decision: Decision) -> Outcome: ...

# kernel/derive.py
def to_answer_view(ctx: RunContext, final_text: str) -> AnswerView: ...
def to_report_view(ctx: RunContext, state: Mapping[str, Any]) -> ReportView: ...

# kernel/registry.py
TOOLS: Mapping[str, ToolCapability]   # tool_id -> capability
def tools_for(profile: Profile) -> tuple[Tool, ...]: ...

# routing/gates.py
def check_input(text: str) -> GateResult: ...   # ok / rejected(reason)
```

## 模块划分与文件所有权

| 文件 | 本变更 | 说明 |
|---|---|---|
| `kernel/__init__.py` | 新增 | 导出公开接口 |
| `kernel/context.py` | 新增 | RunContext / Budget / StepLedger |
| `kernel/profile.py` | 新增 | Profile 与两份实例、自洽校验 |
| `kernel/builder.py` | 新增 | 唯一 agent 装配入口 |
| `kernel/runner.py` | 新增 | run/resume、Outcome |
| `kernel/derive.py` | 新增 | 派生层 |
| `kernel/registry.py` | 新增 | 工具能力登记 |
| `routing/gates.py` | 新增 | 输入硬门 |
| `tests/test_kernel_*.py` | 新增 | 契约与等价测试 |
| `agent_engine.py` | **只读** | 由 `auto-030`/`028`/`025` 持有 |
| `report_session.py` | **只读** | 由 `auto-030`/`033` 持有 |
| `agent_tools.py` | **只读** | 由 `auto-030`/`032`/`031`/`028`/`025` 持有 |
| `app.py` | **只读** | 由 `auto-030`/`032`/`031`/`034`/`027`/`025` 持有 |
| `prompts.py` | **只读** | 由 `auto-030`/`033`/`032` 持有 |
| `jobs.py` | **只读** | 由 `auto-030`/`028` 持有 |

**冲突处理规则**（写入 design 以约束并行期行为）：

1. 只读文件若在建变更期间被修改，内核以**适配读取**方式跟随（不复制其常量），常量差异由 profile 单点承担。
2. 若在建变更调整了预算或递归数值，本变更不改代码，只更新 profile 默认值并重跑自洽校验。
3. 任何需要修改只读文件的动作，必须暂停该文件相关工作、由两个变更的 Owner 协商后单独立项（Phase 2）。
4. 一个物理文件同一时刻只有一个 writer。

## 关键约束

| 编号 | 约束 | 机械检查方式 |
|---|---|---|
| C1 | `create_agent` / `create_deep_agent` 只允许出现在 `kernel/builder.py` | 源码扫描断言（测试内 grep，排除既有老文件基线） |
| C2 | `RunContext` 不接受未知字段 | 构造 `RunContext(unknown=1)` 断言 `TypeError` |
| C3 | 工具必须先在 `registry` 登记能力，未登记不得进入任何 profile | registry 全量测试：profile 引用的每个 tool_id 必须已登记 |
| C4 | `budget.tool_calls * 2 + 4 <= budget.recursion_limit` | profile 导入期校验，非法抛错；两份内置 profile 必须通过 |
| C5 | `verified_steps` 只能经 `record_step` 写入；`negativeShare` 映射只在 `derive.py` | 源码扫描断言 |
| C6 | `deliverable` 失败必须 `status=failed` 且 `view is None`，不得降级 | 状态机单测 |
| C7 | `interactive` 不得产出报告产物（D8 现状语义） | 单测：`artifact=answer` 时 `to_report_view` 不被调用 |
| C8 | 提示词与工具 docstring 逐字节不变 | 重构前后 `git diff` 为空 |

## 验证策略

| 编号 | 手段 | 判定 |
|---|---|---|
| V1 | golden master 回放：同一 fixture 分别驱动旧实现与新内核，比对 `answer` 全文、`stats`（含顺序）、`evidence`、`citations`、`warnings`、工具调用序列 | 全等；差异清单必须为空 |
| V2 | 源码结构断言（C1/C5） | 断言通过 |
| V3 | 配置自洽单测（C3/C4） | 两份内置 profile 通过 |
| V4 | 状态机穷举：`done` / `awaiting_review` / `resume→done` / `resume→rejected→failed` / 异常→`failed` | 五条路径全覆盖 |
| V5 | 现有回归：`test_api`、`test_frontend_contract`、`test_agent_workflow`、`test_intent` | 87 项全绿（基线已录） |
| V6 | 提示词/工具描述 diff（C8） | 空 |

**等价性的边界必须写明**：V1 只能证明"在录制 fixture 覆盖的输入上等价"。fixture 覆盖率是这套方法的已知上限，因此本变更不宣称"整体行为不变"，只宣称"**在已录制场景上等价，且未触碰生产路径**"。

## Migration Plan

Phase 1（本变更，可独立回滚）：

1. 录基线：录制器把输入与模型响应存为 fixture，先用现有测试问题集生成第一版。
2. 建 `kernel/context.py` 与 `profile.py`（含 C4 校验）。
3. 建 `registry.py`（登记现有 9 个工具的能力标签）。
4. 建 `builder.py` 与 `runner.py`（内部仍可分别调用两种构造库）。
5. 建 `derive.py`，把两条派生路径收口。
6. 建 `routing/gates.py`。
7. 写测试 V1–V6。
8. 产出等价报告（附 fixture 清单与差异清单）。

**回滚**：Phase 1 全部为新增文件，删除 `kernel/`、`gates.py` 与新增测试即回到起点；生产路径从未引用，无需数据或配置回滚。

Phase 2（不在本变更内，需单独立项）：

- 老文件改薄壳转调、删除 `run_agent_report` 旧路径、撤掉黑名单裁剪、决定 `routing/intent.py` 去留、决定是否统一构造库。
- 前置条件：`auto-030` 交付合并 + Owner 验收；否则仍是同文件并行。

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| fixture 覆盖不足，等价性结论过强 | 结论只覆盖已录制场景；报告里列出未覆盖类别；Phase 2 前再补一轮真实问题集 |
| 影子期间两套逻辑并存，双份维护 | 明确期限：Phase 1 结束时若未立项 Phase 2，则内核标记为"实验模块"并停止扩展 |
| `create_agent` 的 middleware/interrupt 能力未必等价于 DeepAgents（**未验证假设**） | Phase 1 的 builder 保留双实现分支；等价性只在 Phase 2 立项前用 spike 验证 |
| profile 默认值与在建变更调整的常量冲突 | 常量只从 profile 读取；在建变更改数值时自动触发 C4 校验失败，暴露而非静默 |
| 当前工作区已有未提交改动（`routing/intent.py`、`tests/test_intent.py`、`docs/`），且不在本变更分支上 | 实现开始前必须新建 `change/auto-038-*` 分支并明确这些改动的归属，否则等价基线不可信 |
| 内核与 `agent_tools.py` 预算语义可能重复实现 | Phase 1 只做"读取现有计数"的适配，不重写计数规则；重写留给 Phase 2 |

## Open Questions

1. **Phase 2 是否统一构造库**（`create_agent` vs `create_deep_agent`）：需要 spike 结论，不影响本变更的接口定义。
2. **fixture 来源**：先用现有测试问题集（快），还是由 Owner 提供真实使用样本（更真实）。默认前者，后者可在 V1 中增量补充。
3. **`routing/intent.py` 去留**：本变更不动它；是否在 Phase 2 降级为离线工具，由 Owner 决定。
4. **内核包位置**：放在 `08_semantic_services/kernel/`（与现有模块同包，导入路径不变）还是独立顶层包。默认前者，理由是避免跨包导入影响现有启动方式。

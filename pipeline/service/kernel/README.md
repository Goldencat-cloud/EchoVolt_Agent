# kernel —— 统一 agent 内核（Phase 3：两条链路均已接线）

本目录是 `auto-038-agent-kernel-unification` 的产物。两条业务链路都已接线：

- **交互链路**（`auto-040-agent-kernel-wiring`）：`agent_engine._run_agent_conversation`
  用 `RunContext` 承载状态、用 `INTERACTIVE` 过滤工具、用 `to_answer_view` 派生响应。
- **交付链路**（`auto-041-agent-report-kernel-wiring`）：`ReportSession` 持 `RunContext`，
  工具经 `tool_context()` 桥接，`report_outcome` 走 `to_report_view`。

等价性证据：`tests/test_kernel_equivalence.py`（回放接线前录制的响应）、
`tests/test_kernel_wiring.py`（键覆盖、白名单、实时/快照分支、筛选语义、报告入参兼容），
以及 `tests/test_kernel_derive.py` 的视图字段对照。

**尚未统一**：`app.py` 的输入硬门（`routing/gates.py` 仍未接入）；工具预算的
"双来源"（图递归上限 vs `Budget`）留待后续变更。

> 关于 fixture 基准的时效性：`tests/fixtures/kernel/*.json` 的 `expected` 全部录制
> 于接线之前。`kernel_fixture.old_implementation` 在接线后驱动的是当前实现，只能
> 用于生成"当前实现"的录制，不能再用来补录旧实现基准。

## 1. 上下文 schema（`context.py`）

`RunContext` 是运行期状态的唯一来源。字段是两个既有实现上下文键的并集：

| 字段 | 类型 | 说明 |
|---|---|---|
| `budget` | `Budget` | 工具/错误/提交/代码失败/递归五类上限 |
| `ledger` | `StepLedger` | `verified_steps` 的唯一容器 |
| `submissions` | `list[dict]` | 提交产物记录 |
| `evidence_ids` | `set[str]` | 本轮引用的证据 ID（旧名 `evidence_claim_ids`） |
| `report_hits` | `list[dict]` | 交互链路检索到的报告命中 |
| `code_failures` | `dict[str,int]` | 沙箱失败计数（按原因） |
| `plan` | `dict \| None` | 已提交的分析计划 |
| `progress` | `Callable \| None` | 进度回调 |
| `live_context` | `Any` | 实时数据上下文（可选） |
| `interactive` | `bool` | 是否交互姿态 |
| `accepted_submission` | `bool` | 是否已有被接受的提交 |
| `submit_attempts` | `int` | 提交尝试次数 |
| `tool_errors` | `int` | 工具错误计数 |
| `successful_tool_calls` | `int` | 成功工具调用计数 |
| `gate_rejections` | `int` | 大纲闸门拒绝次数（`auto-041` 补） |
| `outline_approved` | `bool` | 大纲是否已获人工批准（交付链路读取） |
| `outline_decision` | `dict \| None` | 审批记录：动作类型与时间 |
| `extras` | `dict` | 迁移期辅助键白名单（见下） |

**新增字段必须在这里声明**：`RunContext` 是 dataclass，传入未声明的关键字会在
构造期抛 `TypeError`（约束 C2）。不允许再向某个 dict 里 `setdefault` 新键。

写入只走受控方法：`spend_tool_call` / `spend_error` / `spend_submit` /
`spend_code_failure` / `record_step` / `add_evidence`。越界抛 `BudgetExhausted`。

### 迁移期字典桥

`ctx.tool_context()` 返回一个 `MutableMapping`，让既有的 9 个工具（它们按 dict
读写上下文）无需修改即可继续工作。桥的写入会落回同一个 `RunContext`，同时把
`verified_steps` 的 append 转发到同一个账本。

允许透传的辅助键只有 `live_evidence`、`delivery_spec`、`detailed_notes`
（见 `EXTRA_KEYS`）。需要新的辅助键时，先加进这个白名单——**不要绕过它**。

## 2. 运行姿态（`profile.py`）

`Profile` 是 frozen dataclass，两份内置实例：

| 字段 | `interactive` | `deliverable` |
|---|---|---|
| 工具 | 读 + 算 + 计划，**排除** `python_analyze` / `submit_report` | 全部 9 个 |
| 工具预算 | 14（= (32-4)/2，与现状递归上限等价） | 18 |
| 错误预算 | 6 | 6 |
| 提交预算 | 4 | 4 |
| 递归上限 | 32 | 128 |
| 产物 | `answer` | `report` |
| 失败语义 | `retryable` | `terminal` |
| 中间件 | 无 | `hitl.plan` |
| 技能 | 无 | `deep-analysis` |

导入期校验（`Profile.__post_init__`）：

1. 白名单里的每个工具都必须已在 `registry` 登记（C3）；
2. `tool_calls * 2 + 4 <= recursion_limit`（C4）；
3. `artifact=report` 必须声明 `hitl.plan`；`artifact=answer` 不得声明闸门。

新增第三个姿态的检查清单：登记所需工具 → 写 `Profile` 实例 → 断言 C3/C4 通过
→ 补一条状态机测试。不需要写子类。

## 3. 工具登记（`registry.py`）

9 个工具按能力分四类：`read`（快照/语料）、`compute`（方法/聚合/沙箱）、
`plan`（提交计划，触发闸门）、`submit`（产出可发布物）。

**新增工具的流程**：先在 `TOOLS` 登记能力标签，**再**显式加入某个 profile 的
白名单。没登记的工具有两个后果：profile 引用它会直接报错；不引用它则任何
profile 都看不到它（默认不可见，这是安全默认值）。

## 4. 装配与状态机（`builder.py` / `runner.py`）

```
build_runner(profile, ctx) ──> KernelRunner(profile, ctx, agent, view_factory)
                                   │
                     run(TurnRequest)┌┴┐ resume(Decision)
                                     v  v
                         Outcome(status=done | awaiting_review | failed)
```

| 路径 | 触发条件 | 结果 |
|---|---|---|
| 正常完成 | agent 返回无异常、状态缺省 | `done` + `view` |
| 停在闸门 | agent 返回 `status=awaiting_review` 且 profile 有声明的闸门 | `awaiting_review` + `pending` |
| 契约违背 | agent 要求停在闸门但 profile 无闸门 | `failed` |
| 批准/编辑 | `resume(approve|edit)` | 再次 invoke → `done` / `failed` |
| 驳回 | `resume(reject)` | `failed`（不调用 agent） |
| 异常 | agent 抛错或视图派生失败 | `failed`（`terminal` profile 不降级） |

**约束**：`deliverable` 失败时 `view is None`，不得退化为"给个粗略答案"（C6）。
`create_agent` / `create_deep_agent` 只允许出现在 `builder.py`（C1）。

## 5. 派生层命名约定（`derive.py`）

`verified_steps` → 对外视图的字段映射只允许出现在 `derive.py`（C5）。

- `negative_share` → `negativeShare`
- `negative` → `negative_claims`

**反例（禁止）**：在视图组装之外的地方写 `item["negativeShare"] = ...`，或在
控制器里补 `citations` 形状。同一个指标出现两个名字，前端就会有两套渲染分支。

`to_answer_view` 与 `to_report_view` 都接受注入协作者（`sanitizer`、
`citation_parser`、`charts`、`evidence_index`），本模块不重复实现它们的查询逻辑。

## 6. 输入硬门（`routing/gates.py`）

阈值与代码常量同源：`MAX_INPUT_CHARS = 500`。判定顺序：空 → 超长 → 注入特征。

拒绝码 `empty` / `too_long` / `injection` 直接可回给用户。注入规则只匹配
"要求模型放弃自身约束"的句式；宁可漏判，也不能误判正常提问。

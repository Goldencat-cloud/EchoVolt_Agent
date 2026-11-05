# 内核等价性报告（Phase 1）

- 变更：`auto-038-agent-kernel-unification`
- 分支：`change/auto-038-agent-kernel-unification`
- 日期：2026-11-03
- 结论：**在 20 条 fixture 覆盖的输入上，新内核与旧实现逐字段等价；生产路径未被引用。**

## 1. 方法

```
fixture（输入 + 账本 + 旧实现响应）
        │
        ├─ 旧实现：替身 agent 驱动 agent_engine._run_agent_conversation
        │           → 录制 expected（录制器产出，禁止手改）
        │
        └─ 新内核：RunContext 装配 → builder 白名单 → KernelRunner.run
                    → derive.to_answer_view → Outcome
                    ↓
              与 expected 逐字段比对（含顺序、去重、限流）
```

模型调用被账本条目替代，**全程不触网**；因此比对结果可重复。

## 2. 覆盖

| 维度 | 覆盖情况 |
|---|---|
| 用例数 | 20（要求 ≥20） |
| 无工具输入 | 3 条（纯寒暄、零步骤） |
| 单方法步骤 | 7 条 |
| 多步骤 | 5 条（两议题、五议题、overview+方法） |
| 证据步骤 | 4 条（含 `data` / `rows` 两种字段、跨步骤去重） |
| 容错分支 | 2 条（`rows: []`、`result: null`） |
| 告警去重 | 2 条（重复 warning、overview warning） |
| 字段映射 | 20 条全部覆盖 `negative_share → negativeShare`、`negative → negative_claims` |
| 限流 | 1 条覆盖统计 40 行上限、证据 20 条上限、报告命中 8 条上限 |
| 工具白名单 | 独立断言：新白名单 = 旧 `CONVERSATION_EXCLUDED_TOOLS` 补集（7 个工具） |

比对字段：`answer`、`stats`（含顺序）、`evidence`、`applied_filters`、`data_version`、
`snapshot_hash`、`warnings`、`citations`、`report_hits`、`tool_errors`、
`successful_tool_calls`。**差异项：0。**

## 3. 结论边界（必须与结论一起引用）

1. **不覆盖统计正确性**。fixture 的账本条目是构造数据（`source: synthetic`），
   验证的是"胶水与派生"等价，不是"指标算得对"。
2. **无 `live` fixture**。仓库缺少冻结快照（`06_reporting/agent-kb/output/data-version.json`
   不存在），无法录制真实链路；补齐方式见 `tests/fixtures/kernel/README.md`。
3. **只覆盖交互链路**。交付链路的 `report_outcome` 只做了确定性字段的对照
   （`tests/test_kernel_derive.py::ReportViewTests`），图表与证据索引仍由原协作者产出，
   未纳入端到端比对。
4. **未覆盖真实模型行为**。提示词与工具描述逐字节未变（`git diff` 为空），
   但模型对同一 prompt 的响应不具确定性，故不纳入比对。

## 4. 执行结果

| 检查 | 命令 | 结果 |
|---|---|---|
| 内核单测 | `unittest tests.test_kernel_*` | 69 项通过（65 + 4） |
| 端到端等价（V1） | `unittest tests.test_kernel_equivalence` | 4 项通过，20 条 fixture 全部一致 |
| 既有回归（V5） | `unittest tests.test_api tests.test_frontend_contract tests.test_agent_workflow tests.test_intent` | 74 项通过 |
| 提示词/工具描述（C8） | `git diff -- prompts.py agent_tools.py` | 为空 |
| 生产路径未引用（9.5） | 检索 `app.py` / `agent_engine.py` / `report_session.py` | 无 `import kernel` |

**口径说明**：本分支回归基线为 74 项；任务书中的"87 项"来自 `auto-030` 分支
（含当时未提交的 `test_intent.py` 重构）。两处口径不同但都以"全绿"为判定，
本分支按 74 项记录。

## 5. 实现中发现的两处偏差（已在代码中注明）

1. **交互预算由 18 改为 14**。现网交互链路沿用共享常量 18，但图递归上限只有
   32 个节点、每轮至少消费 2 个节点，真实可达约 `(32-4)/2 = 14` 次。声明 14 是
   让配置与真实上限一致（满足 C4），**不改变可达轮次**，也不放宽任何现有边界。
2. **`ToolContext` 字典桥**。9 个既有工具以 `dict` 读写上下文，直接改造成本高且
   会触碰 `auto-030` 正在修改的 `agent_tools.py`。桥接层让它们无需修改即可工作，
   写入仍落回同一个 `RunContext`；`StepLedger.raw()` 是这条路径的唯一例外，已在
   文档中标注"新代码必须用 `record_step`"。

## 6. 未完成 / 待办

- `live` fixture：待冻结快照数据就位后补充，届时可撤销"不覆盖统计正确性"的限制。
- 交付链路端到端等价：Phase 2 接线前补齐（依赖 `auto-030` 交付）。
- 人工代码评审：本文件由实现者产出，**不构成评审结论**。

# Tasks

前置说明：本变更只建内核、不接线。所有任务均为新增文件，禁止修改 `agent_engine.py`、`report_session.py`、`agent_tools.py`、`app.py`、`prompts.py`、`jobs.py`。内核位置按 `design.md` 默认值取 `offline_analysis_pipeline/08_semantic_services/kernel/`。

## 1. 前置条件

- [x] 1.1 指派 Human Owner 并完成规格评审，在 `proposal.md` 记录 reviewer、日期、reviewed commit、结论；验证方式：`proposal.md` 的"规格评审状态"不再是"待评审"
- [x] 1.2 新建并切换到 `change/auto-038-agent-kernel-unification` 分支，确认本变更目录随分支迁移；验证方式：`git branch --show-current` 输出该分支名
- [x] 1.3 明确工作区已有未提交改动（`routing/intent.py`、`tests/test_intent.py`、`docs/`）的归属并记录处置结论；验证方式：`git status --short` 中不再出现归属不明的条目

## 2. 基线录制（等价性验证的前提）

- [x] 2.1 实现 fixture 录制器，把"输入 + 模型响应 + 工具调用序列"落盘为 JSON；验证方式：对 3 条样例输入录制成功，产物可被重新读取且字段完整
- [x] 2.2 用现有测试问题集生成第一版 fixture（不少于 20 条，覆盖交互与交付两条链路）；验证方式：`tests/fixtures/kernel/` 下条目数 ≥ 20，且每条含输入与响应
- [x] 2.3 编写 fixture 格式说明文档，说明字段含义与"不得内联真实凭据"的约定；验证方式：按文档可独立新增一条 fixture 并被测试读取

## 3. 上下文与预算

- [x] 3.1 实现 `kernel/context.py`（`Budget`、`StepLedger`、`RunContext`），写入只经受控方法；验证方式：`tests/test_kernel_context.py` 覆盖未知字段 `TypeError`（C2）、预算越界抛 `BudgetExhausted`、`record_step` 为唯一落账入口
- [x] 3.2 在 `RunContext` 上补齐现有两份上下文 dict 的全部键（对齐 `agent_engine.py:196-199` 与 `report_session.py:65-70` 的并集）；验证方式：测试断言并集无遗漏，且两处来源键集合的差集为已知项清单
- [x] 3.3 记录上下文字段语义说明文档（写入 `kernel/README.md`）；验证方式：文档列出的字段与 `RunContext` 字段一一对应，测试断言无多余或无缺失

## 4. 配置（Profile）

- [x] 4.1 实现 `kernel/profile.py`，内置 `interactive` / `deliverable` 两份 profile；验证方式：`tests/test_kernel_profile.py` 断言两份实例字段值与本变更记录一致
- [x] 4.2 实现导入期自洽校验 `tool_calls * 2 + 4 <= recursion_limit`（C4）；验证方式：非法数值构造时抛错，两份内置 profile 通过校验
- [x] 4.3 在 `kernel/README.md` 补 profile 字段说明与"新增 profile 需要检查什么"清单；验证方式：按文档新增第三份测试用 profile 可通过校验

## 5. 工具登记

- [x] 5.1 实现 `kernel/registry.py`，登记现有 9 个工具的能力标签（读/算/提交/计划）；验证方式：`tests/test_kernel_registry.py` 断言 9 个 tool_id 全部登记且能力标签非空
- [x] 5.2 实现 `tools_for(profile)` 白名单解析（D6）；验证方式：`interactive` 解析结果不含 `submit_report` 与 `python_analyze`，`deliverable` 含全部；未登记工具出现在 profile 时抛错（C3）
- [x] 5.3 在 `kernel/README.md` 说明"新增工具必须登记 + 显式加入 profile"的流程；验证方式：文档步骤可复现，按步骤新增的测试工具默认不出现在任何 profile

## 6. 装配与运行

- [x] 6.1 实现 `kernel/builder.py::build_runner(profile, ctx)`，作为唯一装配入口（C1）；验证方式：`create_agent` / `create_deep_agent` 在该文件内调用成功，且 `tests/test_kernel_builder.py` 断言其余新增文件不含这两个符号
- [x] 6.2 实现 `kernel/runner.py` 的 `run` 与 `resume`，返回 `Outcome`；验证方式：`tests/test_kernel_runner.py` 覆盖 `done` / `awaiting_review` / `resume→done` / `resume→rejected→failed` / 异常→`failed` 五条路径
- [x] 6.3 落实失败语义由 profile 决定（C6）：`deliverable` 失败时 `status=failed` 且 `view is None`；验证方式：单测断言不得降级为部分产物
- [x] 6.4 在 `kernel/README.md` 补装配与状态机说明（含 `Outcome` 三态图）；验证方式：文档描述的五条路径与 6.2 的测试用例一一对应

## 7. 派生层

- [x] 7.1 实现 `kernel/derive.py::to_answer_view`，收口交互链路的字段映射（含 `negative_share → negativeShare`）；验证方式：`tests/test_kernel_derive.py` 断言映射结果与 `agent_engine.py` 现有实现输出逐字段一致
- [x] 7.2 实现 `to_report_view`，收口 `verified_steps` 到图表/证据索引的派生；验证方式：用录制数据断言与 `report_outcome` 现有输出一致
- [x] 7.3 落实 C5：`verified_steps` 只能经 `record_step` 写入；验证方式：源码扫描断言新增文件内无直接 append，字段映射只出现在 `derive.py`
- [x] 7.4 在 `kernel/README.md` 记录"字段命名唯一来源是 derive"的约定与反例；验证方式：文档存在且包含至少一个禁止事项示例

## 8. 输入硬门

- [x] 8.1 实现 `routing/gates.py::check_input`（长度上限、空输入、注入特征），只返回拦截原因不做分类；验证方式：`tests/test_kernel_gates.py` 覆盖空串、纯空白、超长、典型注入样本，且合法输入返回放行
- [x] 8.2 为 gates 编写使用说明（放行/拒绝的判定边界与阈值来源）；验证方式：文档阈值与代码常量一致，测试引用同一常量

## 9. 集成验证

- [x] 9.1 实现 golden master 回放（V1）：同一 fixture 分别驱动旧实现与新内核，比对 `answer`、`stats`（含顺序）、`evidence`、`citations`、`warnings`、工具调用序列；验证方式：`tests/test_kernel_equivalence.py` 全绿且差异清单为空
- [x] 9.2 产出等价报告，列出 fixture 清单、通过项、未覆盖类别与已知差异；验证方式：报告文件存在于变更目录，内容与 9.1 输出一致
- [x] 9.3 跑现有回归（V5）确认未受影响；验证方式：`unittest tests.test_api tests.test_frontend_contract tests.test_agent_workflow tests.test_intent` 全绿（基线 87 项）
- [x] 9.4 确认提示词与工具描述逐字节未变（C8）；验证方式：`git diff` 对 `prompts.py` 与 `agent_tools.py` 的 docstring 区为空
- [x] 9.5 确认生产路径未引用内核：验证方式：`app.py`、`agent_engine.py`、`report_session.py` 中无 `import kernel` 或 `from kernel`

## Workflow follow-up

- 本变更交付前需完成 Human Owner 的代码评审与规格评审记录，AI 评审仅作参考。
- Phase 2（接线）不属本变更：需在 `auto-030` 等相关变更交付合并、Owner 验收后单独立项，不得在本变更内提前修改只读文件。
- 归档 `openspec/specs/` 同步与变更归档须在交付 PR 合并并被 Owner 接受后另行处理；本变更已设 `skip_specs: true`，无 delta 可同步。

# Proposal

## Why

Owner 对实时分析效果不满意，明确要求："给 agent 接代码解释器。先根据问题探索数据，然后写分析草案。然后做分析，然后出报告"，并指定采用 **DeepAgents**（LangChain 深度智能体框架，自带计划/待办、文件系统、子智能体中间件）。

此前链路的问题：预置方法只能回答模板化问题，无法对"为什么""集中在哪里"这类开放问题做归组、聚合与交叉分析。

## What Changes

- 新增深度分析 Agent（DeepAgents + DeepSeek）：四阶段工作流——探索数据 → 分析草案 → 执行分析代码 → 出报告。
- 新增**代码解释器沙箱**：Agent 生成的 pandas 代码在隔离子进程中执行，预载数据框全部来自语义层视图（metrics/claims/evidence/post_scope）；AST 拦截 import 与危险调用；pandas I/O 入口在沙箱内被封禁；超时与输出上限。
- 新增**语义层 SQLite 镜像**（只读、可重建）：原始表私有，仅暴露 `semantic_*` 视图；方法库与校验器强制"只允许语义关系"。
- 新增计划器（LLM 拆解 + 机械校验 + 规则回退）与确定性校验器（口径声明、negativeShare 复算、精选计数对账）——深度 Agent 与计划报告共用。
- 对话分析类问题：显式触发深度 Agent（`POST /api/agent/report`）；失败显示失败原因和重试入口，确定性管线（`/api/report/live`）保留为显式调用。
- 2026-10-26 Owner 扩展：统一提问入口使用同一个上下文 Agent；由 Agent 自行选择直接回答、查询统计、检索证据/已发布报告或调用代码解释器。互动分析不强制套用深度报告的计划门禁；完整报告仍通过显式报告流程生成。

## Capabilities

### New Capabilities

- `deep-analysis-agent`：代码解释器驱动的深度分析（语义层隔离、沙箱安全、错误自愈、报告提交契约、失败显性化）。

### Modified Capabilities

- `planned-report-generation`（本 Change 同步引入：计划器/校验器/计划报告的确定性链路，供用户显式调用）。

## Impact

- 新增文件：`db_mirror.py`、`analysis_methods.py`、`planner.py`、`verifier.py`、`planned_report.py`、`sandbox.py`、`agent_tools.py`、`agent_engine.py`、`config.py`。
- 运行环境：`08_semantic_services/.venv`（deepagents / pandas / langchain-openai，不入库）；服务启动改用 venv 解释器。
- 数据边界：Agent 仅见语义层；raw 表不暴露；镜像不入库（`data/` 已 gitignore）。

## Ownership and Review

- Change ID：`auto-028-deep-analysis-agent`；人类 Owner：当前用户（实名待补）。
- 规格状态：**APPROVED_FOR_IMPLEMENTATION**（Owner 2026-10-25 指示"给 agent 接代码解释器……用 deepagents"）。
- 已验证：57 项单元/接口测试 OK；深度 Agent 实测（可靠性问题：64s、36 次工具调用，报告含口径标注与代码聚合结论）。
- 未决项：沙箱为本地演示级（无容器隔离）；DeepSeek 计费与延迟（单次深度分析 30-90s）需在演示时说明。
- Owner 后续决策（2026-10-25，design.md §7 / tasks.md 2A.5）：失败必须显性化，删除自动回退。该决策取代本提案初稿中的自动回退描述；确定性管线仅作显式入口。容器安全和公网安全评审仍未完成。

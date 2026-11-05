# Proposal

## Change ID 与责任

- **Change ID**：`auto-042-architecture-consolidation`
- **人类 Owner**：待指派（pending assignment，按 CONTRIBUTING.md「一项 Change 一名 Owner」）
- **开发分支**：`change/auto-042-architecture-consolidation`（尚未创建；当前工作区位于 `change/auto-041-agent-report-kernel-wiring`）
- **关联 Issue/PR**：待创建
- **规格审查**：pending（尚未发生 GPT/人类审查，未记录审阅人、日期与结论）

## Why

系统的核心约束（工具即数据边界、双门禁、口径单一来源）已经实现，但同一行为普遍存在第二份实现：四条执行链、三处 agent 装配、五处 `sys.modules` shim，以及一份与代码结构脱节的容器清单。结果是**约束只写在文档与测试里，没有落在唯一实现上**——改一处会漏另一处，读者无法从任一入口判断哪份是当前事实。

现在做的理由：`analyze_core` 已无调用方（前端仅调 `/api/question`），`routing/intent.py` 生产零引用，`kernel` 装配器已写好却零调用，`Dockerfile` 已引用不存在的文件。这些不是设计债务，而是**已经失效却仍在仓库中的结构**，继续叠加只会放大维护成本。

## What Changes

- **BREAKING** 移除 `POST /api/analyze` 与 `analyze_core`（`app.py:99-165`、路由分支 `app.py:650`）。该链不可达：前端唯一对话请求为 `/api/question`（`web/app.js:196`）。
- 移除 `routing/intent.py` 及其测试（生产引用数 0；`tests/test_api.py:145` 已锁定「不使用路由分类器」）。
- 移除 `agent_engine.run_agent_report`（`agent_engine.py:190-211`，自注 `NOT for production`，且自动批准大纲门禁）。
- 移除 `live` 参数链残留（`_run_agent_conversation(live=...)`、`agent_tools.py:245` 的 `live = None`、`research/live_frames` 分支、prompt 分支）。实时管道本体已由 auto-041 未提交改动删除。
- 移除 `CONVERSATION_EXCLUDED_TOOLS`（`agent_engine.py:43`），对话工具集改由 `INTERACTIVE.allows()` 单一口径决定；该常量降级为测试内基准常量。
- 移除 5 个 `sys.modules` shim（`analysis_methods.py`、`service.py`、`intent.py`、`research_catalog.py`、`mcp_server.py`），调用方改为显式包导入（`from research import service`）。
- 两条生产链的 agent 构造改由 `kernel.builder.build_runner(profile, ctx)` 统一装配，删除 `agent_engine.py:254` 与 `report_session.py:85-96` 的自建副本。
- 修复 `Dockerfile`：COPY 清单删除已不存在的 `db_mirror.py`、`intent.py`，补齐 `kernel/`、`semantic/`、`research/`、`routing/`、`integrations/`。
- 装配唯一性约束的扫描范围从 `kernel/` 扩至整个服务目录（`tests/test_kernel_runner.py:114`）。

## Capabilities

正式规格目录当前为空（`openspec list --specs` 返回 `No specs found`），因此全部为新增能力，无 Modified Capabilities。

### New Capabilities

- `api-surface`：对外 HTTP 端点的集合与职责边界——哪些入口存在、各自承担什么、移除后调用方如何降级。
- `agent-composition`：agent 构造的唯一入口与运行姿态声明——预算、工具白名单、技能集合、门禁配置只能由配置数据决定。
- `analysis-gate`：深度分析的人工大纲确认不可绕过——任何代码路径不得自动批准大纲。
- `service-deployment`：容器镜像必须包含运行所需的全部模块，且不含已删除的文件。

### Modified Capabilities

（无。正式 specs 为空，本次不修改既有规格。）

## Impact

**代码**

- `offline_analysis_pipeline/08_semantic_services/`：`app.py`、`agent_engine.py`、`agent_tools.py`、`report_session.py`、`kernel/builder.py`、`tests/`、5 个 shim 文件（删除）、`routing/intent.py`（删除）。
- `Dockerfile`（修复 COPY 清单）。

**接口**

- `POST /api/analyze` 被移除（**BREAKING**）：返回 404。仓库内前端已不使用；仓库外调用方需迁移到 `/api/question`。
- 其余端点（`/api/question`、`/api/ask`、`/api/agent/report`、`/api/health`）请求/响应契约不变。

**依赖**

- 不变。`requirements.txt` 现有 7 项均有实际用途，本次不增删。

**明确排除**

- **`semantic/` 包本次不改**（Owner 裁定：先不管）。Dockerfile 修复需要将其纳入镜像，但不修改其内部代码。
- `modules/experience_modeling/`（`external_events`）暂不处置：其 MCP 服务当前有 4 个进程占用 8878/8879 端口，需先由 Owner 确认停止后再评估。
- `archive/legacy_pipeline/`（6511 文件）的移出不在本 Change 范围，另立维护变更。
- `01`–`07` 流水线阶段、`06_reporting` 资产、`07_qa_agent` 均保留不动。

**运行环境前置条件**

实施前必须停止正在运行的生产服务（PID 54088，监听 `0.0.0.0:8000`，2026-11-03 13:08 启动）以及两个 `unittest discover` 进程（2026-11-04 12:54 启动）。本提案撰写时两者仍在运行，因此**尚未进行任何代码修改**。

**工作区状态**

当前分支有 23 项未提交改动，属 auto-041 的迁移工作（含 `db_mirror.py` 删除、`research/live_*.py` 删除）。实施前需由 Owner 决定：先在 auto-041 提交并合并，或在新分支继承当前工作区。不得覆盖这些改动。

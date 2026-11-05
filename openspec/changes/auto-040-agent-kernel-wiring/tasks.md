# Tasks

前置：`auto-038` 内核已就绪并通过 20 条 fixture 等价验证。本变更只改 `agent_engine._run_agent_conversation` 一个函数。

## 1. 接线

- [x] 1.1 用 `kernel.RunContext` + `INTERACTIVE.budget` 取代函数内联的上下文 dict，并保留 `live_context` / `report_hits` 等既有键；验证方式：`tests/test_kernel_wiring.py` 断言 `ToolContext` 键集合覆盖旧 dict 全部键
- [x] 1.2 工具过滤改为 `INTERACTIVE.allows(...)` 白名单；验证方式：断言结果集合与旧 `CONVERSATION_EXCLUDED_TOOLS` 补集完全相等
- [x] 1.3 结果派生改调 `kernel.derive.to_answer_view`，显式传入 `data_version` / `snapshot_hash` / `source_mode` / `live` / `sanitizer` / `citation_parser`；验证方式：20 条 fixture 在新路径下逐字段一致
- [x] 1.4 在 `kernel/README.md` 补充"已接线"状态与 Phase 3 待办（预算双来源）；验证方式：文档中不再出现"生产路径未引用内核"的表述

## 2. 验证

- [x] 2.1 跑内核测试与既有回归；验证方式：`unittest tests.test_kernel_* tests.test_api tests.test_frontend_contract tests.test_agent_workflow tests.test_intent` 全绿
- [x] 2.2 重启服务后复跑端到端问答（工具路径 + 报告语料路径 + 纯澄清路径）；验证方式：三条请求均 200，`citations.unknown` 为空，`snapshot_hash` 等于 `service.snapshot_hash()`。注意 `/api/health` 只返回 `status` 与完整 `snapshot_version()`（无 hash 字段），而 `/api/question` 的 `data_version` 经 `_present()` 覆盖为 `display_version()`（`app.py:452`），两者语义不同，不可直接比对
## 证据（2026-11-03 实际执行）

| 项 | 检查 | 结果 |
|---|---|---|
| 1.1 | `ContextBridgeTests`（旧 11 个上下文键全覆盖；无未声明的桥接键） | `Ran 10 tests`/`OK` |
| 1.2 | `ToolWhitelistTests.test_wired_filter_equals_legacy_exclusion` | 白名单 == 旧排除名单补集 |
| 1.3 | `LiveSwitchTests`（快照不带 `source_mode`、实时 `live_transaction` 且 `snapshot_hash=None`、evidence 实时取 `rows`）+ `test_kernel_equivalence` 20 条 fixture 逐字段一致 | 通过 |
| 1.4 | `kernel/README.md` 标题改为 Phase 2 并列出未接线范围 | 通过 |
| 2.1 | `unittest` 13 个模块（内核 8 + api/frontend_contract/agent_workflow/intent/auto030_contracts） | `Ran 170 tests`, `OK` |
| 2.2 | 三条 `/api/question`（工具 / 报告语料 / 纯澄清），独立端口实例 | 均 200；`citations.unknown` 空；`snapshot_hash=ba7dc3feac35` 与 `service.snapshot_hash()` 相等；`data_version` 经 `_present()` 呈现为 `V2.3`（即 `display_version()`） |

## Workflow follow-up

- Phase 3（工具预算来源统一、交付链路接线）另行立项，依赖 `auto-030` 交付。
- 交付需人工代码评审；本变更为 AI 生成代码，不得由实现者自行验收。

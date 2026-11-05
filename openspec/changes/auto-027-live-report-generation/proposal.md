# Proposal

## Why

当前产品的"研究报告"是固定的：右栏展示 auto-023 产出的静态设计版报告，问答虽已改为读这份报告，但内容与用户当下的问题无关。用户提新问题时，系统只能给一段回答，不能给一份**针对这个问题**的报告。

Owner 明确要求："根据用户问题在线实时生成分析报告，而不是现在这种预设的"。这会把产品从"报告阅读器"变成"按需出报告的研究助手"。

## What Changes

- 新增按需报告生成链路：用户问题 → 意图/议题解析 → 只读工具 → 结构化报告 → 确定性门禁 → 实时渲染。
- 报告页从单一静态报告改为两个页签：「实时分析报告」（本次问题生成）与「参考报告（设计版）」（auto-023 产物，只读对照）。
- 对话分析类问题回答完成后自动触发实时报告生成；报告问答类问题保持引用式回答（知识源即参考报告本身）。
- 实时报告落盘到 `reports/live/<report_id>/content.json`（不入库，可重建）。

## Capabilities

### New Capabilities

- `live-report-generation`：按用户问题实时生成分析报告的可观察行为（生成条件、门禁拦截、范围拒绝、页签切换、落盘记录）。

### Modified Capabilities

- 无（`report-orchestration` 的离线管线保持不变；本 Change 复用其工具与门禁，不改动其需求）。

## Impact

- 新增 `08_semantic_services/live_report.py`；`app.py` 新增 `POST /api/report/live`；`web/` 增加实时报告渲染与页签。
- 复用既有只读工具（`query_stats`/`query_claims`）与 `report_gate`，不新增数据通路、不新增模型依赖。
- 数字与引文仍来自冻结快照，生成不引入新数据；门禁失败不展示，范围外问题不生成。

## Ownership and Review

- Change ID：`auto-027-live-report-generation`；人类 Owner：当前用户（实名待补）。
- 规格状态：**APPROVED_FOR_IMPLEMENTATION**（Owner 于 2026-10-25 对话中直接指示实现"根据用户问题在线实时生成分析报告"）。
- 已实现并本地验证：57 项测试通过（`python -m unittest discover -s tests` → OK），实测 `/api/report/live` 生成报告且门禁通过。
- 未决项：参考报告（auto-023 产物）仍是上一版本临时样本，且其封面对比结论与表格存在已知矛盾；新数据版本就位后，参考报告需由离线管线重新生成（auto-025 范围）。

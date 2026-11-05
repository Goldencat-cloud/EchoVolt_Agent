# Proposal: auto-033 报告质量提升——证据附录、撰写分级与结构化人审

## Why

对深度 Agent 报告链路（auto-025/027/031/032 交付物）的五维质量审查（可读性/逻辑性/全面性/深度/可解释性，2026-10-28）发现：确定性校验层（claim_id 闭包、数字溯源、结构必填）已闭环，但存在四个系统性缺口：

1. **可解释性最后一公里断裂**：正文 20 位 claim_id 对最终读者无解析路径（无原帖链接/日期/集合），复核需读 `provenance.json` 原始文件。
2. **结论层无置信分级**：小样本结论（如 n=12 的月度分布）与强结论并列出现在结论摘要中，读者无法区分证据强度。
3. **归因与归组黑箱**：归因章节未强制"机制/证据/替代解释/置信度"结构；证据归组未标注是统计计数还是内容归纳。
4. **人审无对标框架**：gate 自述"不是分析质量"，人工审核侧无五维度 checklist，质量保障在确定性校验与泛化人审之间存在空档。

## What Changes

- **证据附录自动生成**（publisher 层，不改 Agent 行为）：`save_submission` 依据 `evidence_claim_ids` 从冻结精选观点池确定性生成 `evidence.md` + `evidence.json`（claim_id → 原帖 URL/日期/标题/议题/情感/归属/亲历/集合/引文）。附录独立于 `report.md`，不参与 gate 数字溯源（server 端生成，天然可溯源）。
- **新增公开查询 `service.evidence_details(claim_ids)`**：复用 `_claim_records()`，供附录与后续消费方使用。
- **评审 checklist 入发布记录**：`review_and_publish` 接受可选五维 checklist（可读性/逻辑性/全面性/深度/可解释性），校验后写入 `meta.review.checklist`；CLI 增加 `--checklist`。
- **撰写指引升级**（report-authoring SKILL）：结论摘要分点（≤5 条、每条一句+核心数字、小样本标置信度高/中/低）；归因四要素模板；归组方式标注（统计计数/内容归纳）；说明发布版自动附证据附录。

## Impact

- Affected specs: `report-orchestration`（新增 2 个 Requirement，4 个 Scenario）
- Affected code: `research/service.py`、`report_publisher.py`、`agent_skills/report-authoring/SKILL.md`、`tests/test_report_appendix.py`（新增）
- 不改动：`report_gate.py` 校验逻辑、`report_session.py` 编排、Agent 工具契约、`prompts.py` 静态提示词（避免 prompt cache 契约破坏）。
- 不做 LLM 自评/自动评分作为质量证明（维持 auto-025 proposal 边界）：checklist 是人审的结构化辅助框架，仍由人填写 verdict。

## Review

- Owner: 人工（用户 2026-10-28 指示"开始改进"，依据当日五维审查报告授权实施）
- Reviewed commit: 待交付 PR 记录
- Verdict: 待人工验收

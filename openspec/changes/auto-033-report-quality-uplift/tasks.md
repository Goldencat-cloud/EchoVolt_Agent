# Tasks: auto-033 报告质量提升

## 1. 证据查询与附录

- [x] 1.1 `research/service.py`：新增 `evidence_details(claim_ids)`——去重、按 claim_id 升序，返回 url/date/title/aspect/sentiment/ownership/experience/journey/source_set/quote(≤160 字)；查不到的 ID 以 unknown 项如实返回
- [x] 1.2 `report_publisher.py` `save_submission`：依据 provenance 的 evidence_claim_ids 生成 `evidence.md`（claim_id → 原帖链接/日期/标题/议题/情感/归属/亲历/集合/引文）与 `evidence.json`；生成失败不阻塞提交本体，但须返回错误信息（不静默吞掉）

## 2. 结构化人审

- [x] 2.1 `review_and_publish` 增加可选 `checklist` 参数：五维（可读性/逻辑性/全面性/深度/可解释性）键校验，通过后写入 `meta.review.checklist`
- [x] 2.2 CLI 增加 `--checklist`（JSON 字符串，可选），透传给 `review_and_publish`

## 3. 撰写指引

- [x] 3.1 `agent_skills/report-authoring/SKILL.md`：结论摘要分点规范（≤5 条、每条一句+核心数字、小样本结论标注置信度高/中/低）
- [x] 3.2 同文件：归因章节四要素模板（机制/支持证据/替代解释检查/置信度）与归组方式标注（统计计数 vs 内容归纳）
- [x] 3.3 同文件：说明发布版自动附证据附录，正文引用保持 claim_id 即可

## 4. 测试与验证

- [x] 4.1 新增 `tests/test_report_appendix.py`：evidence_details 冒烟（真实数据、含 unknown 路径）；save_submission 生成附录文件且 report.md 未被改动；checklist 合法入档与非法形状拒绝
- [x] 4.2 运行报告链路回归：test_report_source、test_search_claims、test_terminology、test_prompt_cache_contract、test_outline_gate、test_report_appendix
- [ ] 4.3 Owner 通读评审附录样例与 checklist 文案（人工验收项）

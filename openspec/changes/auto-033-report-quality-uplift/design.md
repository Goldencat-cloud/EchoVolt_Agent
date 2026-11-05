# Design: auto-033 报告质量提升

## D1 证据附录放在 publisher 层，而不是 Agent 正文

- Agent 产出的 `report.md` 保持不变：若把附录注入正文，引文中的数字（如维修费 5500-6500）可能不在已验证步骤结果中，触发 gate 数字溯源误拒；也会污染 `report_source.py` 的章节切分与报告问答语料。
- 因此 `save_submission` 在写完 report.md/provenance.json/meta.json 后，依据 `evidence_claim_ids` 调 `service.evidence_details` 生成 `evidence.md`（人读）与 `evidence.json`（机器读）。
- 附录生成是确定性的：claim_id 升序、字段固定、全部来自冻结精选观点池；查询不到的 ID 在附录中如实列出（unknown），不静默丢弃。

## D2 `service.evidence_details` 复用精选观点池

- 复用 `_claim_records()`（core/potential JSON，已含 url/date/title/aspect/sentiment/ownership/experience/journey/source_set/quote）。
- 输入集合去重；输出按 claim_id 排序的列表；quote 截断到 160 字符（附录是索引不是全文，全文在 provenance 引文与原帖）。
- 函数为只读查询，供附录生成与其他消费方（如后续 QA）复用。

## D3 评审 checklist 形状

- 五个固定键：可读性/逻辑性/全面性/深度/可解释性；值为自由文本结论（如"通过""关注：归因强度"）。
- 校验：必须是 dict、键必须是五维的子集、值非空字符串；非法形状抛 ValueError。
- checklist 可选：不提供时行为与现状完全一致（向后兼容既有 CLI 调用）。
- 写入 `meta["review"]["checklist"]`，与 reviewer/verdict 同级，满足"关键判断可追溯"。
- checklist 由人填写；系统只做形状校验，MUST NOT 生成或评分（auto-025 边界：不做 LLM 自评）。

## D4 撰写指引只改 SKILL.md，不改静态提示词

- `prompts.py` 的 `DEEP_ANALYSIS_SYSTEM` 受 `test_prompt_cache_contract` 锁定，且报告撰写细节本就由 report-authoring 技能承载（提交 submit_report 前必读）。
- SKILL.md 增量：结论摘要分点规范（≤5 条、一句+核心数字、小样本置信度标注）、归因四要素模板、归组方式标注、证据附录说明（正文只写 claim_id，发布版自动附索引）。

## D5 测试策略

- 新增 `tests/test_report_appendix.py`：evidence_details 真实数据冒烟 + 未知 ID 如实返回；save_submission 附录文件生成（tmp REPORTS_DIR）；checklist 形状校验与入档。
- 运行报告链路既有测试（test_report_source、test_search_claims、test_terminology、test_prompt_cache_contract、test_outline_gate）确认无回归。

## Verification boundary

证据附录与 checklist 提升的是溯源可达性与人审结构化程度，不改变 gate 的能力边界：校验通过仍不是分析质量证明，发布仍需非作者人审。

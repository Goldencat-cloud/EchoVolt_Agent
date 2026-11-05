# Tasks

前置条件（不在本清单跟踪）：auto-031 对应后端交付合并；实施前 re-read 全部交叠文件（design D5）。

## 1. 目录与能力声明

- [x] 1.1 在 `research/catalog.py` 登记聚合原语能力声明（`date_range_filter`、`cross_dimension`、`brand_compare`）与维度→视图/口径映射；验证：单元测试断言声明取值与口径映射符合 design D1/D4（实施注：2026-10-28 落地——`PRIMITIVE_CAPABILITIES`/`PRIMITIVE_METRICS`/`PRIMITIVE_DIMENSION_COLUMNS` + `catalogue()["primitive"]` 暴露；测试 `tests/test_analysis_primitives.py::PrimitiveCapabilityTests`）
- [x] 1.2 在 `research/catalog.py` 为原语新增目录版本号递增与指标/维度引用校验；验证：`validate_brief` 相关既有测试全部通过（实施注：2026-10-28 落地——`CATALOG_VERSION`→2026-10-28.1，`research-brief.json` 同步，`validate_primitive_bindings()`；测试 `PrimitiveBindingTests` 4 项 + test_service/test_analysis_options 回归共 36 项通过）

## 2. 聚合原语实现

- [x] 2.1 在 `research/analysis_methods.py` 实现原语构造器：metric/group_by/filters 全部取值白名单校验，确定性生成只触语义层视图的 SQL，口径声明按所触及维度自动推导（精选子集日期过滤边界如实标注）；验证：新增单测覆盖合法组合、目录外取值拒绝（附允许值清单）、`assert_semantic_only` 通过（实施注：2026-10-28 落地——`validate_primitive`/`build_primitive_sql`/`run_primitive`，`run()`/`validate_params` 分派原语；测试 `PrimitiveExecutionTests` 合法组合、拒绝附 allowed 清单、语义层防线）
- [x] 2.2 实现时间切片过滤（区间校验落快照覆盖范围，越界拒绝并返回允许区间）与跨维度交叉分组（≤2 维度，单元格计数继承过滤口径）；验证：单测覆盖区间内统计只含区间内声明、越界拒绝、交叉组合计数正确（实施注：2026-10-28 落地——date_range 走 `substr(date,1,10) BETWEEN` 绑定参数，越界报覆盖区间；交叉单测逐格与直查 SQL 对账；能力开关关闭时拒绝）
- [x] 2.3 在 `verifier.py` 适配原语结果复核（关键比例复算、计数与快照核对、空结果登记路径）；验证：单测覆盖复算不符拒绝、空结果登记可提交但数字不可引用（实施注：2026-10-28 落地——精选子集口径与时间范围标注强制；新增 `_check_primitive_recompute` 用参数重建 SQL 复算比对（原语计数不与全量 `semantic_aspect_metric` 对账，由复算兜底）；负占比逐行复算与空结果登记测试通过）
- [x] 2.4 在 `agent_tools.py` 新增原语工具（含 docstring 契约：合法取值示例与边界），登记进溯源账本与工具清单；验证：工具契约固定件 `tests/fixtures/tool-contract.json` 更新且 `test_tool_contract.py` 通过（实施注：2026-10-28 落地——`run_aggregate` 工具（metric/group_by JSON 串/三可选过滤），`_record_step(kind=method, params=clean)` 进溯源账本；固定件新增 `run_aggregate` 段并加一致性测试；`run_analysis_method` 对原语方法返回 `use_run_aggregate_tool`）
- [x] 2.5 计划校验器支持原语工作项（filter/group_by 合法性校验，替代 method/aspect 固定组合检查）；验证：单测覆盖含原语工作项的计划获批与非法 filter 拒绝（实施注：2026-10-28 落地——原语工作项 params 必填且 `validate_primitive` 校验、aspect 字段须为 null、requires_evidence 须为 false、去重键改为 method+params JSON；`submit_report` 对原语工作项按 params 匹配已执行步骤；测试 `PrimitivePlanAndToolTests` 9 项）

## 3. 计划 schema 瘦身

- [x] 3.1 修改 `agent_tools.py` 计划校验：不再要求 `dimension` 与 `requires_evidence`，服务端按 method 推导维度合法性与证据需求（`top_negative_claims` → 需证据），旧字段忽略不拒绝；验证：单测覆盖省略字段获批、含旧字段兼容、推导证据缺失时 `submit_report` 仍拒绝（实施注：2026-10-28 落地——dimension 提供时仍校验匹配、缺省按 method/原语 group_by 推导；requires_evidence 一律由 method 推导；`report_gate._required_sections` 兼容原语 group_by；`test_agent_workflow` helper 对齐推导规则；瘦身测试 3 项）
- [x] 3.2 同步工具 docstring、`agent_skills/plan-drafting`、`agent_skills/analysis-methods` 中与计划字段相关的说明（以 auto-031 基线为起点 re-read 后修改）；验证：人工比对无残留旧字段要求，既有计划相关测试全绿（实施注：2026-10-28 与 4.2 合并执行——plan-drafting/analysis-methods/deep-analysis 全文改写，docstring 更新；相关回归 118 项通过）
- [x] 3.3 更新 `tests/fixtures/tool-contract.json` 计划样例为 v2（无可推导字段）并保留一份旧格式兼容样例；验证：`test_tool_contract.py` 与兼容测试通过（实施注：2026-10-28 落地——固定件新增 plan_samples.v2_slim/legacy_compat，测试断言两样例均可提交获批）

## 4. 提示与技能治理

- [x] 4.1 治理 `prompts.py`：system prompt 删除与工具 docstring/skills 重复的行为规则复述，保留使命级标准与阶段路由，改为引用指向；验证：逐条比对重复清单（proposal Why ④ 所列）消除，`test_prompt_cache_contract.py` 通过（实施注：2026-10-28 落地——计划/报告重提规则与证据字段复述删除，改为引用工具说明；行动块同步）
- [x] 4.2 治理 5 个 `agent_skills/*.md`：删除与 docstring/system prompt 重复的硬约束复述（保留判断力内容），剥离"小米 SU7""临时样本"等数据版本事实（由任务简报承载），清除 Agent 可见文本中的 auto-0NN 工单号；验证：人工逐文件核对 + 4.4 静态检查通过（实施注：2026-10-28 落地——report-authoring 品牌与数据状态改为以任务简报为准，plan-drafting 去除工单号，机制类禁止清单改为指向工具层）
- [x] 4.3 确认 `task_brief.build_task_brief` 动态注入完整承载主体品牌与数据状态声明（已具备则仅补缺项）；验证：单测断言简报文本含主体声明与（临时样本）标识，快照更换参数化用例通过（实施注：2026-10-28 落地——简报原有注入已完整，新增 TaskBriefDynamicFactsTests 锁定）
- [x] 4.4 新增静态一致性测试：Agent 可见静态文本（prompts.py 常量、agent_skills/*.md、工具 docstring）不得含品牌名单/"临时样本"字样/auto-0NN 模式，硬约束短语唯一；验证：测试对改写后文本全绿，且人为注入违规文本时失败并指出文件与位置（实施注：2026-10-28 落地——StaticTextGovernanceTests 4 项：prompts 常量与 5 个技能扫描，工具 docstring 为唯一完整表述层并以正/反断言锁定）

## 5. 表单能力对齐

- [ ] 5.1 修改 `task_brief.form_options()`：按能力声明生成选项——`date_range_filter=True` 返回时间切片（区间与快照覆盖一致），`brand_compare=False` 时不输出对比选项字段；验证：单测覆盖声明翻转对返回结构的影响与向后兼容
- [ ] 5.2 同步 `app.py` options 端点行为与 `agent_skills/plan-drafting` 中"能力未开放时在报告限制说明"的表述；验证：端点集成测试断言未声明能力不出现在返回结构

## 6. 集成验证

- [ ] 6.1 全量运行 `python -m unittest discover -s tests`（`08_semantic_services`）并修复回归；验证：退出码 0，无跳过的相关用例
- [ ] 6.2 用真实冻结快照做一次端到端冒烟（计划含原语工作项 → 执行 → 报告过 gate），核对口径声明与时间切片边界在报告中的表述；验证：冒烟产物中每个数字可回溯到原语结果或白名单结果

## 7. 报告门禁一致性修复（Owner 2026-10-28 收编，见 design D7）

- [ ] 7.1 `report_gate.py`：证据引用条件化（按计划推导）与纯量化报告降级提示；验证：单测——纯量化计划无引用通过、含需证据工作项仍强制
- [ ] 7.2 `report_gate.py`：溯源来源剔除元数字（sql/elapsed_ms/row_count/params）；新增 `N月N日`/`第N位`/`近 N 月` 清洗；裸小数展示舍入容差（半位、仅带小数点数值）；验证：单测——SQL 内数字不再可用、0.2 vs 0.203125 通过、0.24 仍拒、日期叙述不误伤、编造数字仍拒
- [ ] 7.3 `report_gate.py`：空结果解释鲁棒化（议题名或无数据表述任一；全表空按方法名判定）与 20-hex hash 上下文排除；章节行首匹配；超限报错附当前长度；验证：单测覆盖同义表述、全表空、hash 正文、行首章节、超限信息
- [ ] 7.4 `agent_tools.py`：`submit_report` 的 gate 拒绝不计入工具错误预算；docstring 的 key_findings 下限同步；`report-authoring` 技能删除"用户明确询问实现细节时可解释"例外；验证：单测——gate 拒绝后 tool_errors 不变；静态治理测试通过
- [ ] 7.5 全量回归 `python -m unittest discover -s tests` 退出码 0；验证：含既有 gate 数字溯源回归（test_report_gate_numbers）全绿

## Workflow follow-up

- 交付 PR 与人工评审（含 GPT 规格评审、Owner 终审）按 AGENTS.md 执行，不在本清单跟踪。
- 归档与 sync specs 须待交付 PR 合并且 Owner 验收后，经独立维护 Change 处理。

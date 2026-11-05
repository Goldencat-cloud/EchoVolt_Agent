# Design: auto-032-analysis-primitives-and-prompt-hygiene

## Context

动机与问题清单见 proposal.md（Why）。当前实现的关键事实（已验证，2026-10-28 读源）：

- 语义层只有 5 个视图：`semantic_aspect_metric`（全量口径按议题聚合）、`semantic_claim_fact` / `semantic_claim_evidence`（精选子集明细，含 date/sentiment/journey/ownership）、`semantic_post_scope`、`semantic_snapshot_meta`（`db_mirror.py`）。**全量口径没有声明级明细视图**——9701 帖全量声明只存在于上游冻结的按议题聚合 CSV。
- 9 个白名单方法为固定 SQL（`research/analysis_methods.py`），均无日期参数；计划校验强制模型填写 `dimension`（method→dimension 映射已存在于 `research/catalog.py` 的 `METHOD_DIMENSIONS`）与 `requires_evidence`（`agent_tools.py`）。
- 静态 skill `report-authoring` 写死"小米 SU7""临时样本"；硬约束在 `prompts.py`、`agent_skills/*.md`、`agent_tools.py` docstring 三处重复；Agent 可见文本含 auto-0NN 工单号。
- auto-031（在途）已交付/计划交付：`form_options()`（时间切片候选生成，未与能力声明关联）、计划 schema v2（`visualization` 可选字段）、`search_claims`、技能最小更新（其 design D6）。

约束：静态层字节稳定是 KV-cache 契约（`prompts.py`，已有 `test_prompt_cache_contract` 锁定）；`report_gate` 数字溯源与人工审核发布流程不变。

## Goals / Non-Goals

**Goals:**
- 聚合原语：一组取值全部可校验的声明式参数 → 确定性 SQL → 与白名单方法同级的 verifier 复算与溯源登记
- 计划 schema 瘦身：模型只表达意图，维度合法性与证据需求由服务端从 method 推导
- 提示治理：硬约束单一表述、动态事实归简报、静态层一致性测试锁定
- 表单选项由能力声明推导，UI 不承诺引擎不支持的分析

**Non-Goals:**
- 不改变 report_gate 校验语义、大纲审查状态机、人工审核发布流程
- 不替换/删除既有 9 个方法与 3 个取证工具（过渡期并存；收敛另行 Change）
- 不新增全量口径的声明级明细视图（需上游快照再生成，另行立项）
- 不做多品牌数据分支；`BRAND_MULTI_ENABLED` 保持关闭
- 不重设计错误预算粒度（schema 瘦身自然减少失败面）

## Decisions

### D1. 聚合原语 = 目录驱动的小语言，不是 SQL 模板拼接

原语参数：`metric`（负面声明数 / 观点声明数 / 帖子数等，取值 ⊆ `research/catalog.METRICS`）、`group_by`（1-2 个，取值 ⊆ `research/catalog.DIMENSIONS` 的已登记字段）、`filters`（aspect / sentiment / date_range / brand-壳）、`order`+`limit`。服务端把每个取值映射为白名单内的列名与字面量（全部来自 catalog 与快照枚举，不接受模型提供的任何标识符），经 `assert_semantic_only` 后执行。维度→视图映射静态登记：全量口径指标只能沿 `semantic_aspect_metric` 按 aspect 分组；其余组合一律走 `semantic_claim_fact`（精选子集），口径声明由所触及维度的 catalog scope 自动推导。

- 备选 A：继续按需追加固定方法——被否：每解锁一种切片都要新增 SQL 与校验，扩展不可持续，正是本次审查定位的结构问题。
- 备选 B：开放受控 SQL（只读视图 + 语法白名单）——被否：SQL 解析与安全边界复杂度远超收益，且 verifier 复算难以覆盖任意 SQL。
- **口径边界（重要）**：日期过滤本期只作用于精选子集（`semantic_claim_fact` 含 date）。全量口径的时间切片需上游重新生成声明级明细，超出本 Change（Non-Goals）；原语返回的口径声明 MUST 如实标注该边界，skill 指南同步写明，避免"时间切片被误读为全量趋势"。

### D2. 计划瘦身的推导规则与门禁衔接

服务端推导：`derived_requires_evidence = (method == "top_negative_claims")`；维度合法性沿用 `METHOD_DIMENSIONS`。报告门禁不变：推导为 true 的工作项未取得带 claim_id 证据时 `submit_report` 仍拒绝。计划接口忽略（而非拒绝）旧字段——旧格式计划与测试夹具不需批量改写，`tool-contract.json` 固定件随本 Change 更新一份 v2 样例。

- 备选：要求模型显式声明并校验一致性——被否：与现状同构，只是把错误从"填错被拒"变成"填错但一致"，信息量仍为零。
- 原语工作项进入计划：`method = "run_aggregate"`（或原语工具同名），`aspect` 变为可选 filter 之一；计划校验器对原语工作项改为校验 filter/group_by 取值合法性。计划 JSON ≤8000 字符上限不变。

### D3. 提示治理的实施载体：代码执法 + 静态一致性测试

- 硬约束唯一完整表述位置：**工具 docstring**（对模型而言契约与工具同处一手）；system prompt 只保留使命级标准（每个数字可核验等）与失败处理的阶段路由；skills 删除与 docstring/system prompt 重复的行为规则，只保留"何时做、怎么判断"的程序性内容（如拆解自查、分母三问、口径转换表——这些是判断力内容，不是机制规则）。
- 动态事实迁移：`report-authoring` 中"分析主体为小米 SU7""当前快照为临时样本"删除；`task_brief.build_task_brief` 已注入的品牌范围与（临时样本）标识承载该职责（已验证：简报现有文本已含两者）；report_gate 的"正文须含分析主体声明"检查不变。
- 工单号剥离：`plan-drafting` 中的 "auto-030 8.6" 等引用改为行为描述或删除；dev 面向的代码注释不动。
- 一致性检查：扩展 `tests/test_prompt_cache_contract.py` 风格，新增静态扫描——Agent 可见静态文本（prompts.py 常量、agent_skills/*.md、工具 docstring 提取）不得包含品牌名单、"临时样本"字样、auto-0NN 模式；硬约束短语清单（如"全流程仅此一次"）在静态文本中唯一。短语清单随治理收窄维护，避免清单本身变成新的漂移源。

### D4. 能力声明与表单对齐

`research/catalog.py` 新增原语能力声明（`date_range_filter`、`cross_dimension`、`brand_compare`，本期前两真一假）。`task_brief.form_options()` 按声明生成：`date_range_filter=True` → 时间切片选项照常返回；`brand_compare=False` → 返回结构不含对比选项字段（前端零改动兼容）。技能 `plan-drafting` 同步"能力未开放时在报告限制中说明"的表述，替代现状"表单可选但执行不了"。

### D5. 文件所有权、顺序依赖与冲突处理

本 Change 与 auto-031 交叠文件：`agent_tools.py`（计划校验）、`task_brief.py`、`agent_skills/plan-drafting`、`analysis-methods`、`report-authoring`、`research/catalog.py`（间接）、`web/app.js`（仅 options 消费，无交互新增）。

- 顺序约束：本 Change 后端任务在 auto-031 对应后端交付合并后开工；实施前 re-read 全部交叠文件；发现 auto-031 的 schema v2 或技能更新与本设计冲突时停下协调 Owner，不静默择一。
- 单写者：交叠文件在两 Change 间不得并行写入；本 Change 的技能改写以 auto-031 D6 产出的版本为基线。
- Owner 未决项：auto-031 交付节奏与合并顺序需 Owner 裁定（本 design 无法单方确定）。

### D6. 测试策略（确定性优先）

原语：取值校验（目录外拒绝）、SQL 只触语义层、verifier 复算、空结果登记、时间切片边界。计划：v2 字段省略获批、旧字段忽略、推导证据门禁仍拒绝缺证据提交。治理：静态一致性扫描（D3）。选项：能力声明→选项结构的映射与"未声明不出现"。既有 9 方法与 3 取证工具的回归不动。

## Risks / Trade-offs

- [原语表达力扩大，错误组合变多] → 全部取值进目录白名单 + 每结果 verifier 复算 + 既有错误预算；docstring 给合法值示例。
- [精选子集时间切片可能被业务误读为全量趋势] → 口径声明强制携带时间边界与"精选子集"字样；skill 口径红线补对应正反例；报告门禁既有口径检查兜底。
- [auto-031 交付顺序不确定，交叠文件冲突] → D5 顺序约束；冲突上报 Owner；不并行写同一文件。
- [硬约束"唯一表述"清单式检查可能过严或漏检] → 先覆盖已知重复项（小清单起步），清单只删不加时需评审；测试失败信息给出文件与位置。
- [表单选项随能力声明变化，演示脚本可能依赖固定选项] → 能力声明是配置常量，关闭即回退；options 返回结构向后兼容。

### D7. 报告门禁一致性修复（2026-10-28 Owner 收编，范围=审查清单 P1 全部 + P2-4/6/7 + P3-8/12）

2026-10-28 对 `report_gate.py` 的系统性业务审查确认三类问题，本期按授权范围修复：

- **P1-1 证据引用条件化**：gate 的"至少一条 claim_id 引用"改为仅在计划推导出需证据工作项时强制（推导规则与 `agent_tools` 一致：method == top_negative_claims）；纯量化报告降级 warning。
- **P1-2 数字溯源边界**：可比来源仅取 rows/data/result/chart 与证据记录（剔除 sql/elapsed_ms/row_count/params 回显）；新增叙述数字清洗（`N月N日`、`第N位/名/次`、`近 N 月`）；裸小数接受展示舍入（报告精度半位容差，仅限带小数点的报告数值，整数计数逐字不变）。
- **P1-3 空结果解释鲁棒化**：议题名或任一无数据表述（空/无数据/未返回/不支持/未覆盖）即视为已解释；全表空结果以"限制章节非空且含方法名"判定，消除死锁路径。
- **P2-4** 20-hex 未知引用判定排除 hash 上下文（token 前 30 字符含 hash/哈希/指纹 时跳过）。
- **P2-6** `submit_report` 的 gate 拒绝不再计入工具错误预算（已有独立的提交次数与 gate_rejections 计数）。
- **P2-7** data_version 比对大小写归一；key_findings 下限 = min(3, 工作项数)。
- **P3-8** 章节检查改为行首匹配（标题或行首出现，保留子串兼容的行首形式）；**P3-12** 超限报错附当前长度。

排除（仍不在本期）：结构化"引用数字清单"旁路、内部词豁免通道（按审查建议改为删除技能例外条款）、品牌声明检查范围统一。

## Migration Plan

1. 目录与能力声明先行（`research/catalog.py`），原语实现 + verifier 适配 + 单测。
2. 计划校验瘦身 + `tool-contract.json` v2 样例 + 兼容测试。
3. 技能与 system prompt 治理改写（以 auto-031 基线为起点）+ 静态一致性测试。
4. `form_options` 能力推导 + options 端点测试（前端无需改动）。
5. 回滚：原语为增量（不下线既有方法）；计划瘦身与治理改写按 commit 粒度 revert；能力声明常量可即时关闭时间切片选项。

## Open Questions

- 原语工具命名与计划中 method 标识（`run_aggregate` 为工作名）——实现时与 auto-031 的工具命名风格核对后定，不影响接口语义。
- 硬约束唯一表述层最终选 docstring 还是 system prompt——D3 倾向 docstring，GPT 评审时可复核。

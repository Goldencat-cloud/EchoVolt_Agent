# Proposal: auto-032-analysis-primitives-and-prompt-hygiene

- **Change ID**: auto-032-analysis-primitives-and-prompt-hygiene
- **Owner**: 人类 Owner（**待指派**；2026-10-28 由业务审查触发立项，授权范围仅规划）
- **状态**: 规格评审 **待定**（本 proposal 与 delta specs 尚未经 GPT 评审与 Owner 终审）
- **授权实施记录**（2026-10-28，Owner 在会话中裁定，同 auto-031 先例）：① 后端任务按"依赖顺序全做"授权实施；② 同日追加授权：门禁一致性修复（原排除项"report_gate 数字溯源语义变更"经同日系统性业务审查后由 Owner 指示"修复"收编入本 Change，范围限审查清单 P1 全部 + P2-4/6/7 + P3-8/12，见 design D7）。评审通过前不合并、不归档、不 sync specs。
- **授权实施记录**（2026-10-28，Owner 在会话中裁定）：按 auto-031 先例授权实施——Owner 于当日会话中选择"授权实施（同 auto-031 先例）"（署名待补记）。GPT 评审与 Owner 终审**仍待执行**，实施产物以上述授权为临时依据，评审通过前不合并、不归档、不 sync specs。
- **依赖顺序**: 本 Change 建立在 auto-030（已交付）与 auto-031（在途，2026-10-28 立项）之上。auto-031 的表单选项目录（`form_options`）、计划 schema v2（`visualization` 可选字段）与技能更新（`plan-drafting`/`analysis-methods`/`report-authoring`/`sandbox-python`）与本 Change 交叠同一批文件——本 Change 的实施任务在 auto-031 对应交付合并后开工，实施前 re-read 最新文件；冲突按 AGENTS.md 协调，不静默覆盖。

## Why

2026-10-28 的深度分析 Agent 业务审查确认了四个结构性问题：① 上游 V2.3 抽取了丰富的结构（维度/情感/阶段/产品/时间），下游语义层却只暴露 9 个单维 `GROUP BY` 白名单方法，分析表达能力被锁死；② 前端表单承诺"近 1/3/6 月"时间切片与"对比对象"，但没有任何白名单方法接受日期过滤或对比参数——产品承诺引擎兑现不了；③ 分析计划要求模型填写可由 method 推导的 `dimension` 与 `requires_evidence` 字段，凭空制造失败面、浪费错误预算；④ 同一规则散落在 system prompt / skills / 工具 docstring 三处（违反项目自身 "Define once" 约定），且"分析主体为小米 SU7""临时样本"等随数据版本变化的事实被写进字节稳定的静态 skill，数据版本更替或开放多品牌时将变成持久错误指令。

## What Changes

- **受限参数化聚合原语**：新增一个声明式聚合原语（`metric ∈ 目录` × `group_by ∈ 已登记维度` × `filter ∈ 议题/情感/日期区间/品牌`），服务端校验全部取值来自 `research_catalog` 与快照枚举，SQL 由原语确定性构造，仍走 `verifier` 复算与语义层防线。覆盖现有 9 个白名单方法中可被原语表达的单维聚合，并解锁时间切片、跨维度交叉、对比能力。既有方法名在过渡期保留可用（计划校验兼容），废弃另行 Change。
- **计划 schema 瘦身**：`submit_analysis_plan` 不再要求 `dimension` 与 `requires_evidence` 字段——维度合法性由 method→dimension 映射服务端判定，证据需求由 method 语义服务端推导。旧计划含这两个字段时服务端忽略（向后兼容），Agent 指南不再要求填写。
- **Prompt/Skill 单一事实源**：硬约束只在工具代码层强制，skills 与 system prompt 不再复述（引用代替重述）；"分析主体品牌""临时样本标识"等数据版本相关事实从静态 skill 移入任务简报（动态层）；Agent 可见文本剥离内部工单号（auto-0NN 引用）。静态层新增"不得包含随快照变化的业务事实"检查并锁进测试。
- **表单能力对齐**：`GET /api/analysis/options` 的时间范围切片与对比选项由聚合原语的能力声明推导生成——原语声明支持 `date_range` 后"近 1/3/6 月"才如实开放；引擎不支持的能力不再在 UI 承诺。

**排除项（本期不做）**：多品牌数据分支（`BRAND_MULTI_ENABLED` 仍关闭）；接入 `external_events` 事件对照；claim 主题聚类/归因分析；`co_mention_products`/`top_negative_claims`/`snapshot_overview`/`aspect_scope_compare` 的替换或删除；report_gate 数字溯源**重设计**（结构化引用清单等大改）——本期仅限审查清单授权范围的一致性修复；python 沙箱能力扩展；错误预算粒度重设计（仅靠 schema 瘦身自然减少失败面）；前端视觉改动。

## Capabilities

### New Capabilities

- `analysis-primitives`: 受限参数化聚合原语与能力对齐——声明式聚合的取值校验、口径继承、时间切片与交叉分析、计划校验瘦身后服务端推导、表单选项由能力声明同源生成。
- `agent-prompt-governance`: Agent 提示与技能的单一事实源治理——硬约束单一来源、静态层不得携带数据版本相关业务事实、动态事实由任务简报承载、Agent 可见文本不含内部工单号。

### Modified Capabilities

（无——`openspec/specs/` 当前为空，auto-030 的 `deep-analysis-agent` 与 auto-031 的 `deep-analysis-workflow` 尚未归档为正式规格；本 Change 与两者的交付顺序和文件交叠在 design 阶段约束。）

## Impact

- **后端 `08_semantic_services/`**：`research/analysis_methods.py`（原语定义与 SQL 构造）、`research/catalog.py`（能力声明）、`agent_tools.py`（计划校验瘦身、原语工具、错误信息）、`task_brief.py`（动态事实注入、`form_options` 能力推导）、`app.py`（options 端点行为）、`prompts.py`（去重）、`verifier.py`（原语结果复算）、`agent_skills/*.md`（5 个技能文去重与动态事实剥离）。
- **前端 `web/`**：仅消费 `form_options` 返回结构变化（选项按能力声明过滤），无新交互；需与 auto-031 前端任务协同。
- **测试**：`tests/` 新增原语取值校验、SQL 白名单、verifier 复算、计划向后兼容、prompt 静态层事实检查、options 能力推导用例。
- **依赖**：后端无新增第三方依赖。
- **兼容性**：计划 API 向后兼容（旧字段忽略）；既有 9 个方法保留；`form_options` 返回结构向后兼容（新增能力标记字段）。

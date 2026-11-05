# Design

## Context

三类分析能力的触发与边界约束见 proposal.md；行为契约见本 Change 三份 delta specs。此处仅记录影响实现方案的现状（已验证部分均来自本仓库代码阅读，2026-10-27）：

- **后端**（`08_semantic_services/`）：
  - `app.py` 的 POST 分派（`app.py:423-430`）：`/api/ask` → `ask_core`（报告问答）、`/api/analyze` → `analyze_core`（统一对话 Agent，带 session_id）、`/api/agent/report` → `agent_report_start`（深度分析启动）；
  - `jobs.py`：内存任务存储，自带 `set_phase` 阶段级进度事件（"理解问题中…"等文案）与 `finish_ok`/`finish_error` 失败显性化；前端经 `GET /api/agent/report/{id}` 轮询（`app.py:322`）；
  - auto-028 已交付 `agent_engine.py` / `agent_tools.py` / `sandbox.py` / `db_mirror.py`（语义层视图与沙箱）。
- **前端**（`web/`）：`app.js` 为 hash 路由多视图（official/report/library/result/chat）；聊天页已有可开合结果分栏（`has-result` / `#result-divider`，`app.js:258-265`）；引用锚点点击已可跳报告页并滚动定位（`.cite[data-anchor]` → `scrollReportTo`，`app.js:393-397, 420-421`）；输入区已有深度开关 `data-deep-toggle`；官方报告阅读视图为**同源 iframe**（`app.js:394`），父页面可读取其选区与章节锚点。
- **auto-024 契约**（已验证于其 delta spec）：整份报告进 LLM 上下文、超约 60K 字符预算显式报错、引用锚点流水线校验、拒答清单 [R]。
- **约束**：正式规格目录为空，`deep-analysis-agent`/`workspace-navigation` 能力由 auto-028/029 持有；本 Change 的 MODIFIED 归档依赖 auto-028 先同步（validate INFO 已确认，proposal 已记录时序约束）。

## Goals / Non-Goals

**Goals:**

- 以最小改动把统一对话 Agent 收缩为"轻量模式"（工具集收回代码解释器与报告产出），并落实意图引导。
- 复用既有 `/api/ask`、`/api/agent/report`、`jobs.py` 阶段事件与前端分栏/锚点机制，避免新建并行链路。
- 定义"我的报告"引用的请求契约（内容随请求上传），不引入服务端报告存储。
- 深度分析以 job 状态机承载表单→澄清→大纲审查门禁，门禁未通过不进入沙箱。

**Non-Goals:**

- 不做服务端"我的报告"存储、多端同步与账户体系（沿用 auto-029 的 localStorage 决策）。
- 不改深度报告的审核/发布链路、沙箱实现与数据边界（沙箱安全评审为 auto-028 遗留未决项）。
- 不改官方报告内容与 `report-skin.css`。

## Decisions

### D1. 轻量模式通过工具集配置实现，而非新 Agent

统一对话 Agent（`analyze_core` → auto-028 `agent_engine`）保持单实例，按能力集配置收缩：代码解释器工具与报告产出工具从对话 Agent 的工具表中移除，仅注册给深度分析流程。理由：保持 auto-028"同一上下文 Agent"的会话连续性，改动面最小。备选：拆分轻量/深度两个 Agent——被否，会丢失上下文且重复会话管理。

### D2. 引用契约：响应体新增 `citations[]`

`/api/question`（对话 Agent 实际入口；`/api/analyze` 为无报告引用的旧统计路径，不涉及）与 `/api/ask` 响应体在既有 `citations` 对象下新增 `refs: [{anchor, report_id, report_kind}]`。三个字段即定位与路由的全部所需：`anchor` 供滚动定位（复用既有锚点机制），`report_id + report_kind` 供前端决定分栏打开哪份报告。锚点真实性由服务端校验兜底（`/api/ask` 未知锚点拒绝输出；对话路径剥除虚构锚点文本）。备选：前端自行抓取报告并抽取锚点——被否，"我的报告"锚点校验逻辑会被复制。

### D3. "我的报告"引用：内容随请求上传，官方报告按 ID 引用

`/api/ask` 请求体扩展 `report_ref: {kind: "official"|"mine", report_id?, content?}`：官方报告传 `report_id`（服务端已有全文）；"我的报告"为浏览器本地数据，前端随请求上传 Markdown 全文（`content`），沿用 auto-024 的 60K 上下文预算，超限显式报错。服务端对 `mine` 内容做与 `official` 相同的锚点校验（锚点由前端在保存报告时保留，校验"锚点存在于该内容"）。理由：避免为演示场景新增存储；契约对称、可测试。备选：服务端临时缓存上传报告——被否，引入过期/一致性复杂度。

### D4. 深度分析门禁用 job 状态机 + 三个扩展端点

复用 `jobs.py` 的 job 模型，`agent_report_start` 请求体扩展 `brief: {topic, brand?, time_window?}`；阶段文案经 `set_phase` 扩为：`澄清中 → 数据探索中 → 待大纲审查 → 编写分析代码中 → 沙箱执行中 → 撰写报告中 → 已完成 / 失败`。新增：

- `POST /api/agent/report/{id}/clarify`：答复澄清问题（job 处于 `澄清中` 时有效）；
- `POST /api/agent/report/{id}/outline`：`{action: confirm|edit|regenerate, outline?}`，`edit` 以提交的大纲为准；`confirm/edit` 通过门禁后引擎才继续。

理由：与现有轮询模型一致，前端改动小。从引导话术内嵌入口发起时，前端以最近引导上下文预填主题草稿（纯前端行为，服务端契约不变）。备选：SSE 推送 + WebSocket 交互——被否，演示场景过度设计。

### D5. 待审 job 的驻留策略

`jobs.py` 现有过期清理（已验证 `jobs.py:29-33, 110`）会回收长时间任务。大纲待审/澄清中的 job 属于"等用户"状态，延长其过期时限并限制每会话并发的待审 job 数（1 个），超限拒绝新深度分析并提示先完成当前审查。前端将活跃深度分析 job 的 `status_url` 持久化于 localStorage，页面刷新后恢复轮询与进度显示（演示场景刷新常见，成本低、避免进度丢失）。理由：内存模型的简单补偿；不引入持久化。**此为设计假设**：具体 TTL 数值在实现时以现有清理参数为基准确定。

### D6. 前端斜杠命令在前端解析、路由到既有端点

输入框监听：输入 `/` 即提示可用命令（当前仅 `/ask`，不设独立面板层）；`/ask ` 后触发 `@` 报告补全（官方报告清单 + localStorage 我的报告）；提交时前端解析命令并路由：带 `@` → `/api/ask`（附 `report_ref`），不匹配命令语法的文本保持现有 `/api/analyze` 行为。理由：路由决策是纯展示层职责；服务端保持"按内容类型"分派。备选：服务端解析斜杠语法——被否，补全与预览必须前端实时响应。

### D7. 旅程三改动均为父页面叠加，不触碰报告本体

落地视图：首访（无 localStorage 会话标记）默认 hash 指向官方报告视图，此后记住最近视图。桥A："问研究员"为报告阅读视图上的父页面浮动按钮，同源 iframe 读取选区/章节锚点后跳转 `#/chat`，并复用既有结果分栏（`has-result`）内嵌展示对应完整报告——与引用锚点定位共用同一分栏渲染通道。桥C：深度分析结果视图支持划词追问，与桥A 同模式——选中文字后出现提问入口，跳转 `#/chat` 并在分栏内嵌展示该报告，追问按显式引用语义（等价 `/ask @<该报告>`）路由到 `/api/ask`。结果视图为父页面 DOM（非 iframe），选区读取无需跨文档处理。三者均不修改 iframe 内文档与 `report-skin.css`。备选：注入报告页面内部按钮——被否，违反"不改官方报告"约束且 iframe 文档由管线再生成，注入点不稳定。

### D8. 意图引导由 Agent 提示词约束，行为级校验兜底

"分析诉求 → 引导深度分析"由 Agent 系统提示词约束；后端仅在**行为层**兜底：若对话响应试图触发报告产出路径（防御性校验，相关工具已按 D1 收回，正常情况下不可达），MUST 拦截并替换为引导话术。不做回答文本的关键词拦截——"报告里怎么说"这类正常回答会被误伤。理由：话术归提示词、行为归校验器，职责单一且各自可测试；校验器与 auto-028 锚点校验同一模式。

### D9. 大纲门禁机制采用 deepagents interrupt_on，拆段编排保底

> **8.4 spike 结论（2026-10-28 实测，deepagents 0.7.32 + langgraph 1.2.12，假模型确定性测试 `tests/test_interrupt_gate_spike.py` 4 项）：方案 B 生效。**
> - interrupt 触发 ✓：`interrupt_on={"submit_analysis_plan": True}` + `checkpointer=MemorySaver()` + thread_id，batched 模式（默认）；中断值形态 `{action_requests: [{name, args, description}], review_configs: [{action_name, allowed_decisions: [approve, edit, reject, respond]}]}`。
> - resume 三决定映射 ✓：`Command(resume={"decisions": [...]})`（同 thread、同 checkpointer 实例）。confirm→`{"type": "approve"}`（工具以原参数执行，ToolMessage 即纯 JSON 工具返回）；edit→`{"type": "edit", "edited_action": {name, args}}`（**以编辑后参数执行**，但 ToolMessage 带中间件说明前缀 + `Tool response:` 段——8.5 实现时工具结果解析必须兼容该前缀，或直接以 edited_action 为事实源）；regenerate→`{"type": "reject", "message": ...}`（拒绝反馈作为 ToolMessage 回给模型，运行在同一 thread 继续，即"重出草案"）。
> - SkillsMiddleware 共存 ✓：`skills=[AGENT_SKILLS_DIR]` + `FilesystemBackend` 与 interrupt_on 同图工作，暂停/恢复路径无冲突。
> - 实施注意：resume 必须复用暂停时的同一 agent/checkpointer 实例（测试骨架曾因重建实例而无法恢复）；`interrupt_on=True` 展开的 allowed_decisions 含 `respond`，8.5 配置时改用 `InterruptOnConfig` 显式限定 `allowed_decisions=["approve", "edit", "reject"]` 以匹配三动作契约。

`submit_analysis_plan` 配置为 interrupt 工具（`interrupt_on` + checkpointer(MemorySaver) + thread_id）：计划通过确定性校验后运行挂起，job 转 `待大纲审查`；三操作经 resume 映射——confirm→`approve`；edit→`edited_action`（编辑版 plan_json 重新过同一校验器，编辑兜底零新代码）；regenerate→`reject`（带反馈让模型重出草案，原草案留存对比，上限 3 次）。澄清保持在图外（编排器独立小调用，见 D10）。checkpointer 状态以 job 为唯一事实源：job 清理时同步清 thread，待审 job 不占 `MAX_ACTIVE_JOBS` 执行名额。前置 spike：实测 0.7.32 的 interrupt/resume 与 SkillsMiddleware 共存行为；spike 不过则退拆段编排（大纲段 invoke 结束落库待审 + 执行段新 invoke 注入已批准计划），端点契约不变。理由：官方 HITL 与本项目同栈（requirements 钉 `deepagents==0.7.32`，高于文档标注的 0.6.8 门槛），edit 自动复用现有校验器，等待期无存活线程；上下文经同 thread resume 无损带入执行段。备选：手写 langgraph checkpointer 流程——被否，官方封装已覆盖。

### D10. 澄清按充分度判定，失败跳过兜底

必要信息 = 研究主题具体度 + 品牌范围（快照多品牌且未指定时，见 D11）+ 对比意图所涉对比对象；时间窗口可默认快照全区间。确定性快路径优先：可由快照元数据直接判定的（品牌单选、时间窗口超范围）不烧 LLM；需要语义判断的（主题过泛、对比意图）用一次小调用问全当前全部缺口。用户答复后重新评估，充分即停；已答复信息保留，不重复询问；每轮由用户答复驱动，引擎不自行循环，不设固定轮数。兜底：澄清判定调用失败 → 跳过澄清直接探索，方向偏差由大纲审查门禁兜住。理由：Owner 裁定"按澄清程度而非次数"；终止性由用户驱动保证。

### D11. 品牌升格为快照约束维度

品牌清单确定性提取自 `semantic_post_scope`（`SELECT DISTINCT brand`；联结可行性已验证：`claims.post_id` 可联结 `post_scope`，db_mirror.py:31-41）。处理梯子：表单校验 brand/compare ∈ 清单（超清单 4xx 提示可用品牌，与 time_window 同模式）→ 澄清必要性判定（多品牌未指定 = 必要信息，选项来自清单）→ 单品牌默认 + 大纲卡片与报告口径显式声明。报告门禁新增确定性检查：正文必须含品牌范围声明（与数据版本检查同模式）。

**Owner 裁定（2026-10-27）：当前仅开放 SU7 主体分析，多品牌分支延后。** 实现为 `config.BRAND_MULTI_ENABLED` 开关：关闭时未指定品牌即固定主体（小米 SU7）并在简报/大纲/报告声明，指定其他品牌被拒并提示开放范围；开启后启用多品牌澄清分支（梯子代码已实现并有确定性测试覆盖）。注意：实测快照 post_scope 已含 7 个 in_scope 品牌（特斯拉/极氪等），均为帖子内共现对比信息，非分析主体——简报与报告口径须将二者区分。

### D12. 报告交付分层约束与流程兜底

按"越接近事实越死、越接近表达越活"分层：事实层数字溯源校验保持不动；结构层核心三段（结论摘要/证据与归组/限制与不确定性）必填，其余章节按报告类型注入（对比型加对比矩阵、趋势型加归因分析），gate 校验随之调整；风格层 `user-language` 技能 + 确定性内部词禁词检查（workstream、语义层等；claim_id 引用格式除外），命中 gate 拒绝；分析组织不校验，由大纲审查前置把关。硬参数收敛单一常量源（修正 report-authoring ≤1500 字与 gate ≤12000 字符的漂移）。流程兜底：workstream 执行过且结果为空 + 限制章节解释 = 完成可提交（造假仍被数字溯源拦截）；regenerate 上限 3 次；大纲审查卡片随确认携带可选"重点/受众"交付规格字段，注入执行段开场（前端 6.4 协同）。

### D13. 深度分析上下文重构：任务简报（实施第一步）

完整方案、原则依据（Anthropic/Manus 上下文工程原则）与完整示例见本 Change 目录 `context-engineering-revision.md`（D-CTX1~4）。要点：开场消息改为四区任务简报（研究请求/数据覆盖声明/数据目录/预置基准），枚举值、品牌清单、日期范围、口径分区服务端确定性注入，整行样例与长文本移出；baseline 以 `kind: "baseline"` 记入 verified_steps，使预生成数字通过数字溯源门禁（修正 baseline 可引用 SOP 与 gate 只认 verified_steps 的矛盾）；系统提示/技能/开场分层去重，硬参数单一常量源（与 D12 同一常量源）；简报生成器同时向表单校验提供品牌/时间区间清单（与 D10/D11 同一数据源）。与 D9 同窗口实施（执行段开场消息本就重写）。后置观察项：预算计数回传、长运行压缩/结构化笔记——先量化真实任务 token 曲线再决定；不做子代理架构。

**静态/动态缓存契约（KV-cache 架构约束，2026-10-27 实施于 prompts.py）**：静态层（系统提示词、行动块、工具 docstring、SKILL.md）逐字节稳定，构成跨 job 可缓存前缀——禁止时间戳、job 数据、易变插值；动态层（任务简报、工具结果、会话历史）只允许出现在静态前缀之后，单条消息内静态文本先于动态数据（开场消息 = 行动块 → 分隔 → 简报）。文本由 `prompts.py` 注册表统一定义、他处只引用不复述；`tests.test_prompt_cache_contract` 确定性锁定：无日期字面量、跨 job 静态前缀逐字节一致、工具 docstring 跨构建稳定。

**技能架构重组（2026-10-28，Owner 批准方案 A）：11 → 5，按 SOP 阶段组合**。原 11 个技能按"知识主题"切片，导致元决策负担（阶段 1 需从 11 选 2-3 并跳转引用）与规则多处安家。重组为按工作阶段组合：`deep-analysis`（入口）→ `plan-drafting`（起草计划的工作流程：读简报→拆问题→映射方法→自查提交）→ `analysis-methods`（执行循环：取项→取证→解读检查三问→失败/空结果处置，方法选择已在计划期完成，执行期不存在"按域选方法"动作）→ `report-authoring`（报告，含口径表述红线）→ `sandbox-python`（条件技能，仅 use_python=true 时读）。原则：每个技能是动词性的操作程序而非名词词典（静态定义的住所——枚举/覆盖在任务简报、匹配表在工具 docstring、表述红线在 report-authoring）；description 写成路由条件（何时用/不用+反例）；每阶段至多读 1 个技能；规则写成"作用域+动作+例外+验证方式"。

## Risks / Trade-offs

- [待审/澄清中的内存 job 被清理或服务重启丢失] → D5 的 TTL 延长 + 会话内单待审 job；重启后提示用户重新发起（深度分析本就失败显性化，可接受）。
- [意图识别误判（auto-025 曾修复过分类置信度问题）] → 引导话术降级安全：误判只会多引导一次按钮，不会静默执行分析；D8 校验器防反向泄漏。
- [我的报告上传体积超预算] → 前端预检 60K 上限并提示（auto-024 契约），服务端二次校验显式报错。
- [auto-028/029 未合并导致实现基线不确定] → 本 Change 分支基于 auto-028 分支创建（沿用 auto-024 基于分支创建的先例），交付时按 Owner 决定 PR 拆分；delta 归档顺序已在 proposal 记录。
- [沙箱为本地演示级、容器安全评审未完成（auto-028 遗留）] → 本 Change 不扩大沙箱暴露面（代码执行仅限深度分析门禁后），风险随 auto-028 记录移交。
- [interrupt_on 与 deepagents 0.7.32 实测不兼容（SkillsMiddleware 共存、resume 语义）] → D9 前置 spike；失败退拆段编排，端点契约与前端卡片交互不变。
- [checkpointer 内存态与 jobs 内存 store 生命周期不一致] → 以 job 为唯一事实源、清理同步；服务重启两者同丢，提示重新发起，与 D5 一致。
- [简报枚举/清单随快照增长膨胀] → 枚举按计数排序设 top-N 上限，自由文本列只给示例值；简报总长设确定性上限，超限先裁示例值、永不裁覆盖声明。
- [分栏内嵌报告与既有 `scrollReportTo` 跳整页行为并存] → 分栏为对话页内统一的报告承载面：引用锚点点击、桥A"问研究员"与桥C 划词追问均指向分栏；报告页整页阅读入口保留，二者不互斥。窄屏（<1024px）下分栏为视图切换形态（现有 `app.js:258` 行为），spec 已约束"查看后返回对话且状态保留"，与现状一致。

## Migration Plan

1. 分支 `change/auto-030-analysis-capability-triggers` 基于 auto-028 分支创建（若已合并则基于主干）。
2. 后端先行：D1 工具集收缩 → D2/D3 响应与请求契约 → D4/D5 状态机（每步带确定性单元测试，未配置 LLM 时可测）。
2b. 后端核心阶段（Owner 2026-10-27 批准，上下文重构为第一步）：D13 任务简报与 baseline 溯源合法化 → D9 方案 B 门禁（前置 spike）→ D10/D11 澄清与品牌 → D12 交付分层。
3. 前端跟进：D6 斜杠命令 → D7 旅程三改动 → 引用锚点分栏定位 → 深度分析表单与大纲卡片。
4. 回滚：契约扩展均为响应/请求体的**新增字段**，前端旧版本忽略未知字段即可降级；D1 工具集开关可单独回退恢复旧行为。

## Open Questions

- 澄清与大纲审查阶段 job TTL 的具体数值（以实现时观察现有清理参数与演示时长为准，不改变契约）。
- 官方报告清单接口是否已有可复用端点供 `@` 补全（实现时核查 `app.py` 现有 GET 路由；若无则以现有静态清单方式提供，不新增存储）。
- deepagents 0.7.32 interrupt_on 实测结果（D9 前置 spike）：通过则方案 B 生效；未通过则按 D9 备选拆段编排，端点契约不变。
- 时间窗口/品牌可用区间数据源已收敛：由 D13 简报生成器与快照元数据同源提供，表单提示与 agent 简报共用。

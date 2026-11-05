# Tasks

## 1. 准备与基线

- [x] 1.1 确认 auto-028 分支状态并创建唯一开发分支 `change/auto-030-analysis-capability-triggers`（基线为 auto-028 分支，若已合并则基于主干）；在 proposal.md 补记基线 commit。验证：`git status` 干净、分支名正确、proposal 审阅记录已更新。
- [x] 1.2 复跑既有测试套件确认基线全绿（`08_semantic_services` 现有单元/接口测试）。验证：全部通过且无新增失败。（实施注：2026-10-28 修复两个预存失败——`aspect_scope_compare` 的 `negative_post_rate` 在 SQL 中 `ROUND(...,4)` 展示舍入，而 verifier 以 1e-6 复算导致必然超差；修复为 `verifier.py` 帖子占比检查采用与展示精度半位对齐的 `RATE_TOLERANCE`（≈5e-5），分母混用类错误仍被拦截。全套 152 项通过）

## 2. 后端轻量模式与意图引导（D1/D8）

- [x] 2.1 从对话 Agent 工具集中移除代码解释器与报告产出工具（保留统计查询、观点证据、报告检索），深度分析流程保持完整工具集。验证：单元测试断言对话 Agent 工具表不含沙箱类工具、深度流程含全部工具。（实施注：对话入口实测为 `/api/question` → `run_agent_conversation`，经 `CONVERSATION_EXCLUDED_TOOLS` 过滤；`/api/analyze` 为无报告引用的旧统计路径，见 design D2 更新）
- [x] 2.2 对话响应行为级后置校验：拦截试图触发报告产出路径的响应并替换为深度分析引导话术（不做回答文本关键词拦截，见 design D8）。验证：校验器拦截路径确定性测试通过；引导话术行为在配置 LLM 的环境手动验收。
- [x] 2.3 `/api/analyze` 响应体新增 `citations[]`（anchor/report_id/report_kind）。验证：接口测试断言字段存在、锚点存在于被引报告、无锚点引用被拒绝。（实施注：落点为对话入口 `/api/question` 的 `citations.refs`，`/api/analyze` 不涉及报告引用）

## 3. 报告问答契约扩展（D2/D3）

- [x] 3.1 `/api/ask` 请求体扩展 `report_ref`：`official` 按 `report_id` 服务端取全文；`mine` 接受随请求上传的 Markdown `content`。验证：接口测试覆盖两种 kind 的成功路径。
- [x] 3.2 对 `mine` 内容实施与 `official` 相同的锚点校验与 60K 上下文预算，超限与未知锚点均显式报错（错误码沿用 auto-024 契约）。验证：单元测试覆盖超预算报错、未知锚点拒绝、拒答清单命中拒绝。（实施注：拒答清单 [R] 由报告正文自带、经问答提示词约束生效，本层未重复实现独立校验；超预算与未知锚点拒绝已测）
- [x] 3.3 `/api/ask` 响应体同样返回 `citations[]`。验证：接口测试断言斜杠命令路径的回答带真实锚点。

## 4. 深度分析门禁状态机（D4/D5）

- [x] 4.1 `/api/agent/report` 请求体扩展 `brief{topic, brand?, time_window?}`，服务端校验 topic 必填、time_window 在冻结快照覆盖范围内（超范围 4xx 并返回可用区间）。验证：接口测试覆盖缺 topic、超范围时间窗口、合法提交三类。（实施注：2026-10-28 落地——`task_brief.validate_brief`（4.1/D11 表单校验与简报同源：snapshot_coverage + resolve_brand_scope；time_window 格式 `YYYY-MM-DD ~ YYYY-MM-DD`、起终序与快照区间校验，400 响应携带 `allowed_brands`/`allowed_time_window`；无 brief 的旧请求兼容）；`app.do_POST` `/api/agent/report` 分支接线；端点级测试三类路径 + validate_brief 单测 7 项（tests/test_task_brief.py），全套回归通过）
- [x] 4.2 阶段文案与 `set_phase` 扩展为：澄清中 → 数据探索中 → 待大纲审查 → 编写分析代码中 → 沙箱执行中 → 撰写报告中 → 已完成/失败。验证：单元测试断言各阶段事件按序出现在 job events。（实施注：2026-10-28 落地——`jobs.create_job` 初始「澄清中」；`pause_for_clarify`（澄清中）→ `claim_for_run`（数据探索中）→ `pause_for_review`（待大纲审查）→ `claim_for_resume`（编写分析代码中）→ `python_analyze` progress「沙箱执行中」（原「执行分析代码中」）→ `submit_report` progress「撰写报告中」→ 已完成/失败；事件按序断言见 `tests/test_clarify.py` 全流程与 `test_outline_gate.py`）
- [x] 4.3 新增 `POST /api/agent/report/{id}/clarify`：仅 `澄清中` 状态有效，答复后进入数据探索；信息完整路径跳过澄清（引擎内判定）。（实施注：澄清按充分度判定，见 design D10 与 8.6；必要信息含品牌范围，见 D11）验证：接口测试覆盖澄清往返与跳过路径。（实施注：2026-10-28 随 8.6 落地——`app.agent_report_clarify`（answer 1..2000 校验；答复后台重评估，客户端轮询 status 取新问题或数据探索中，与既有轮询模型一致）；跳过路径=start 时判定充分（或判定失败无确定性缺口兜底跳过）直接 launch；测试：澄清往返→数据探索→大纲门禁全流程 + 非澄清中 409 + 非法答复 400（`tests/test_clarify.py`））
- [x] 4.4 新增 `POST /api/agent/report/{id}/outline`：`confirm|edit|regenerate` 三动作；门禁未通过时引擎 MUST NOT 进入编写代码阶段；edit 以提交大纲为准并标记状态。验证：接口测试断言待审状态下无代码执行事件、confirm/edit/regenerate 三路径行为正确。（实施注：2026-10-28 随 8.5 落地——`app.agent_report_outline`：confirm→approve、edit→`edited_action`（plan_json 2..8000 校验后由工具校验器重过）、regenerate→reject（带反馈，`REGENERATE_LIMIT=3` 超限 429 `regenerate_limit_reached`）；非待审状态 409 `outline_not_awaiting_review`，`claim_for_resume` 原子占用防并发双 resume；验证见 `tests/test_outline_gate.py`）
- [x] 4.5 待审/澄清中 job 的过期时限延长与每会话单待审 job 限制（数值以现有清理参数为基准，见 design D5 假设）。验证：单元测试覆盖超限拒绝新深度分析、提示先完成当前审查。（实施注：2026-10-28 落地——`jobs.py`：`PENDING_TTL_SECONDS=6h`（基准 JOB_TTL 1h 的延长）分层清理（终态过 JOB_TTL、pending 过 PENDING_TTL、running 永不清理）、`MAX_PENDING_JOBS=10` 全局待审上限（约束 checkpointer 内存）、`create_job(question, brief, session_id)` 每会话单待审（重复→None）+ `pending_exists_for`；`app.agent_report_start` 超限区分响应：同会话已有待审→409 `pending_review_exists`（提示先完成当前审查），全局满→429 `deep_analysis_busy`；测试：单待审/全局上限/TTL 分层（`tests/test_outline_gate.py`））
- [x] 4.6 失败显性化回归：确认失败路径仍返回原因与重试入口、无自动回退（auto-028 决策不回退）。验证：既有失败测试全部保持通过。（实施注：2026-10-28 回归确认——`test_jobs` 失败显性化（finish_error 保留原因）与 `test_agent_workflow` 失败路径全部保持通过；8.5 会话化后 `_spawn`/`_spawn_flow` 任何异常均走 `finish_error` 且不自动回退/重试；全套 189 项通过）

## 5. 前端：斜杠命令与轻量分析交互（D6）

- [ ] 5.1 输入框 `/` 前缀命令面板（当前仅 `/ask`），`/ask ` 后 `@` 报告补全列表（官方报告清单 + localStorage 我的报告）。验证：浏览器手动验收补全行为。
- [ ] 5.2 命令提交解析与路由：带 `@` → `/api/ask` 附 `report_ref`；裸 `/ask` 阻止发送并提示需指定报告。验证：DOM 级测试覆盖两种提交路径。
- [ ] 5.3 引用锚点分栏定位：点击回答中的锚点，在结果分栏内嵌打开对应报告并滚动定位、高亮被引段落（改造既有 `scrollReportTo` 指向分栏），对话保持可用。验证：浏览器手动验收锚点定位与对话可用性。

## 6. 前端：旅程闭环（D7）

- [ ] 6.1 首访落地官方报告视图（localStorage 标记判断），此后保持最近视图。验证：清空存储后打开落在官方报告；再次打开回到最近视图。
- [ ] 6.2 桥A"问研究员"：报告阅读视图父页面浮动按钮，同源 iframe 读取选区/章节锚点，跳转对话页、结果分栏内嵌展示对应完整报告（复用 `has-result` 分栏机制）并预填；报告 iframe 文档与 `report-skin.css` 零改动。验证：浏览器手动验收选中/未选中两种预填与分栏展示；diff 确认未改报告文件。
- [ ] 6.3 桥C 划词追问：深度分析结果视图选中文字后出现提问入口（与桥A 同模式），跳转对话页、分栏内嵌展示该报告并预填所选原文，追问按显式引用语义路由 `/api/ask`。验证：浏览器手动验收划词、分栏展示与来源锁定回答。
- [ ] 6.4 深度分析 UI：按钮改为打开输入表单卡片（含时间窗口可用区间提示）、澄清与大纲审查卡片（确认/编辑/重新生成，状态可见）、阶段进度展示（消费 job phase 事件）、失败原因与重试入口。验证：浏览器手动验收全流程走通一遍（含一次人为失败）。
- [ ] 6.5 深度分析会话韧性：引导话术内嵌"发起深度分析"入口并预填主题草稿；活跃 job 的 `status_url` 持久化 localStorage，刷新后恢复进度轮询与展示。验证：从引导话术发起时表单已预填；刷新页面后进度恢复显示且结果可达。

## 7. 集成验收与文档

- [ ] 7.1 全链路集成测试：官方报告落地 → 桥A预填提问 → 轻量回答带引用 → `/ask @我的报告` → 引导话术 → 深度分析（澄清/大纲/执行/结果）→ 结果视图划词追问。验证：集成测试或录屏记录全部通过。
- [ ] 7.2 复跑 `openspec validate auto-030-analysis-capability-triggers --strict --no-interactive` 并更新 proposal.md 审阅记录（reviewer/date/commit/verdict/未决项）。验证：validate 通过、审阅记录完整。
- [ ] 7.3 浏览器视觉与响应式验收（沿用 auto-026 品牌令牌；<1024px 抽屉侧栏下桥A/表单可用，分栏切换查看报告后返回对话且状态保留）。验证：桌面与窄屏各一遍手动验收清单。

## 8. 后端核心：上下文重构、方案 B 门禁与交付质量（D9–D13，Owner 2026-10-27 批准；上下文重构为实施第一步）

- [x] 8.1 任务简报生成器（D13/D-CTX1、D-CTX4，**实施第一步**）：四区开场简报（研究请求/数据覆盖声明/数据目录/预置基准），枚举值、品牌清单、日期范围、口径分区服务端确定性注入；整行样例与长文本移出；简报总长上限与裁剪规则（先裁示例值、永不裁覆盖声明）；同一函数向表单校验提供品牌/时间区间清单（与 4.1 联动）。验证：确定性单测断言全部字段在场、裁剪次序正确（枚举/覆盖声明不裁）。（实施注：落点新模块 `task_brief.py`，`agent_engine._opening_message` 改为简报+行动块；真实快照实采见本目录 `agent-context-actual.md`。实测发现快照已含 7 个 in_scope 品牌——品牌为当下多品牌，非未来假设）
- [x] 8.2 baseline 溯源合法化（D13/D-CTX2）：baseline 以 `kind=baseline` 记入 verified_steps，gate/verifier 适配该校验路径。验证：回归测试——baseline 数字写进报告不再触发"来源外数字"，伪造数字仍被拒。（实施注：`agent_engine._baseline_step` 记账；`report_gate` evidence 汇总纳入 rows；provenance 随 submit_report 持久化、发布复检自洽）
- [x] 8.3 提示词分层去重与硬参数单一常量源（D13/D-CTX3、D12）：系统提示只留行为高度、开场只放数据、规则细节归技能与工具 docstring；字数/预算/上限收敛到 config 单一来源（修正 ≤1500 字 vs ≤12000 字符漂移）。验证：审查无重复表述；技能与 gate 引用同一常量。（实施注：config 新增 REPORT_MAX_CHARS/BRIEF_* /BASELINE_TOP_ROWS；report-authoring SKILL.md 移除冲突字数；工具预算常量仍在 agent_tools——随 8.5 方案 B 一并收敛，本项未动。后续按 KV-cache 契约增设 `prompts.py` 静态提示词注册表——系统提示/行动块/对话提示词统一定义，开场消息改为静态行动块在前、动态简报在后，`test_prompt_cache_contract` 锁定无时间戳、跨 job 前缀逐字节一致、工具 docstring 稳定。再后续按 Owner 批准的方案 A 完成技能架构重组 11→5：新增 plan-drafting 与 analysis-methods，report-authoring 吸收 user-language/evidence-citation/口径表述红线，删除 8 个旧技能目录，全仓库零残留引用）
- [x] 8.4 spike：deepagents 0.7.32 interrupt_on 实测（D9 前置）：假模型跑通 interrupt 触发、resume 三决定（approve/edit/reject）与 SkillsMiddleware 共存。验证：spike 结论记录于 design D9；不通过则 8.5 改走拆段编排备选（契约不变）。（实施注：2026-10-28 结论=方案 B 生效，本地 deepagents 已升级 0.7.21→0.7.32 与 requirements 对齐；4 项确定性测试 `tests/test_interrupt_gate_spike.py` 全过并留作 8.5 回归锁。关键发现：edit resume 后 ToolMessage 为"说明前缀+Tool response:"复合格式；`interrupt_on=True` 默认含 respond 决定，8.5 需用 InterruptOnConfig 显式限定三动作。详见 design D9 spike 结论块）
- [x] 8.5 门禁接入 interrupt_on（D9）：`interrupt_on` 配置 `submit_analysis_plan`、checkpointer+thread_id、三动作 resume 映射（confirm→approve / edit→edited_action / regenerate→reject，重生成上限 3 次）、job 与 checkpointer 生命周期对齐（清理同步、待审不占 `MAX_ACTIVE_JOBS`）。验证：接口测试覆盖三路径、待审状态下无代码执行事件。（实施注：2026-10-28 落地——新模块 `report_session.py`（ReportSession：checkpointer+工具上下文随 job 持有，`InterruptOnConfig` 显式限定 approve/edit/reject，`_sweep` 与 job 清理同步）；`jobs.py` 增 `awaiting_review` 状态（`pause_for_review`/`claim_for_resume` 原子占用/`record_regenerate`），待审不占 `MAX_ACTIVE_JOBS`；`agent_engine.run_agent_report` 降级为 legacy 自动批准包装，服务端路径走 session；spike 测试 4 项 + 新增 `tests/test_outline_gate.py` 9 项（jobs 生命周期 2 + 端点三动作/上限/非法动作/404/待审无执行事件 7），全套 165 过）
- [x] 8.6 澄清充分度引擎（D10）：确定性快路径（品牌单选、时间窗口超范围）+ 语义判定小调用一次问全缺口；已答复信息保留不重复问；失败跳过兜底。验证：单测覆盖跳过、问全、答复后重评估、失败跳过四路径。（实施注：2026-10-28 落地——新模块 `clarify.py`：确定性缺口自快照元数据（品牌待澄清分支，经 resolve_brand_scope 同源），语义判定 `_llm_judge` 一次小调用问全（JSON 输出）；时间窗口超范围已在 4.1 提交时拦截、不进入澄清；答复历史随 assess 传入、判定提示词明确不重复问；失败兜底=有确定性缺口只问确定性的（`judge_unavailable_deterministic_only`）、否则跳过（`clarify_judge_failed_skip`，大纲门禁兜底）；单品牌裁定下当前默认路径为跳过澄清直接探索。测试：`tests/test_clarify.py` 6 项单测（judge 注入，无 LLM）+ 2 项端点流程，全套 186 过）
- [x] 8.7 品牌梯子（D11）：品牌清单提取（`semantic_post_scope` DISTINCT brand）、brief 校验（brand/compare 超清单 4xx 提示可用品牌）、单品牌默认声明、gate 品牌范围声明检查。（Owner 裁定 2026-10-27：先单主体 SU7——`resolve_brand_scope` 已在 8.1 落地并含 `BRAND_MULTI_ENABLED` 开关与测试；本项剩余落点为 4.1 表单校验端点与 gate 品牌声明检查）验证：接口测试覆盖非开放主体拒绝、未指定默认主体+声明、报告缺声明被拒。（实施注：2026-10-28 收尾——4.1 表单校验随 validate_brief 落地（brand 超清单 400 带 allowed_brands）；`report_gate._has_brand_scope_declaration`：正文须含「分析主体」/「品牌范围」声明字样且写明小米/SU7，缺声明拒绝、checks 增 `brand_scope_declaration`；`report-authoring` SKILL.md 口径红线增品牌范围声明必写条目；测试：声明缺失/仅有主体无声明字样拒、两种声明字样过（tests/test_task_brief.py），既有 gate fixtures 已同步补声明）
- [x] 8.8 沙箱错误提示映射与预算计数回传（D13 配套）：KeyError→实际列清单、AttributeError→可用成员、空结果→关键列非空计数与去重值数、超时→拆分提示；成功响应附 calls/errors 剩余计数与 80% 阈值警告。验证：单测断言各类错误返回携带修复提示。（实施注：2026-10-28 落地——`agent_tools`：`_sandbox_error_hint`（KeyError→`_semantic_columns()` 经 PRAGMA table_info 列出语义层实际可用列；AttributeError→常用成员与字典式列引用提示；超时→先过滤再聚合/拆分提示）、`_empty_result_hint`（claims/metrics 关键列非空计数与去重值数，附"过滤条件取值须来自数据目录枚举"）、`_budget_snapshot`（成功与失败响应附 `successful_calls_left`/`error_budget_left`，≤20% 触发 `budget_warning`）；`python_analyze` 成功/失败路径全部接线；测试 6 项（KeyError/AttributeError/超时映射、空结果、预算回传、80% 警告，`tests/test_sandbox.py`））
- [x] 8.9 报告分层结构与禁词检查（D12）：核心三段必填 + 按报告类型注入章节的 gate 校验；内部词确定性禁词检查（claim_id 引用格式除外）；空结果 workstream 规则（执行过且为空 + 限制章节解释 = 可提交）。验证：单测覆盖缺核心段拒绝、类型章节注入、禁词命中拒绝、空结果合规通过。（实施注：2026-10-28 落地——gate：`CORE_SECTIONS`=结论摘要/证据与归组/限制与不确定性，`_required_sections(plan)` 按计划类型注入（对比型=product 维度或 co_mention_products→对比矩阵；趋势型=time 维度或 negative_claims_by_month→归因分析），`validate_submission` 增 `plan` 参数（submit_report 传入）；`INTERNAL_TERMS` 禁词（workstream/语义层/semantic_/frames./verified_steps/白名单方法/工具名），`CLAIM_CITATION_RE` 剥离 claim_id 引用格式后检查；空结果规则：`run_analysis_method` 对仅"查询结果为空"的校验失败登记 `verification.empty_result=True` 步骤（计入 workstream 完成度），gate 要求该议题在限制章节被解释（议题名+"空"字样）否则拒绝；既有 gate fixtures 同步补核心段（原本含五段仍过）；测试 7 项（`tests/test_task_brief.py`））
- [x] 8.10 交付规格字段接收与注入（D12，与前端 6.4 协同）：大纲审查动作携带可选"重点/受众"，注入执行段开场简报。验证：接口测试断言字段随 confirm/edit 进入执行上下文。（实施注：2026-10-28 落地——outline confirm/edit 请求体可选 `focus`/`audience`（≤200 字），`jobs.record_delivery_spec` 持久化 + `report_session.set_delivery_spec` 注入工具共享 context（`context["delivery_spec"]`），活图恢复前经 `update_state` 以用户消息注入执行段（失败不阻塞）；`task_brief.build_task_brief` 研究请求区新增"交付规格"行（重点/受众，未指定给默认值），拆段编排备选与后续 fresh run 同样生效；测试：confirm 携带规格→job 记录 + session 捕获（`tests/test_outline_gate.py`））
- [ ] 8.11 行为验收与 token 计量：修订前后同批问题对比（计划一次通过率、沙箱首/二次成功率、错误预算消耗、gate 拒绝次数）+ token 曲线记录（作为压缩/笔记是否启动的依据）。验证：验收记录更新 proposal.md。（实施注：2026-10-28 确定性埋点已落地——`agent_engine.report_metrics`（successful_tool_calls/tool_errors/code_failures/submit_attempts/gate_rejections，随 report_outcome["metrics"] 进 job result）+ job 级 regenerates 计数（8.5）；**行为对比与 token 曲线需配置 LLM 的环境运行同批问题，未测量**，验收记录框架与未决项已记 proposal.md，勾销待 Owner 在配置环境执行）
- [x] 8.12 claims 召回工具 `search_claims`（Owner 2026-10-28 指示新增，8.3 系统协同核查后续）：服务层确定性相关度召回（关键词覆盖 × core/potential 层级权重 × 亲历加成 × 新近度；池内全部通过 evidence_ok 引文回挂校验）；工具层受计划约束（aspect ∈ 已批计划议题），走 `_record_step("evidence")` 溯源账本——召回结果可直接满足 requires_evidence 完成条件；`analysis-methods` 取证规则更新为三选一。验证：`tests/test_search_claims.py` 11 项确定性单测全过，全套 149 项无新增回归。（实施注：后续按 Owner 同日指示将相关度主分升级为 embedding——新模块 `research/embeddings.py` 走 OpenAI 兼容 `/embeddings`（复用 AI_BASE_URL/AI_API_KEY，`config.AI_EMBEDDING_MODEL` 可选开关），池向量按快照指纹+模型落盘缓存于 `data/embedding-cache/`，任何调用失败降级关键词评分并输出 `relevance` 字段与 `embedding_unavailable_keyword_fallback` 警告；requirements 显式声明 openai。验证：`test_search_claims.py` 增至 14 项（embedding 过滤/降级/未配置三路径），全套 150 过 + 2 个预存失败（verifier 容差，随 1.2 修复），无新增回归）

## Workflow follow-up

- 交付 PR 创建与人类 Owner 代码审查（本 Change 排在 auto-028/029 合并之后，MODIFIED 归档依赖 auto-028 规格先行同步）。
- 归档该 Change 并同步正式规格，需在交付 PR 合并与 Owner 验收记录之后，经单独维护 Change 完成。
- 公网部署前的公开数据授权确认仍为 Owner 未决项（沿 auto-025 记录）。

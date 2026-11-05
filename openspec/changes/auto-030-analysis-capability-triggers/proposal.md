# Proposal

## Why

Owner 于 2026-10-27 明确产品定位为"行研机构"，要求三类分析能力各有明确的触发方式与输出边界：官方报告阅读（已完成）、深度分析（仅在显式点击"深度分析"时触发）、轻量分析（对话中按需隐式触发，斜杠命令为显式引用报告的一种情形）。当前实现与此存在冲突：auto-028 的 2026-10-26 扩展允许统一对话 Agent 自主选择包括代码解释器在内的工具，且报告页与对话页的使用旅程存在断点（报告阅读页无法就地提问、深度分析产出后缺少追问入口），需要收紧触发模型并补齐旅程闭环。

## What Changes

- **BREAKING（对 auto-028 已批准决策的修订）**：收回统一对话 Agent 的两项权限——代码解释器（沙箱）仅在深度分析流程内可用；对话 Agent 永不产出报告文件。auto-028 proposal 中"由 Agent 自行选择……或调用代码解释器"的决策据此修订。
- 新增**轻量分析**（对话 Agent 隐式按需，A 档能力边界）：官方报告/我的报告全文问答 + 语义层确定性统计查询（metrics/claims/evidence 视图）+ 观点证据下钻；回答带引用锚点与口径；命中拒答清单即拒答；永不产出报告。
- 新增**意图引导行为**：对话中检测到分析诉求（如"帮我分析一下XX"）时不执行，引导用户点击深度分析按钮。
- 新增**斜杠命令** `/ask @<报告名> <问题>`：显式锁定引用源，回答必须仅出自指定报告并带真实锚点；`@` 后提供报告名自动补全（官方报告 + 我的报告）；不支持不带 `@` 的裸 `/ask`。
- **深度分析流程扩展**：点击"深度分析"按钮 → 前置输入表单（研究主题必填；品牌/对比对象与时间窗口可选，时间窗口受冻结快照覆盖范围约束，超范围在表单内提示可用区间；从引导话术内嵌入口发起时预填主题草稿）→ 条件触发的对话澄清（至多一轮，仅问缺失的必要信息，输入完整则跳过）→ 数据探索（分进度提示，复用现有状态机制；活跃任务刷新页面后恢复进度显示）→ **大纲草案审查门禁**（确认 / 编辑 / 重新生成三操作，审查通过方可进入沙箱执行）→ 沙箱执行 → 撰写报告 → 结果视图；失败显性化沿用 auto-028 已有决策（显示原因 + 重试入口，无自动回退）。
- **工作台旅程闭环**：首访落地视图为官方报告；报告阅读页新增"问研究员"入口（桥A：点击后跳转对话页并在结果分栏内嵌展示对应完整报告，携带当前章节/用户选中文本上下文预填问题；不改报告内容与 `report-skin.css`）；深度分析结果视图支持划词追问（桥C：与桥A 同模式——选中文字后跳转对话页、结果分栏内嵌展示该报告并预填所选原文，回答按显式引用语义仅出自该报告并带锚点）。
- **引用查看增强**：点击对话回答中的引用锚点，结果分栏内嵌打开对应报告并定位到被引段落，对话保持可用。

## Capabilities

> 注：正式规格目录（`openspec/specs/`）当前为空，`deep-analysis-agent` 与 `workspace-navigation` 为 in-flight Change（auto-028、auto-029）已声明但未同步的能力；本 Change 的 delta spec 以其声明的能力路径为准，交付时按各 Change 的合并顺序协调同步。**时序约束（openspec validate 2026-10-27 INFO 已确认）**：`deep-analysis-agent` delta 中的 MODIFIED 段要求 auto-028 的规格先行同步至 `openspec/specs/`，否则本 Change 归档将被拒；因此本 Change 的交付 PR 与归档必须排在 auto-028（及 auto-029）之后。

### New Capabilities

- `lightweight-analysis`：对话内轻量分析契约——能力边界（报告问答 / 确定性统计 / 证据下钻，禁止代码执行与报告产出）、分析诉求的意图引导、斜杠命令 `/ask` 的显式引用契约、真实引用锚点要求。

### Modified Capabilities

- `deep-analysis-agent`：触发方式收紧为仅显式点击"深度分析"按钮；新增前置输入表单、条件澄清（至多一轮）、大纲审查门禁（确认/编辑/重新生成）、时间窗口快照范围约束、分进度提示；代码解释器从对话 Agent 工具集收回。
- `workspace-navigation`：首访落地官方报告视图；报告阅读页"问研究员"入口（跳转对话页 + 结果分栏内嵌报告 + 预填上下文）；深度分析结果视图划词追问（与桥A 同模式）；引用锚点点击在结果分栏定位被引段落。

## Impact

- 前端 `offline_analysis_pipeline/08_semantic_services/web/`（index.html / app.js / styles.css / tokens.css）：落地视图、桥A/桥C、斜杠命令解析与自动补全、引用锚点分栏定位、深度分析输入表单与大纲审查卡片、分进度提示。
- 后端 `08_semantic_services/`：对话 Agent 工具集调整（收回代码解释器工具）、报告问答/对话接口响应体新增引用锚点契约 `citations[]`、深度分析编排新增表单与大纲审查状态流转（复用 `POST /api/agent/report` 契约扩展）；后端核心阶段（2026-10-27 批准）新增：深度分析上下文重构（任务简报、baseline 溯源合法化）、门禁机制方案 B（deepagents interrupt_on）、品牌快照约束梯子、报告交付分层与沙箱错误提示映射。
- 修订 auto-028 proposal 的 2026-10-26 决策记录；与 auto-029 的侧栏、结果视图实现衔接。
- 数据边界不变：Agent 仅见语义层只读视图，raw 表不暴露；沙箱执行仅限深度分析流程。

## Scope

**范围内**：上述触发模型、轻量分析契约、斜杠命令、深度分析流程扩展与旅程闭环交互。

**范围外（exclusions）**：不改官方报告内容与 `report-skin.css`；不做报告多端同步与用户账户体系（我的报告仍为浏览器本地）；不改报告审核/发布流程（深度报告仍走统一审核链路）；不改上游 01–05 管线与数据采集。

## Ownership and Review

- Change ID：`auto-030-analysis-capability-triggers`；人类 Owner：当前用户（实名待补）。
- 唯一开发分支：`change/auto-030-analysis-capability-triggers`；唯一交付 PR：待创建。
- 规格状态：**PENDING_REVIEW**。需求依据：Owner 于 2026-10-27 在探索对话中逐项确认——定位行研机构；不提供自由文本分析入口；轻量分析采用 A 档（报告问答 + 语义层统计 + 证据下钻）；`/ask @报告名 问题` 定稿且不支持裸 `/ask`；首访落地官方报告视图；采纳桥A（问研究员）与桥C（划词追问，与桥A 同模式）；引用查看采用锚点分栏定位（取消引用气泡与段落摘要）；澄清条件触发且至多一轮；大纲审查为确认/编辑/重新生成三操作。
- 终审修订（2026-10-27）：按 Owner 四项标准（保障用户体验、减少设计冗余、杜绝过度设计、保障技术可行性）完成一轮一致性清理——移除过时的气泡/摘要/按钮残留文案，简化意图引导校验为行为级兜底，`citations[]` 精简为定位必需字段。本 proposal 与 delta specs **待 Owner 审阅批准后方可进入实施**。
- 实施授权与范围（2026-10-27，Owner 指示）：Owner 批准进入实施，本轮范围为**前端交互全量 + 后端轻量改动**（使交互闭环可用：对话 Agent 工具集收回、`/api/ask` 的 `report_ref` 与引用锚点契约）；深度分析门禁状态机（表单/澄清/大纲审查的后端编排）为核心优化，**延后至下一阶段**。基线说明：仓库中不存在 auto-028 独立分支，auto-028/029 实现以未跟踪文件存在于 `change/auto-025-agent-report-orchestration` 工作区；开发分支 `change/auto-030-analysis-capability-triggers` 自当前 HEAD `b3f017bc` 创建，保留全部未提交工作。
- 后端核心阶段授权（2026-10-27，Owner 指示）：门禁状态机进入实施，并经探索对话扩展为五项决策——D9 门禁机制方案 B（deepagents interrupt_on，spike 前置）、D10 澄清按充分度（Owner 裁定"按澄清程度而非次数"，delta spec 已同步修订）、D11 品牌快照约束梯子、D12 报告交付分层与流程兜底、D13 深度分析上下文重构（**实施第一步**，设计依据与完整示例见本目录 `context-engineering-revision.md`）。任务落点 tasks.md 第 8 节。
- 本轮实施结果（2026-10-27）：后端轻量改动（`agent_engine.py` 对话工具集收回+提示词引导+未知锚点剥除；`app.py` `/api/ask` report_ref 契约与 `citations.refs`、行为级报告产出兜底；`report_source.py` `sections_from_markdown`）已落地，新增 14 项契约测试全部通过（`tests/test_auto030_contracts.py`）；前端交互（首访落地、斜杠命令补全、引用锚点分栏定位、桥A 问研究员、桥C 划词追问、深度分析表单卡片、任务刷新恢复）已在 `web/` 实现并通过语法检查与代码走查。已验证：`openspec validate --strict` 通过；全量 unittest 113 项中 2 项失败为工作区既有数据校验问题（`test_agent_workflow`，`run_analysis_method` 复算不符，不经过本轮改动路径），基线另有沙箱负载超时抖动（单独运行全过）。未决项：前端浏览器人工验收（任务 7.3 清单）、深度分析端到端流程（依赖下一阶段后端 4.x）、引导话术 LLM 环境手动验收；工作区改动未提交，待 Owner 审查。
- 前端系统性排查与修复（2026-10-27，Owner 指示）：修复 5 项真实缺陷——① `/api/ask` 多词报告名解析截断（改为已知名最长前缀匹配）且缺问题/未知名时保留用户输入；② `MAX_BODY` 4096 卡死"我的报告"整份上传（提升至 512KB 并保留 413 契约测试）；③ `_call_report_qa` 锚点校验始终对官方章节执行导致 mine 路径必然拒绝（改为传入本次 sections）；④ QA 提示词示例 `[F1]` 偏置导致 mine 路径虚构锚点（改为动态注入允许 ID 清单）；⑤ 死代码清理（`loadAspectNames`/`currentSessionRecord` 及 6 组无产出方样式）。验证：真实 LLM 下 mine 问答端到端 200 且 `citations.refs` 正确（agent-1/local-test/mine）、超预算 4xx、官方路径 refs 正常、全量测试回到既有 2 失败、CSS 括号平衡与死引用清零、JS 语法通过。遗留：`test_agent_workflow` 2 项数据复算失败（既有问题，建议另立处理）；浏览器人工验收待 Owner。
- UX 修复 P0+P1（2026-10-27，Owner 批准"可以"）：P0 五项——① 输入框补全浮层改为 absolute 悬挂（`.composer-box{position:relative}` + `bottom:calc(100%+8px)`，含 suggest-in 入场动画），消除弹出/收起的布局跳动；② `openDeepForm` 打开前移除既有未提交的 `.deep-form` 消息卡片，杜绝多张表单叠放；③ 报告入口按钮文案"生成完整研究报告"→"发起深度分析"，与深度分析表单/后端术语统一，且 `deep_analysis_guided` 引导回复也渲染该入口（消除引导死胡同）；④ `showCitePick(text, refName, rect)` 泛化（报告名与视口坐标由调用方显式传入），并做视口边界夹取（上越界翻到选区下方、左右夹取）杜绝浮层越界；⑤ 深度分析 chip 语义修正 `aria-pressed` → `aria-haspopup="dialog"`（它打开对话框而非切换态）。P1 五项——⑥ 官方报告 iframe（同源）内划词触发"问研究员"浮层（选区 rect + frame 偏移换算），与"我的报告"结果视图划词一致；⑦ 侧栏「我的报告」新增报告数徽标 `#library-badge`（`.nav-badge`，saveReport 与初始化时 `updateLibraryBadge()` 同步）；⑧ 空状态新增 3 个 `data-fill` 示例问题 chips（`.empty-suggest` 居中布局），降低首访冷启动认知负担；⑨ 静态资源缓存版本号递增（`?v=20261027-2`）。验证：`node --check` 通过、CSS 括号平衡 252/252、HTTP 冒烟确认单实例服务且页面/JS/CSS 均含新标记、全量 unittest 113 项回到既有 2 失败基线（无新增失败）。遗留：浏览器人工验收（agent-browser 被系统策略拦截）待 Owner 本机执行；工作区改动未提交，待 Owner 审查。
- 报告检索卡片去摆设化（2026-10-27，Owner 指出"报告依据/检索到的报告内容像摆设"并要求查行业最佳实践）：对照检索到的 RAG 引用展示最佳实践（来源需可追溯、展示支撑片段并高亮命中、引用可点击跳转、附"为什么命中"说明），实施——① `agent_tools.search_published_report` 的 `report_hits` 由仅 `{id,title}` 扩展为附带 `snippet`（新增 `_hit_snippet`：围绕首个命中词 ±70 字截取原文）与 `matched_terms`，并按章节 ID 去重；② 前端卡片改名「报告原文片段」，渲染高亮命中词的片段与命中词说明，有锚点的卡片改为按钮可点击 → 分栏定位到官方报告对应章节（复用 `showOfficialInPane`）；③ `.evidence mark` 高亮样式与 `button.evidence` 可点击样式，缓存版本号递增 `?v=20261027-3`；④ 新增 3 项契约测试（`ReportHitSnippetTests`：片段居中截取、无命中回退头部、检索 enrichment+去重）。验证：`node --check` 通过、契约测试 17/17、程序化全量 131 项仅剩 2 个既有 `test_agent_workflow` 数据复算失败（无新增）。未改变 `report_hits` 既有字段，旧会话持久化数据兼容。
- 首次对话布局与输入框消失修复（2026-10-27，Owner 报告首条 `/ask` 消息后空状态滞留、输入框错位/消失）：根因——① 收起空状态的 `dockComposer()` 只在普通提问路径 `askOnce` 调用，`/ask` 路径（`askReport`）、命令提示（`askCommandHint`）、深度表单（`openDeepForm`）均不调用，导致首条消息走这些路径时空状态滞留、消息追加在居中布局下方；② 空状态下输入框 `#chat-form` 位于 `chatLog` 子树内的 `#composer-slot`，`renderEmptyState()` 直接 `innerHTML` 重建会把它连带销毁成游离节点，且滞留时消息滚动令输入框滚出视口（视觉"消失"）。修复——把空状态收起下沉到 `addMsg()` 开头（任何消息出现均保证空状态已收起、输入框停靠底部，覆盖全部首条消息路径），并在 `renderEmptyState()` 重建前将仍在 `chatLog` 内的输入框先移回窗格再 `innerHTML` 重建。缓存版本号递增 `?v=20261027-4`。预期行为：任意路径的首次对话，空状态随首条消息收起、消息流正常排列、输入框始终停靠底部可见；「新建对话」/切换会话不再可能丢失输入框。验证：`node --check` 通过、服务已提供最新代码。
- @ 直触与多位置划词提问（2026-10-27，Owner 指示，对标 Codex 引用式交互）：① 斜杠命令 `/ask @报告名 问题` 改为直接 `@报告名 问题` 触发——`parseAskCommand` 要求 `q.startsWith('@')`、提交入口匹配 `/^@/`、输入补全改为输入 `@` 即弹报告清单（移除 showCmdSuggest/cmd 类型）、占位符与命令提示文案同步、用户气泡显示 `@报告名 问题`；`/api/ask` 后端契约不变。② 多位置划词"问研究员"统一为 `attachSelectionPicker(frame, refName)`（同源 iframe 内 pointerup 出浮层、click/scroll 收起、选区 rect + frame 偏移换算、`selectionContext` 取选区上方最近编号标题作为来源章节），绑定三处：官方报告阅读页 `#report-frame`（#/report）、结果分栏官方报告 iframe（`showOfficialInPane`）、结果视图「我的报告」正文；悬浮框保持单按钮 pill（简洁）。③ 点击"问研究员"→ 跳转对话页并保持分栏，选段以 Codex 式引用卡片（`#composer-quote`：选段原文 + 来源章节 + 移除按钮，`.composer-quote` 左引线样式）挂在输入框上方，输入框预填 `@报告名 `；提交时 `composeQuestion` 将选段并入问题文本（`报告选段"…"（出自「章节」）：问题`）并清空引用卡。缓存版本号 `?v=20261027-5`。验证：`node --check` 通过、`/ask` 残留仅注释与 `/api/ask` 接口、CSS 括号 260/260、HTML/JS 冒烟含全部新标记、契约测试 17/17。
- 豆包式行内引用（2026-10-27，Owner 指示：回答与来源的关联改为行内角标）：对话回答中的引用展示由底部「报告依据」/「报告原文片段」汇总区块改为行内角标模式——① `renderAnswer` 将 `citations.sections`（被引锚点）与 `report_hits`（检索命中）按 ID 去重合并为来源清单，每条含 `{id,title,kind,report_id,snippet,matched_terms}`，以 `<script type="application/json" class="cite-sources">`（`<` 转义防逃逸）随消息持久化（会话回放可用）；② 回答文本中匹配来源清单的 `[锚点]` 标记（`[A-Za-z0-9_-]+`）替换为编号角标 `<sup class="cite-inline">`（accent 底色小圆角编号，hover 加深），未匹配的文本原样保留；③ 点击角标弹出 `showSourceCard` 来源卡片（fixed 定位、视口夹取、Esc/滚动/点外部收起）：头部为序号 + 章节标题 + 来源类型标签，正文为命中片段（`highlightTerms` 高亮命中词）或"已引用章节"说明，底部「定位到报告章节」按钮——mine 来源走 `showReport` + `scrollPaneReportTo`，官方来源走 `showOfficialInPane`；④ 移除底部两个汇总区块及 `locateCitation`、`data-hit-anchor` 死代码。缓存版本号 `?v=20261027-6`。验证：`node --check` 通过、死引用清零、CSS 括号 271/271、服务已提供最新代码、全量 132 项测试仅剩 2 个既有 `test_agent_workflow` 数据复算失败（无新增）。
- 划词记录与笔记管理（2026-10-27，Owner 指示：划词不直接跳转、累积保存、统一管理、引用精简）：① 划词悬浮框（原"问研究员"单按钮）改为**记录框** `.quote-form`——选段预览 + 来源（报告 · 章节）+ 问题输入框（可留空）+「保存」/「立即提问」双动作；保存写入 localStorage `ai.quotes.v1`（上限 50 条 FIFO），保存后关闭可继续划词，多次记录累积保存；「立即提问」= 保存 + 跳转对话（引用卡挂选段、预填 `@报告名 [已输入问题]`）。② 侧栏新增「划词笔记」导航项（`data-nav="notes"` 拦截不走路由，`#quotes-badge` 数量徽标），打开轻量 overlay 面板 `#quotes-panel`：列表展示每条记录（来源标签、章节、时间、选段引文、问题），支持**编辑**（行内 textarea）、**删除**、「问研究员」从记录发起对话（跳转对话 + 引用卡 + @ 预填）；空状态有引导文案；遮罩点击/×/Esc 关闭；移动端（≤720px）面板贴底全宽。数据模型 `{id,text,question,source,section,kind,report_id,created_at}`，`store`（localStorage + 内存兜底）持久化，刷新不丢失。③ 引用角标精简：回答文本中连续多个 `[锚点]` 折叠为一个角标，仅显示**引用条数**（`data-srcs` 逗号分隔保存全部锚点）；来源卡片适配多引用——每条独立展示（编号 + 章节标题 + 来源标签 + 命中片段高亮 + 独立定位按钮），卡片限高滚动（`max-height:min(64vh,520px)`）。卡片样式升级：片段加 canvas 底色圆角块、分隔线、高度夹取适配。④ 清理 `.cite-pick` 死样式。缓存版本号 `?v=20261027-7`。验证：`node --check` 通过、`cite-pick`/`data-src` 死引用清零、CSS 括号 304/304、HTML/JS/CSS 冒烟均含新标记、契约测试 17/17。遗留：浏览器人工验收待 Owner（含移动端划词长按选区体验）；工作区改动未提交。
- 三维审查记录（2026-10-28，范围=深度分析执行模块 `08_semantic_services`）：已完成用户体验/产品流程/工程规范三维审查并修复落地项——ENG：README API 清单补 6 个深度分析端点（核对后剔除误写的 cancel）、auto-031 归档顺序硬约束写明（MODIFIED 依赖 auto-030 先行）、outline regenerate 计数移到占用成功后（并发白增修复）、legacy `run_agent_report` 加显式无门禁警示、embedding 快照缓存按模型保留最新 3 份。未修（阻塞前端解锁/需配置环境）：阶段文案与审查卡片前端接线（6.2/6.4/4.2/4.3）、旧/新草案对比渲染（后端 outline_history 已就绪）、8.11 行为对比与 token 曲线（需配置 LLM）。验证：全套 220 项通过。
- E2E 真实用户模拟批次（2026-10-28 第二轮，`tests/e2e_user_sim.py` + 离线健壮性电池 `tests/test_user_flows_api.py`）：正常（口语吐槽/购车咨询）、异常（竞品销量超范围/无意义输入/指令注入导出）、边界（空与超长问题、坏 JSON 编辑、非待审操作、限流、并发双任务）全覆盖，**6/6 PASS**（105-130s/单）+ 确定性电池 9 项。发现并修复 2 项：① 大纲 edit 坏 JSON 此前被 202 放行、失败延迟到 resume 才暴露 → 端点层即校验 JSON 语法与 workstreams 结构（语义仍由校验器统一执行）；② 提交尝试上限 3→4（3 次常被"首轮全量错误+收尾漏网 1 个数字"耗尽，4 次可挽回近失型失败，e_nonsense 实测挽回）。行为亮点：e_sales 报告明确"销量不在数据范围"且零编造数字；e_inject 报告拒绝导出原始数据且零内部词泄漏；b_parallel 双任务隔离完成。全套 248 项通过。
- E2E 端到端实测（2026-10-28，LangSmith 监控下 4 场景 × 5 轮迭代）：以 HTTP 全链路驱动（detail/vague/compare/trap，trap=诱导性问题），第 5 轮 **4/4 全部 done**（81-111s/单），全程 trace 在 LangSmith `deep-agents-action` 项目。实测发现并修复 7 项缺陷：① 澄清语义判定不收敛（7/5/9 轮连环追问，判定器不知系统固定事实且无轮次上限）→ prompt 注入固定事实（品牌裁定/数据源/口径/交付）+ 单轮问全 ≤3 问 + `CLARIFY_MAX_ROUNDS=2` 保险丝；② `report_session.resume` 未按 HITL batched 协议包装 `{"decisions":[...]}`（resume 必挂，单测因 FakeSession 全未覆盖）→ 补包装；③ 8.10 `update_state` 交付规格注入破坏暂停态消息序（assistant tool_calls 后插 user 消息被端点 400）→ 改经批准后工具结果注入；④ gate 数据版本拒绝消息缺实际值 → 补（首次提交 3 连拒的直接原因）；⑤ 数字溯源误报（年份 2023/日期 12-24 被当统计数、20.3% vs 0.203125 舍入不匹配）→ 剔除日期年份 + 百分数 0.05pp 容差；⑥ `co_mention_products` SQL 列名与视图漂移（`m.analysis_series`→`m.series`，OperationalError）；⑦ POST 限流 10/60s 被单个正常会话（启动+澄清+审查）耗尽 → 20/60s。行为数据：每场景 submit_attempts=2（gate 拒 1 次后自修）、trap 场景报告明确拒绝"证明 SU7 加速最快"诱导并主动用 co_mention_products 做竞品语境分析、大纲 w1-w6 方法映射全对且 detail/trap 主动声明 visualization。token 成本：单次深度分析约 20-30 万 tokens（LangSmith 根 run 聚合），尾段 gate 重试约占 1/3——改进空间为在 submit_report 文档给出 data_version 精确串。遗留：前端接线（6.x/4.x）；8.11 修订前后对比可在本批 4 场景基线上开展。
- 8.11 行为验收与 token 计量（2026-10-28 更新）：① 确定性埋点已落地——`agent_engine.report_metrics(context)`（successful_tool_calls/tool_errors/code_failures/submit_attempts/gate_rejections）随 `report_outcome["metrics"]` 进 job result；E2E 实测 4 场景 metrics 已入档（`data/e2e-runs/20261028-191233/`）。② token 曲线：LangSmith 监控已接入（trace 项目 `deep-agents-action`，.env 复用 Owner 提供的 `d:\Desktop\Projects\deep_agents_action\.env` 配置），单次深度分析聚合 20-30 万 tokens 已测得；修订前后同批对比（各 ≥3 次）仍待 Owner 排期执行后勾销。本条不构成验收通过。

# auto-023-temp-analysis-report

## Why

离线管线的采集（auto-021）与清洗（auto-022）产出已冻结为 06_reporting 的分析数据（9,529 帖 / 26,936 Claim / 15,002 提及，2022-10-28 ~ 2026-10-03 快照）。Agent 搭建阶段有两个目标：**① 离线分析报告的问答；② 用户问题的在线分析**。两者都需要一个先行存在的分析知识库作为接地语料。Owner 指示跳过离线评估阶段（由队友负责），先基于已有数据构造一份**临时的离线分析报告**，供后续 Agent 搭建使用。

该工作与 auto-022（comment-corpus-cleaning）无业务重叠，须独立成 Change、独立分支，不得混入清洗 Change。

**数据版本澄清（Owner 2026-10-22 指示）**：上述 06_reporting 分析数据是**上一版本的产物**；新版本数据由队友负责、尚未完成。因此本 Change 的定位是**只搭架子**：以旧版数据构造临时报告，用于验证知识库结构、口径写法与 Agent 消费接口；数字仅作结构验证占位，不作为正式结论资产，Agent 侧 MUST NOT 硬编码任何具体数字，新数据就位后按同一契约整体替换。

## What Changes

- 新建临时分析报告 `offline_analysis_pipeline/06_reporting/SU7临时分析报告-Agent知识库.md`（初稿已按 Owner 直接指令完成，待规格审查与人工评审）：
  - 结构化重组既有冻结数据（summary/profiles/aspect-sentiment/scope/verification/reviewed-cases），不重算上游、不新增模型调用；
  - 口径与术语表先行（表达≠人数、负面占比定义、cohort 嵌套不可加、ownership 标签含义）；
  - cohort 漏斗、方面×情感双维（热度 vs 负面占比）、旅程前/后关注点转移、11 个证据案例库、竞品共提及视图；
  - 面向 Agent 的拒答清单（禁止结论）与五段式回答模板；
  - 显式排除：不含离线评估结论（未完成）、不输出车主满意率/故障率、不充当正式交付。
- 架子优先：报告头部与工件显式声明数据版本（上一版本产物，占位）；沉淀一份**知识库数据契约**（数据来源清单 + 版本声明 + 替换方式），使新版本数据就位后可整体换入而不改报告结构与 Agent 代码。
- 双读者格式（Owner 2026-10-22 确认）：**单一 Markdown 源 + 脚本生成的 SVG 图表 + 导出的单文件 HTML**。人类阅读 HTML（图文混排）；Agent 消费 MD 结构化层（口径/拒答/模板），图表 caption 内嵌可校验数字锚点供引用定位。规划使用场景：人类阅读报告时由 Copilot Agent 伴随问答；问题超出报告范围时 Agent 转入在线分析。
- 阶段路线（Owner 2026-10-22 更新）：**第一阶段 = 离线分析报告 + 基于 LLM RAG 的报告离线问答**（产品形态：用户接入数据 → 平台自动产出报告 → RAG 问答；明细即时查询经 Owner 指示移出第一阶段）；**第二阶段 = Agent 团队自动产出与核查分析报告**（数据管道自动运行，agent 做报告更新）；联网补充分析推迟。数据更新是脚本自动化，无人值守。
- 本 Change（第一阶段·报告部分）产出文档工件 + 报告生成链（`agent-kb/`，stdlib-only，只读 analysis 冻结数据），并沉淀供问答 Agent 消费的数据接缝（numbers.json 答案册、Agent 版 MD、明细索引接口预留）；**问答 Agent 服务本体为后续独立 Change**，联网采集分析明确推迟。**不改任何管线代码与数据**。

## Scope

**范围内**：上述临时报告文档（占位性质，基于上一版本数据）；其数字可追溯性核验；**知识库数据契约**（数据来源清单、版本声明、替换方式）；Owner 规格审查与人工评审记录；后续按评审意见修订。

**范围外**：新版本数据的分析与报告（队友负责，完成后按数据契约接入）；离线评估（队友负责）；Agent 服务本体（问答编排、检索层、在线分析流程——后续独立 Change，只搭架子不绑数字）；主题模型/embedding/新模型 API 调用；01/02/03/04/05 管线代码与数据修改；正式（非临时）知识库建设。

## Capabilities

### Added
- `analysis-report-kb`：临时分析报告作为 Agent 知识库的契约——数字可追溯、口径先行、边界显式、Agent 消费结构与范围隔离。

### Modified
- 无。openspec/specs 当前为空，本 Change 不修改任何已交付正式 spec。

## Impact

- 代码：无（纯文档 Change）。
- 数据：无修改；只读取 06_reporting/analysis/ 冻结文件（原始文件与 9,529 份冻结原文哈希未变，verification.json 12 项检查通过）。
- 下游：为后续 Agent Change 提供接地语料与口径基准；临时版将在离线评估结论就绪后升级为正式版。
- 协作：Owner 审阅 proposal/design/spec/tasks 并批准后，报告方可作为 Agent 搭建依据；交付走独立分支与本 Change 的 PR。

## Ownership and Review

- Change ID：`auto-023-temp-analysis-report`；人类 Owner：当前用户（沿用本会话身份，实名未补）。
- 唯一开发分支：`change/auto-023-temp-analysis-report`；唯一交付 PR：待创建。
- 批准状态：**PENDING_REVIEW**。报告初稿系 Owner 2026-10-22 直接指令（"开个新分支……撰写一份临时分析报告"）的产物，先于本 Change 工件存在；四份工件呈现后待 Owner 规格审查。审查通过前，报告不得作为 Agent 搭建依据。
- 与 auto-022 的隔离：本 Change 不触碰 02_cleaning 代码、标注表与别名映射；分支自 auto-022 分支 HEAD（b3f017bc）切出仅为继承工作区冻结数据，不并入其任务或 PR。
- reviewed_commit：null（本 Change 工件尚未提交）。

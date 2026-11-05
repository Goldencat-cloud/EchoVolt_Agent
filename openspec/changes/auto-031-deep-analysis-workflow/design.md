# Design: auto-031-deep-analysis-workflow

## Context

引擎侧（auto-030）：澄清充分度、方案 B 大纲门禁、执行循环、溯源门禁、任务简报（覆盖声明/数据目录/预置基准，`task_brief.py` 生成）。前端（auto-029 已基本交付）：自研 `renderMarkdown()`（app.js:32-65，无外部 markdown 依赖）、「我的报告」localStorage（app.js:414 附近）、结果视图、下载 .md（app.js:409）。**已验证**：前端无 ECharts、无 marked；官方报告样式走 `report-skin.css`。

业务流程与五项 Owner 决策见 proposal.md；行为契约见 specs/deep-analysis-workflow/spec.md。本文件只讲实现取舍。

## Goals / Non-Goals

**Goals:**
- 澄清输入结构化：对象/时间走选项，主题与子问题自由填写，选项数据与 Agent 简报同源
- 计划起草前的合法探索（按议题预览样本量/时间分布/代表性观点）
- 草案双层：大纲（用户视图）与执行步骤（Agent 视图），编辑双向一致
- 图表数据可产出、可溯源、可渲染
- HTML 成为报告交付与下载格式

**Non-Goals:**
- 多品牌数据分支（品牌梯子已有，本期单选项）
- 外部搜索工具；预置子题库；后端报告清单端点（auto-029 localStorage 决策）
- 门禁状态机变更（auto-030 tasks 8.4/8.5 承担）
- 官方报告（report-skin.css）样式改动

## Decisions

### D1. 选项目录：task_brief 同源扩展，不新建独立服务

`task_brief.py` 增加 `form_options()`：分析对象 = `resolve_brand_scope` + `snapshot_coverage`（品牌清单，当前仅 SU7）；时间范围 = 从快照 `date_max` 回溯生成确定性候选区间（近 1 月 / 近 3 月 / 近 6 月 / 全部，均校验落在这覆盖区间内）。`GET /api/analysis/options` 返回该结构。
- 备选：独立 options 服务/独立 YAML 配置——被否：与简报同源是 spec 硬约束（MUST），两处生成必然漂移。
- 主题不做选项卡：自由填写文本进 brief.topic，Agent 映射议题（existing behavior，无新机制）。

### D2. 探索预览：semantic_overview 增加 aspects 过滤参数

`semantic_overview(aspects=[])`：对指定议题返回精选证据样本量、按月计数分布、代表性观点（top 3，带 claim_id）。全部服务端 SQL 确定性聚合；工具 docstring 更新用途与边界（计划阶段专用）。样本量阈值（<5 条须标注支撑不足）写入 `plan-drafting` 指南，不做 gate 强制——阈值是业务判断，门禁管不了"该不该问"。
- 备选：新工具 `preview_scope`——被否：与 semantic_overview 职责重叠，工具数量应克制。

### D3. 草案双层：大纲是执行步骤的投影，不是独立文档

计划 schema v2 仅在 workstream 上增加 `visualization` 可选字段（`{type: bar|line|pie|table, x, y, title}`）。**大纲层不落独立字段**：大纲审查卡片直接渲染 workstreams 投影（question + visualization 描述 + 依赖关系），用户编辑即编辑 workstreams。这样 spec 的"执行层 MUST NOT 与大纲矛盾"由构造保证（同一数据源），消除双文档同步问题。
- 备选：独立 outline 数组 + steps 数组 + 双向同步——被否：两处状态必然漂移，同步逻辑复杂且无业务收益。
- 影响接口：`submit_analysis_plan` 接受 visualization（可选，向后兼容）；大纲卡片渲染逻辑属前端。

### D4. 图表数据：两个来源，一条溯源通道

- **白名单方法**：图表数据不落库——渲染层按计划的 `visualization` 意图从 `result.rows` 确定性生成图表配置（列到轴的映射规则写在 `report-authoring` 技能）。
- **python_analyze**：返回值扩展 `chart` 键（`{type, title, x_label, y_label, data}` JSON）；沙箱透传，禁 I/O 不变。
- **溯源**：`report_gate` 的 evidence payload 并入图表数值（与 baseline rows 同模式），图表中任何不在分析结果中的数值被拒。白名单图表由渲染层从已验证 rows 生成，天然溯源。

### D5. HTML 交付：前端生成自包含文件，后端不渲染

下载 HTML 由**前端**在下载时生成：复用现有 `renderMarkdown()` + vendored ECharts（`web/vendor/echarts.min.js`）+ 内联样式，产出单文件自包含 HTML；结果视图内嵌图表同样走 ECharts 在线渲染。后端零渲染改动，`report_publisher` 不动。
- 备选：后端渲染 HTML（report_publisher + 模板引擎）——被否：auto-029 已确立"下载/保存在前端"的先例，后端渲染引入模板依赖且与 localStorage 架构脱节。
- ECharts 以 vendor 文件引入（演示环境不依赖 CDN）。

### D6. 技能更新的最小面

`plan-drafting`：起草流程第 1 步扩"探索预览"动作与样本量判断；`analysis-methods`：执行循环增加图表数据产出动作（仅 python 路径）+ 解读检查加"图表数值同源"一问；`report-authoring`：渲染约定（白名单 result→图表配置映射、章节锚点即追问引用 ID）；`sandbox-python`：chart 键输出规范。不新建技能。

## Risks / Trade-offs

- [前端 app.js 为单写者文件，auto-029（13/14 完成）与前端进程都在改] → auto-031 前端任务在 auto-029 合并后开工；实施前 re-read 最新 app.js；冲突处按 AGENTS.md 协调，不静默覆盖。
- [ECharts vendored 体积约 1MB] → 仅 vendor 常用条形/折线/饼图所需主文件；下载 HTML 内联该文件，接受单文件体积。
- [图表数值溯源扩大 gate 校验面] → 图表数值并入既有 evidence payload，复用 `_matches_number` 通道，不新增校验器。
- [visualization 意图由模型填写，可能虚标] → 意图仅影响渲染选择，不影响数据正确性；渲染层对非法 type 回退表格。
- [时间切片候选固定四种可能不贴业务] → 切片规则集中在一处常量，调整零成本；spec 只约束"落在快照区间内"。

## Migration Plan

1. 后端先行：options 端点 + semantic_overview 扩展 + 计划 schema v2 + chart 数据（各自带确定性单测，互相独立可分批交付）。
2. 技能更新随对应后端能力同批交付（简报/工具说明与技能引用保持同源）。
3. 前端（auto-029 合并后）：选项卡片 → 大纲卡片 v2 → 图表渲染 → HTML 下载升级。
4. 回滚：各端点与前端功能独立，任一环节回滚不影响其余；计划 schema 的 visualization 为可选字段，旧计划兼容。

## Open Questions

- 时间切片候选（近 1/3/6 月 + 全部）是否满足演示需求——实现时可用真实快照核对后再定，规则已集中。
- ECharts 具体版本与 vendor 体积裁剪方式——实现时定，不影响接口。

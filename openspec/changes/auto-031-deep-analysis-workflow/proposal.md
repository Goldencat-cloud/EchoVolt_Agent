# Proposal: auto-031-deep-analysis-workflow

- **Change ID**: auto-031-deep-analysis-workflow
- **Owner**: 人类 Owner（2026-10-28 授权立项，并裁定本文五项业务决策；署名待补记）
- **状态**: 规格评审 **待定**（本 proposal 与 delta specs 尚未经 GPT 评审与 Owner 终审）
- **授权实施记录**（2026-10-28，Owner 在会话中裁定）：后端任务 1.x-3.x 按 Owner 当日指示"依赖顺序全做"视为 Owner 授权实施——前置 auto-030 8.4/8.5 已于同日交付；GPT 评审与 Owner 终审**仍待执行**，实施产物以上述授权为临时依据，评审通过前不合并、不归档、不 sync specs（见 Workflow follow-up）。前端 4.x 未授权（仍锁 auto-029 合并）。

## Why

深度分析的后端门禁与上下文重构（auto-030）交付的是"引擎能力"：澄清、大纲门禁、执行循环、溯源报告。但业务闭环还缺四段用户可见的链路——结构化的意图澄清输入、正式的数据探索步骤、给人看的大纲与执行步骤分离、以及带可视化的 HTML 报告交付。Owner 于 2026-10-28 梳理了完整业务流程（提问→澄清→探索→草案→审核→分析→报告→存档追问），本 Change 将该流程落地为可演示的产品能力。

## What Changes

- **意图澄清选项化**：新增选项目录数据源（分析对象清单、时间范围切片），与 Agent 任务简报同源生成。分析对象为多选壳（当前仅小米 SU7 一项，见决策 2）；分析主题与具体问题为**用户自由填写**，由 Agent 自行识别映射到议题维度——**不做**上层主题选项卡与预置子题库（决策 1）。
- **正式探索步骤**：`semantic_overview` 扩展按议题过滤的预览能力（样本量、时间分布、代表性观点），计划起草前 Agent 可合法探索；外部搜索工具**本期不做**（决策 3）。
- **双文档草案**：分析计划升级为"大纲（供用户审核的人读结构）+ 执行步骤（供 Agent 的 method/aspect/可视化意图）"双层结构；大纲审查卡片直接渲染大纲层。
- **图表数据能力**：`python_analyze` 支持返回图表数据 JSON；沙箱禁 I/O 约束不变；报告携带图表数据。
- **HTML 报告交付**：报告渲染为 HTML（Markdown 正文 + ECharts 图表，前端渲染），用户下载物从 Markdown 升级为 HTML 文件；report_gate 数字溯源校验**不变**（仍作用于结构层）。
- **报告存档接线**：复用 auto-029 的「我的报告」（localStorage）与结果视图，仅将下载物升级为 HTML；**不新建**后端报告清单端点（沿用 auto-029 演示场景决策）。
- 依赖引用：大纲审查门禁机制沿用 auto-030 tasks 8.4/8.5（方案 B `interrupt_on`），本 Change 不重复设计门禁。

### Owner 已裁定的业务决策（2026-10-28）

1. 具体问题由用户自由填写；不做上层主题选项与预置子题库，Agent 自行识别问题。
2. 分析对象仅 SU7；多选为通用能力壳，表面支持、实际单选项，多品牌待数据支持后启用。
3. 外部搜索工具本期不做、延后。
4. 可视化采用图表数据 JSON + 前端 ECharts 渲染（不引入 matplotlib 出图）。
5. 独立立项为本 Change，不并入 auto-030。

## Capabilities

### New Capabilities

- `deep-analysis-workflow`: 深度分析业务工作流的用户可见能力——结构化澄清选项与 Agent 上下文同源、探索预览、双文档草案（大纲+执行步骤）、图表数据产出与 HTML 报告交付、下载物升级。与 auto-030 的 `deep-analysis-agent`（门禁与 Agent 行为）互补：本能力管"业务流程形态"，不重复门禁状态机与溯源规则。

### Modified Capabilities

（无——`openspec/specs/` 当前为空，auto-030 的 `deep-analysis-agent` 尚未归档为正式规格；本 Change 与其交付顺序在 design 阶段约束。）

## Impact

- **后端 `08_semantic_services/`**：`app.py` 新增选项目录端点；`task_brief.py` 生成器扩双消费者（表单选项 + Agent 简报同源）；`agent_tools.py` 计划 schema v2（outline + visualization）；`sandbox.py` 图表数据返回；`report_publisher.py` HTML 渲染（Markdown→HTML）。
- **技能**：`plan-drafting`（双文档草案规范）、`analysis-methods`（图表数据产出动作）、`report-authoring`（HTML 渲染约定）、`sandbox-python`（图表数据输出规范）。
- **前端 `web/`**：澄清选项卡片、大纲审查卡片 v2（渲染大纲层）、ECharts 渲染、结果视图下载升级为 HTML（需与 auto-029/前端进程协同）。
- **依赖**：前端新增 ECharts；后端无新增依赖。
- **排他**：不改 report_gate 溯源校验语义；不做多品牌数据分支；不做外部搜索；不做后端报告清单。

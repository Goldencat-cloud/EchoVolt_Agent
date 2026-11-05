# Tasks: auto-031-deep-analysis-workflow

前置：auto-030 tasks 8.4/8.5（方案 B 大纲门禁）先行交付；前端任务在 auto-029 合并后开工（app.js 单写者约束，见 design Risks）。

## 1. 选项目录与探索预览（后端）

- [x] 1.1 `task_brief.py` 增加 `form_options()`：分析对象（品牌清单，当前仅 SU7）与时间范围候选（近 1/3/6 月 + 全部，校验落在快照区间内），与简报覆盖声明共用 `snapshot_coverage`/`resolve_brand_scope`。验证：确定性单测断言对象、时间切片与简报同源且落在快照区间。（实施注：2026-10-28 落地；时间切片由 date_max 确定性回溯 `_shift_months_back`，早于 date_min 的切片自动剔除；测试 `tests/test_analysis_options.py::FormOptionsTests`）
- [x] 1.2 `app.py` 新增 `GET /api/analysis/options` 返回 `form_options()` 结构。验证：接口测试断言对象/时间字段与简报覆盖声明一致。（实施注：2026-10-28 落地；端点测试 `AnalysisOptionsEndpointTests` 断言 subjects/version/时间区间与 snapshot_coverage 一致）
- [x] 1.3 `semantic_overview` 工具扩展可选 `aspects` 参数：返回指定议题的精选证据样本量、按月计数分布、代表性观点（top 3 带 claim_id），口径标注与简报一致；更新工具 docstring（计划阶段专用边界）。验证：单测断言三段数据在场、口径标注正确、非法议题名报错。（实施注：2026-10-28 落地——服务层 `research/service.aspects_preview`（样本量/按月分布/代表性观点 top3 带 claim_id，`support_insufficient`=<5 标注，caliber 与简报同源声明）；工具层 aspects 参数（JSON 数组字符串，坏 JSON/空数组/非法议题名返回 error JSON）；不传参数保持旧 frames 概览；测试 6 项）
- [x] 1.4 `plan-drafting` 技能起草流程第 1 步扩"探索预览"动作：何时调预览、样本量 <5 条须标注支撑不足或剔除。验证：技能文本与工具 docstring 引用一致。（实施注：2026-10-28 落地；插入为新步骤 2"探索预览（按需，至多一次）"——预览用于支撑判断、<5 标注或剔除、NEVER 据预览下结论；后续步骤编号顺延）

## 2. 计划 schema v2（后端）

- [x] 2.1 `agent_tools.py` 计划校验器接受 workstream 可选 `visualization` 字段（type ∈ bar/line/pie/table，x/y/title），非法值拒绝；旧计划（无该字段）兼容。验证：单测覆盖合法/非法/缺省三种计划。（实施注：2026-10-28 落地——校验器对 visualization 归一化（type ∈ `task_brief.VISUALIZATION_TYPES`，x/y/title 截断入库）并随工具 docstring 更新；测试合法/非法/缺省三路径）
- [x] 2.2 大纲投影函数：workstreams → 大纲条目（子问题表述 + 可视化描述 + 顺序），供大纲卡片与门禁共用；确认无独立大纲存储。验证：单测断言投影与 workstreams 一一对应、编辑 workstream 后投影同步。（实施注：2026-10-28 落地——`task_brief.outline_projection`（纯函数投影，无独立存储）；大纲门禁待审 payload 已携带投影（`report_session._spawn` awaiting 分支），编辑 workstream 后经 2.3 重过校验器即自然同步；投影形状单测）
- [x] 2.3 编辑同步校验：审查动作（confirm/edit/regenerate，方案 B resume）对编辑版计划重过校验器时覆盖 visualization 字段。验证：接口测试——编辑删除子问题后执行层同步、编辑 visualization 后校验通过。（实施注：2026-10-28 落地——edit 决定以 `edited_action` 执行 `submit_analysis_plan` 工具（spike 已证），校验器为同一次调用 → 编辑版计划（含 visualization）自动重过同一校验器，无需新代码；outline edit 端点测试（test_outline_gate）+ visualization 校验单测覆盖"编辑后校验通过"；"编辑删除子问题后执行层同步"端到端依赖前端 4.3，归入 5.1 验收）

## 3. 图表数据（后端）

- [x] 3.1 `sandbox.py`/`agent_tools.py`：python_analyze 返回值支持可选 `chart` 键（type/title/x_label/y_label/data JSON），透传进 verified_steps 结果；沙箱禁 I/O 等约束不变。验证：单测——含 chart 与不含 chart 两种返回、超限与非法 chart 结构被拒或降级。（实施注：2026-10-28 落地——wrapper 提取 `chart` 变量（不可序列化→chart_error）；`agent_tools._validate_chart`：type ∈ 四类 + title 必填 + JSON 总长 ≤20KB，非法/超限降级丢弃并加 `chart_invalid_dropped` 警告（不使结果失败）；合法 chart 随 `_record_step` 进入 verified_steps；测试透传/非法 type/缺 title 三路径）
- [x] 3.2 `report_gate.py`：evidence payload 并入图表数值，图表中不存在于分析结果的数值触发"来源外数字"拒绝。验证：单测——图表数值与表格同源通过、伪造图表数值被拒。（实施注：2026-10-28 落地——python 步骤的 `result`（含 chart）本就整体进入 `_evidence_payload`，图表数值自动受数字溯源约束；单测：图表数值引用通过、同批编造数值被拒，验证了该通道）
- [x] 3.3 技能同步：`analysis-methods` 执行循环加"图表数据产出"动作与"图表数值同源"解读检查项；`report-authoring` 加白名单 result→图表配置映射规则与章节锚点说明；`sandbox-python` 加 chart 键输出规范。验证：三份技能文本与工具 docstring/校验行为一致。（实施注：2026-10-28 落地——analysis-methods 新增步骤 6"图表产出"（visualization.title/格式转换不重算/同源检查=gate 拒绝图表编数）；report-authoring 新增"图表规则"（标题取计划、章节锚定、数值同源、业务词标签）；sandbox-python 核心流程新增第 4 步 chart 键规范（结构/20KB/降级约束））

## 4. 前端交付（auto-029 合并后开工；app.js 单写者）

- [ ] 4.1 vendor ECharts 到 `web/vendor/`，结果视图按计划 visualization 意图与 python chart 数据渲染图表，非法 type 回退表格。验证：真实报告数据渲染条形/折线图，回退路径可见。
- [ ] 4.2 澄清选项卡片：深度分析表单接入 `GET /api/analysis/options`——对象多选（仅 SU7）、时间范围切片选择、主题与具体问题自由填写框。验证：选项数据与端点一致、自由填写可提交进 brief。
- [ ] 4.3 大纲审查卡片 v2：渲染大纲投影（子问题 + 可视化描述），编辑动作作用于 workstreams 并走既有审查三动作。验证：编辑删除子问题后 resume 的计划同步（与 2.3 联动）。
- [ ] 4.4 下载升级：结果视图下载从 .md 改为自包含 HTML（renderMarkdown + 内联样式 + 内联 ECharts + 图表数据）。验证：下载文件离线打开可见正文分节与图表；localStorage「我的报告」记录兼容旧记录。

## 5. 集成验收

- [ ] 5.1 端到端走查：提问 → 选项化澄清 → 探索预览 → 双层草案 → 审核编辑 → 执行（含图表）→ HTML 报告 → 下载/存入我的报告/引用追问。验证：验收记录（含截图或导出文件）入本目录。
- [ ] 5.2 回归：全套后端测试无新增失败；report_gate 溯源行为（正文+图表）回归通过。验证：测试输出记录。

## Workflow follow-up

- 规格评审：proposal 与 delta spec 经 GPT 评审 + Owner 终审后方可实施（后端 1.x-3.x 已按 Owner 2026-10-28 会话授权先行实施，见 proposal 授权记录；评审仍需补做）。
- 交付 PR 合并、Owner 验收后，按流程归档并同步 specs。**归档顺序硬约束**：必须先归档 auto-030（使 `specs/deep-analysis-agent/` 落地），再归档本 Change——本 Change 的 delta 对 `deep-analysis-agent` 使用 MODIFIED 操作，目标 spec 不存在时 `openspec validate` 报归档阻断 INFO（2026-10-28 已验证）。

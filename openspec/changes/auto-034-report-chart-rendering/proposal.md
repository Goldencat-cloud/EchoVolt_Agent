# Proposal: auto-034 报告可视化——已验证数据的服务端 SVG 渲染

## Why

用户反馈"报告可视化不足"。现状：auto-031 计划 schema v2 已支持工作项级 visualization 意图（bar/line/pie/table），python_analyze 结果也支持 gate 校验过的 `chart` 数据（数值并入数字溯源），但**发布端无任何渲染**——已发布报告只有表格，计划与执行中的图表数据停留在 provenance.json 里未被消费。

## What Changes

- 新增 `report_charts.py`：stdlib-only SVG 渲染（条形图/折线图），数据仅来自已验证步骤（方法步骤 rows / python chart），与正文数字同源；无对应已验证数据的工作项跳过渲染，不画无依据的图。
- `render_published_html` 集成：图表按标题锚进对应章节元素之后，找不到锚点入文末"图表"附录；附数据来源说明。
- `latest_published` 返回值附加 `provenance` 键（向后兼容的加法修改）。

## Impact

- Affected specs: `report-orchestration`（新增 1 个 Requirement，2 个 Scenario）
- Affected code: `report_charts.py`（新增）、`report_publisher.py`、`tests/test_report_charts.py`（新增）
- 不改动：Agent 行为、gate 校验、报告正文 markdown（图表仅在发布 HTML 渲染层）。
- 边界：不画无已验证数据支撑的图；pie/table 类型暂不渲染（表格已由 markdown 承载）。

## Review

- Owner: 人工（用户 2026-10-28 指示"报告可视化不足"，据此授权实施）
- Verdict: 待人工验收

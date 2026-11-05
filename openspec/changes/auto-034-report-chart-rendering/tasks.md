# Tasks: auto-034 报告可视化

- [x] 1.1 新增 `report_charts.py`：charts_for（计划意图 → 已验证数据 → SVG）、bar/line 渲染、python chart 优先于方法 rows、无数据跳过
- [x] 1.2 `latest_published` 附加 provenance；`render_published_html` 经 `_insert_charts` 锚进对应章节（找不到锚点入文末图表附录）+ figure 样式
- [x] 2.1 新增 `tests/test_report_charts.py`（6 用例：方法 rows 条形、python 折线、无数据跳过、非数值跳过、章节锚定、孤儿图表附录）
- [x] 2.2 真实数据冒烟：样例报告 745938b60175 渲染出 2 张图；e2e 报告 1632afb36aa1 的 python chart 被正确消费
- [x] 2.3 回归：报告链路 68 个测试通过
- [x] 2.4 复现并修复 gate 误判 bug（E2E 2026-10-28）：「### 2.1 标题」式小节编号被数字溯源当成未溯源数字，拒绝理由噪音可耗尽 3 次提交机会 → job failed（前端"深度分析未完成"）。修复：report_gate 剥离标题标记与行首多段小节编号后再做数字比对；回归测试 `tests/test_report_gate_numbers.py`（3 用例，含编造数字仍须拒绝）
- [x] 2.5 Owner 2026-10-28 裁定：对比矩阵/归因分析不再强制——章节是否必要由问题本身决定。report_gate 将类型注入章节（对比型→对比矩阵、趋势型→归因分析）从阻断错误降级为建议性 warning；核心三段（结论摘要/证据与归组/限制与不确定性）仍必填；test_task_brief 对应用例同步修订
- [x] 2.7 Owner 2026-10-28 反馈"草案没法修改、捆绑不相干议题"：①大纲卡片增加编辑入口——条目带保留勾选框，"按勾选修改"走后端既有 `action:"edit"` 契约（移除未勾选工作项、重排 id、重新过计划校验器，模拟验证 6→4 通过）；②plan-drafting SKILL 拆解规则收紧——数量由问题决定（6 是上限不是目标），逐项自查"删掉后问题是否仍完整"，趋势类问题以时间维度工作项为主，NEVER 为覆盖面凑无关议题
- [x] 2.8 Owner 2026-10-28 反馈"明确要求画图仍未生成图片"：根因=图表只渲染在发布视图（render_published_html），用户实际看到的报告视图（report_md）从未收到图表。修复：report_outcome 结果附带 charts（report_charts 从已验证步骤渲染，与发布视图同源）；前端 saveReport/showReport 渲染图表区；plan-drafting 增加"用户要求图表时对应工作项 MUST 声明 visualization（占比→bar、走势→line）"。验证：新增 4 个单测（result 下发/空意图/table 类型跳过/编造数字仍拒），报告链路全量回归通过；e2e 实测"22-26年需求趋势变化图"→ done，charts=2（占比 bar + 月度走势 line），charts_expectation=PASS；边界与异常场景由单测覆盖（无可视化意图→空数组、table 类型→不渲染、无已验证数据→跳过、非数值行→跳过、python chart 优先、孤儿图表入附录）
- [x] 2.9 运维：清理并存的多只 app.py 实例（Windows SO_REUSEADDR 允许同端口重复绑定，netstat 出现双 LISTENING），重启为单一实例并冒烟通过
- [x] 2.10 Owner 2026-10-28 前端 bug 三连修（浏览器实测验证）：①报告页闪烁——resumeLiveJob/重试/新启动可并存两个 pollJob 循环，交替覆写 #result-view；修复：pollSeq 轮询序号，旧循环每个 tick 检查、过期即退出；②大纲勾选框/编辑按钮显示异常——`.deep-form input`/`.deep-stage-card input` 全局表单样式把 checkbox 渲染成 100% 宽不可见块；修复：选择器排除 `[type="checkbox"]` + `.outline-keep` 专属样式，浏览器实测 15×15、checkVisibility=true、编辑按钮在位；③深度分析自动填写过期——askReport（@报告 问答）不更新 currentQuestion，之后点「深度分析」填入旧问题；修复：askReport 同步更新 currentQuestion；chip 路径自动填写实测正常
- [x] 2.11 Owner 2026-10-28 追加反馈"自动填写应取输入框正在输入的内容"：深度表单打开时优先取 #question 输入框当前未发送文本，为空才回退最近一次提问；浏览器实测两路径均正确。确认静态资源每请求读盘（app.py _static → read_bytes），前端修复无需重启服务；后端修复已随上轮重启生效
- [x] 2.12 Owner 2026-10-28 反馈"图表溢出"：根因双因——SVG 无 viewBox（窄容器缩视口裁内容）+ styles.css 缺 figure.report-chart 缩放规则（该规则此前只写在发布视图内联 style）。修复：bar/line SVG 加 viewBox、右边距 +70；styles.css 补 max-width:100%/height:auto/题注样式。验证：单测断言 viewBox（9 用例通过）；浏览器实测 575px 容器 → SVG 等比缩至 575、fits=true、16 个百分比标签齐全
- [x] 2.13 Owner 2026-10-28 反馈"图表应嵌入对应文字段落"：前端 showReport 新增 embedCharts（与发布视图 _insert_charts 同构）——按图表标题/议题文本匹配正文元素，figure 插到其后；找不到锚点才入文末「图表」附录。浏览器实测：锚定路径（figure 紧跟"表：各议题负向观点占比…"段落）与孤儿兜底路径（入附录）均正确
- [x] 2.14 Owner 2026-10-28 反馈"正文大量裸露 claim_id"：不删除（gate 证据闭包与附录解析依赖），改为呈现层折叠——report_outcome 随结果下发 evidence_index（claim_id→原帖 URL/日期/标题/议题/情感/归属/亲历）；前端 decorateCitations 把正文 `(claim_id: hex)` 折叠为 `[n]` 角标（悬停显示原帖信息、可点击跳原帖），文末附可展开"证据引用编号"清单；发布视图 _decorate_citations 同构实现。report.md 原文不变、gate 证据闭包不受影响。验证：发布视图单测（角标+清单+原帖链接，143 测试全过）；浏览器实测 rawGone=true、[1] 角标带链接与悬停信息、清单含原帖链接
- [ ] 3.1 Owner 通读渲染样例并验收（人工验收项）

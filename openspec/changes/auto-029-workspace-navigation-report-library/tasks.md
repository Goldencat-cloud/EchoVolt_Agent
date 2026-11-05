# Tasks

## 1. 外壳与侧栏

- [x] 1.1 重构 index.html：侧栏（官方报告 / 我的报告 / 短线分割 / 对话历史，入口无子列表）+ 主区视图容器（chat/report/official/library/result）
- [x] 1.2 styles.css：侧栏、分区标题、激活态、短线分割、版本标识样式（沿用既有令牌）
- [x] 1.3 响应式：<1024px 抽屉化 + 遮罩 + 顶栏菜单按钮；触屏目标 ≥44px

## 2. 视图路由与对话历史

- [x] 2.1 app.js：hash 路由扩展为 chat/official/library/result/report，兼容 #report/#analyze 旧链接
- [x] 2.2 会话持久化：`ai_sessions` 最多 5 条、淘汰最早；会话项显示标题与时间
- [x] 2.3 会话切换与新建：恢复消息流、延续 sessionId；新建对话入列
- [x] 2.4 localStorage 不可用时降级为内存态

## 3. 结果视图与报告库

- [x] 3.1 结果视图：标题/状态/数据版本/关键结论置顶/正文分节渲染
- [x] 3.2 下载报告：导出 Markdown 文件（Blob）
- [x] 3.3 `ai_reports` 保存（最多 10 条）并驱动「我的报告」卡片网格；卡片可查看与下载；官方报告卡片（含打开阅读）
- [x] 3.4 修复 `#doc-status` 缺失缺陷；分析进行中显示阶段进度，失败显示三段式错误

## 4. 验证

- [x] 4.1 后端 unittest 全量通过（99 tests，仅剩 2 个既有数据复核失败，与前端无关）；`test_static_index_served` 断言同步新外壳
- [x] 4.2 服务重启后验证：静态资源 200、/report/full 200、/api/reports/published/latest 行为符合预期；页面预览打开
- [ ] 4.3 Owner 视觉验收

# Design

## 布局结构

```
┌────────────┬──────────────────────────────┐
│ 侧栏 240px │  主区（hash 路由视图）        │
│ ───────────│  #/chat       对话 + 输入     │
│ 官方报告   │  #/report     官方报告阅读    │
│ 我的报告   │  #/official   官方报告卡片   │
│ ────────   │  #/library    我的报告卡片   │
│ 对话历史   │  #/result     报告结果视图    │
│  · 会话项  │                              │
│ ───────────│                              │
│ 版本标识   │                              │
└────────────┴──────────────────────────────┘
```

- 侧栏只有三个入口项，不展示报告子列表；官方/我的报告内容在主区以卡片呈现。
- 视图沿用 `data-active-pane` + hash 路由；兼容旧链接：`#report`→官方报告阅读、`#analyze`→对话。
- 状态存储（localStorage）：
  - `ai_sessions`：会话数组，最多 5 条，每条 `{id, title, updated_at, messages:[{role:'user',text}|{role:'bot',data}]}`；淘汰最早。
  - `ai_reports`：报告数组，最多 10 条，每条 `{report_id, title, markdown, key_findings, data_version, question, saved_at}`。
- 会话消息按原始数据存储（用户存文本、回答存响应 JSON），切换时用 `renderAnswer` 重渲染，避免存 HTML 造成注入与体积膨胀。

## 侧栏收起 / 展开

- 桌面端（≥1024px）：侧栏头部「«」按钮收起；侧栏宽度 248px→0 平滑过渡（220ms），内层固定 248px 宽避免文字重排；主区 flex 自动补满，内容重新居中。
- 收起态：主区左上角出现「»」浮动入口（34px，surface 底 + 细边），点击恢复完整侧栏；收起时侧栏设 `inert`，避免 Tab 焦点进入不可见区域。
- 状态持久化于 `ai.sidebar`（collapsed/expanded），刷新后保持。
- 窄屏（<1024px）：不使用收起态，保持抽屉 + 遮罩；收起/展开按钮均隐藏，由「☰」承担。

## 卡片视图

- 官方报告（`#/official`）：一张卡片——标题、数据版本、发布时间、"打开阅读"按钮（→ `#/report` iframe）；`/api/reports/published/latest` 404 时展示内置研究报告（auto-023）卡片。
- 我的报告（`#/library`）：卡片网格（自适应 minmax(260px,1fr)），每张卡片：标题、数据版本、保存时间、关键结论前 2 条摘录、"查看"/"下载"按钮；空状态给出说明。
- 卡片样式：surface 底、细描边、hover 上浮 1px，与品牌令牌一致。

## 对话主区（DeepSeek 风格）

- 空状态：品牌标记居中 + 问候语 + 建议胶囊（pill）；范围说明居中小字。
- 消息流居中列（≤768px）：用户消息为浅色气泡（accent-100）右对齐、16px 圆角；回答不带卡片边框，左侧 30px 品牌头像（brand-900 "A"）。
- 输入区：底部居中悬浮圆角胶囊框（≤768px 宽），输入框无边框内嵌，右侧 40px 圆形渐变发送键；focus-within 光环。

## 结果视图

- 头部：标题 + 状态标签（待审核/已保存）+ 数据版本 + 下载按钮（Blob 下载 `AutoInsight报告-<标题>.md`）。
- 关键结论置顶卡片（`key_findings`），正文 `renderMarkdown` 分节渲染，保留口径与证据链接样式。
- 深度分析进行中：同视图显示阶段进度（`publicPhase`）；失败：显示三段式错误与重试。
- 深度分析完成后 `saveReport()` 写入 `ai_reports` 并刷新侧栏「我的报告」列表。

## 组件与样式

- 侧栏：surface 底 + 右侧 1px 分隔线；分区标题 11px 大写字距；当前项 accent-100 底 + 左侧 2px 强调线；分割线用 1px `--line`（视觉上的"短线分割"）。
- 品牌令牌全部沿用 tokens.css（夜航蓝/电光蓝/香槟金），不新增色值。
- 响应式：<1024px 侧栏 `position:fixed` + `translateX(-100%)`，`.sidebar-open` 时滑出，遮罩点击关闭；触屏目标 ≥44px。
- 无障碍：侧栏 `nav aria-label`，分区 `h2.sr-only`，激活项 `aria-current="page"`，抽屉开关 `aria-expanded`。

## 交互细节

- 切换会话：恢复消息流并把 `sessionId` 指向该会话，后续消息追加到同一会话。
- 新建对话：生成新 session；仅在发出第一条消息时写入历史。
- 会话项标题取首条提问前 24 字；显示相对时间。
- 官方报告视图保留引用跳转（cite → iframe 锚点）逻辑。

## 兼容与风险

- localStorage 不可用（隐私模式）：降级为内存态，功能不报错。
- 旧版 iframe 引用跳转、`report-skin.css` 不改动。
- 现存缺陷修复：`#doc-status` 元素在结果视图中补齐。

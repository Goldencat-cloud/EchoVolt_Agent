# Design —— 深度分析 Agent（代码解释器）

## 1. 流程与组件

```
用户问题
  │
  ├─ /api/question → 上下文对话 Agent（LangChain create_agent，不做独立意图分类）
  │                    ├─ 直接回答交流、追问或解释统计来源
  │                    ├─ 按需查询统计 / 检索证据 / 检索已发布报告
  │                    └─ 按需调用语义层代码解释器进行在线分析
  │
  └─ 用户显式生成完整报告 → POST /api/agent/report
        │
        ▼
   DeepAgents（create_deep_agent：计划中间件 + 工具循环，仅用于完整报告）
        │  指令 = 四阶段工作流（探索→草案→代码分析→提交报告）
        ▼
   工具集（agent_tools，错误回传模型自愈）
     semantic_overview     语义层数据结构 + 口径说明
     run_analysis_method   白名单方法（参数化 SQL，经语义白名单校验）
     python_analyze        代码解释器沙箱（pandas 已预载）
     get_negative_evidence 精选证据（claim_id/引文/链接）
     submit_report         报告提交契约（落盘 reports/agent/<id>/）
        │
        ▼
   沙箱（sandbox.py）：AST 拦截 + 子进程隔离 + I/O 封禁 + 超时/输出上限
        │  预载数据框全部来自语义层视图
        ▼
   报告（Markdown）+ 分析日志（工具调用/代码/输出）→ 前端实时页签渲染
```

互动分析不经过独立意图分类器。完整报告仍使用受计划和发布门禁约束的报告 Agent；用户可显式调用确定性报告端点。

## 2. 关键决策

1. **语义层是唯一数据边界**（Owner 约束）：SQLite 镜像中原始表以 `_raw` 前缀私有，
   仅 `semantic_aspect_metric / semantic_claim_fact / semantic_claim_evidence /
   semantic_post_scope / semantic_snapshot_meta` 视图对 Agent 可见；
   `analysis_methods.assert_semantic_only` 在执行前解析 SQL 的 FROM/JOIN，
   校验器复核已执行 SQL——两道防线。
2. **代码解释器而非纯预置方法**：开放性问题（"集中在哪里"）需要归组、聚合、交叉，
   预置方法覆盖不了；沙箱让模型写 pandas，但数字必须出自代码结果。
3. **工具错误回传而非抛出**：LangGraph 默认把工具异常向上抛、杀死整图；
   `@guarded` 把异常变成 JSON 错误消息，模型可读取并自愈（实测：模型第一次写了
   `import pandas`，被拦后自行修正）。
4. **提交契约**：Agent 必须调用 `submit_report` 恰好一次；引擎从提交中取报告，
   未提交则以最终消息兜底并标记 `ok=false`。
5. **DeepSeek 直连**：`ChatOpenAI(model=AI_MODEL, base_url=AI_BASE_URL)`，
   temperature=0，recursion_limit=80，实测单次 30-90s。
6. **对话 Agent 与报告 Agent 分开选型**：互动入口使用 LangChain `create_agent` 和精简的 `CONVERSATION_PROMPT`；不加载 DeepAgents 的计划、文件或子 Agent 中间件。完整报告入口继续使用 DeepAgents 和发布门禁。互动工具不要求先提交报告计划。

## 3. 沙箱防护（本地演示级）

| 防护 | 实现 |
|---|---|
| import 拦截 | AST 遍历拒绝 Import/ImportFrom |
| 危险调用 | open/exec/eval/compile/__import__/input/breakpoint 拒绝 |
| dunder/系统调用 | `__` 前缀属性与 system/popen/remove 等属性拒绝 |
| pandas I/O | wrapper 内把 read_*/to_* 全部替换为报错函数 |
| 资源 | 子进程 `-I` 隔离、20s 超时、输出 8KB 截断 |
| 语义层可见性 | 数据框仅由 `semantic_*` 视图构建 |

已知限制：无容器级隔离；`pd.read_csv` 类 I/O 靠 wrapper 补丁拦截（非硬隔离）。
生产化路径：Docker/防火墙沙箱 + 资源配额。

## 4. 验证与回退

- 校验器（`verifier.py`）：口径声明、negativeShare 与 negative/claims 复算一致、
  与快照计数对账、精选条数不超过实际、空值/薄样本告警——深度 Agent 的方法调用
  与确定性管线共用。
- 回退链：`/api/agent/report` 失败 → 前端自动降级 `/api/report/live`（确定性模板报告）。

## 5. 职责承载方式（Owner 迭代）

Prompt 只承载角色与硬红线；其余由结构承载：

| 承载物 | 内容 |
|---|---|
| **工作流结构** | 阶段推进由编排代码驱动：预注入上下文、进度事件、递归上限、失败预算都是代码，不是提示词 |
| **Skills** | 四阶段工作流与口径红线写在 `agent_skills/deep-analysis/SKILL.md`，经 DeepAgents SkillsMiddleware 渐进披露（模型按需读取，不占常驻上下文） |
| **工具** | 五个白名单工具自带校验与口径声明；语义层白名单在执行与校验两处强制 |

## 6. 进度与监控

`jobs.py` 提供异步任务与阶段事件流（理解问题中 → 分析草案中 → 执行分析代码中 → 撰写报告中 → 已完成/失败）。
同一事件流有双重用途：前端轻量提示（轮询 1.5s）与监控/评估面（每次运行的阶段时序、
工具调用数、失败次数、最终结果全部可查，job 结果含完整分析日志）。

## 7. 失败处理（Owner 指示：失败显性化）

- 深度分析失败 → 前端直接呈现失败原因与重试按钮；**不自动回退**确定性链路
  （静默回退会让失败不可见，破坏监控与评估——Owner 2026-10-25 明确要求删除）。
- 确定性管线端点（`/api/report/live`、`/api/report/planned`）保留，仅作显式调用。
- 自愈预算化：工具错误回传模型自愈，但全局错误预算 6 次、同段代码失败 3 次即封禁重试，
  防止"无限修正循环"（行业事故：LangGraph Text-to-SQL 20 轮空转直到递归上限）。

## 8. 风险

- **[延迟/成本]** 预注入上下文后实测 ~35s 量级；进度提示缓解等待感；成本随调用次数可控。
- **[沙箱逃逸]** 本地演示级防护；Docker 化已交付构建物，上公网前在容器内运行并叠加资源配额。
- **[模型口癖]** 首轮 import 已由"指令强调 + 错误回传自愈 + 重试预算"三重兜住。

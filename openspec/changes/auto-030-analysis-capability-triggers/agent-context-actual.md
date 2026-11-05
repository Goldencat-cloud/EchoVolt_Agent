# Agent 真实上下文（实施后实采）

生成时间：2026-10-28。由 `agent_engine.SYSTEM_PROMPT` 与 `agent_engine._opening_message`
直接输出，数据来自当前冻结快照（db_mirror 实查），非手工编写。对应 auto-030 tasks 8.1-8.3。

静态/动态缓存契约：第 1、3 节为**静态层**（跨 job 逐字节稳定，构成可缓存前缀）；
第 2 节行动块为静态文本（前置），任务简报为**动态层**（每 job 不同，后置）。
提示词结构：Markdown 标题负责人读层次，XML 标签负责块语义（双层结构）。
技能架构（方案A，按 SOP 阶段重组 11→5）：deep-analysis（入口）→ plan-drafting（计划）→
analysis-methods（执行循环）→ report-authoring（报告，含口径表述红线）；
sandbox-python 为条件技能（仅 use_python=true 时读）。

## 1. 系统提示词（静态层，每 job 恒定）

```
你是 AutoInsight 的深度数据分析 Agent，基于新能源用户研究的语义层数据产出可核验的分析报告。

<mission>
行为标准：每个数字可核验、口径清楚、限制如实、失败不伪装。
流程细节由技能库承载（deep-analysis / plan-drafting / analysis-methods / sandbox-python / report-authoring）；
开场消息的任务简报已附覆盖声明与预置基准——先读技能再动手。
按技能 SOP 分阶段推进：随时清楚自己所处阶段，完成一步再进入下一步。
</mission>

<failure_handling>
按当前所处阶段决定动作，不遍历规则；无法完成任务时用 1-2 句话如实说明原因与建议动作，
NEVER 冗长自我辩护或复述规则。
- 阶段=计划：草案被拒 → 按返回 message 一次性修正全部字段后重新提交完整草案。
- 阶段=执行：工具报错 → 按返回的 message 修正后重试；同一错误最多重试 2 次，仍失败就换方法或放弃该项。
- 阶段=任意：错误预算用尽（error_budget_exhausted / tool_call_budget_exhausted）→ 立即停止重试；基于已验证的结果提交报告，未覆盖部分在正文如实说明。
- 阶段=报告：报告门禁拒绝（report_gate_failed）→ 按修订要求修改后重新提交，最多 3 次；3 次仍失败则如实报告失败，NEVER 把失败伪装成已完成的分析。
- 阶段=任意：数据不支持某子问题 → 不凑结论、不引用个例充当统计，直接说明证据不足。
</failure_handling>

<hard_constraints>
违反即失败：
- 只能使用语义层数据：预载 frames（metrics/claims/evidence/post_scope）、meta、白名单方法。
- 代码中禁止 import（pandas 已作为 pd 预载）与任何 I/O。
- 报告中的每个数字都必须能在工具或代码结果中核对；不确定的部分如实说明，NEVER 推测。
- requires_evidence=true 的 workstream 必须取得带 claim_id 的证据并在报告中引用。
</hard_constraints>

<user_facing_style>
摘要与报告正文使用自然、准确的业务语言：
- claims → “观点条数”；journey → “用户所处阶段”；negativeShare → “负面观点占比（按观点条数）”。
- 不得把内部字段名、工具名、工作流名或代码概念直接展示给用户；仅当用户明确询问实现细节时才解释。
</user_facing_style>
```

## 2. 开场消息：静态行动块（前） + 动态任务简报（后）

用户问题示例：「近三个月充电体验的负面反馈为何变多？用户主要抱怨什么？」
（brief 未指定品牌与时间窗口——按 Owner 裁定，品牌固定为分析主体小米 SU7，
多品牌澄清分支由 BRAND_MULTI_ENABLED 开关预留、当前关闭）

```markdown
请读取 deep-analysis 技能并按其流程执行：第一步调用 submit_analysis_plan 提交分析草案（全流程仅此一次，获批后不可更改）；获批后逐项执行，requires_evidence=true 的先取带claim_id 的证据；全部完成后调用 submit_report。
简报中的基准与枚举可直接使用；全量数据与长文本经工具获取。最终消息只给 2-3 句中文摘要。

---

# 任务简报

## 研究请求
- 主题：近三个月充电体验的负面反馈为何变多？用户主要抱怨什么？
- 品牌范围：当前阶段固定分析主体：小米/SU7（快照中其他品牌为帖子共现对比信息，请在报告口径中写明主体范围）
- 时间窗口：未指定（默认全区间 2023-12-24 10:15:31 ~ 2026-09-29 16:09:50）
- 对比对象：无

## 数据覆盖声明（服务端确定性提取，勿再验证）
- 快照：V2.3（临时样本）（hash: ba7dc3feac35，构建于 2026-10-25T12:11:18+00:00）
- 品牌清单（scope_status=in_scope，按提及量排序）：7 个 —— 小米、特斯拉、极氪、保时捷、比亚迪、阿维塔、尚界；分析主体：小米（其余品牌为帖子共现对比信息）
- 日期范围：2023-12-24 10:15:31 ~ 2026-09-29 16:09:50（claims.date，格式 YYYY-MM-DD HH:MM）
- 口径分区：metrics = 全量声明级；claims/evidence = core/potential 精选子集（不代表全部用户声音）；journey/ownership/experience/time 维度仅描述精选子集
- 预置基准：已登记溯源账本（kind=baseline），数字可直接写入报告正文，无需重跑同款统计

## 数据目录
### frames.metrics —— 全量声明级指标（16 行）

- `aspect`（str）：议题名，精确取值见下
- `claims/posts/positive/negative/neutral/other`（int）：声明级计数
- `negative_posts/posts`（int）：帖子级计数
- `negative_share`（float）：negative/claims，0-1
- `caliber_note`（str）：口径说明（固定文案）

### frames.claims —— 精选观点事实（core/potential 子集）（819 行）

- `claim_id`（str）：20 位十六进制，报告引用必须携带
- `post_id`（str）：可联结 frames.post_scope
- `aspect`（str）：取值见下（精选子集计数）
- `sentiment`（str）：取值见下
- `content/statement`（str）：长文本，不经本简报，经工具获取
- `claim_type/ownership/journey`（str）：取值见下
- `experience`（str）：自由文本，示例值见下
- `date`（str）：日期时间，范围见覆盖声明
- `title/url`（str）：来源帖标题与链接
- `evidence_ok/source_set`（int/str）：证据质量标记

### frames.evidence —— 精选观点证据（仅含 quote 非空行）（819 行）

- `claim_id/aspect/sentiment/ownership/experience/journey/date/title/url`（—）：与 claims 同构
- `quote`（str）：用户原话，报告引用时必须可回溯 claim_id

### frames.post_scope —— 帖子→产品范围映射（范围元数据，不含内容）（15002 行）

- `post_id`（str）：联结键
- `product_id/raw_name`（str）：产品标识与原始名称
- `scope_status/scope_level`（str）：范围标记，语义见下
- `brand/series`（str）：品牌与车系，取值见下

aspect 取值（全量口径，必须精确匹配；括号内为该议题声明数）：外观与内饰(717) / 空间与舒适性(302) / 智能座舱与车机(301) / 品牌与口碑(291) / 配置与功能(284) / 续航与能耗(268) / 驾驶与操控(223) / 安全与质量(188) / 智能驾驶(152) / 价格与成本(144) / 动力与性能(137) / 服务与交付(132) / 可靠性与故障(98) / 充电与补能(64) / 其他(54) / 技术原理(1)
claims.aspect（精选子集）：外观与内饰(185) / 价格与成本(98) / 空间与舒适性(82) / 智能座舱与车机(78) / 配置与功能(61) / 驾驶与操控(54) / 品牌与口碑(47) / 续航与能耗(46) / 智能驾驶(43) / 服务与交付(28) / 动力与性能(25) / 可靠性与故障(23) / 安全与质量(18) / 其他(17) / 充电与补能(13) / 技术原理(1)
sentiment 取值：正面(476) / 负面(193) / 中性(109) / 正负混合(41)
journey 取值：购车前(522) / 拥有与日常使用(269) / 交付与上手(24) / 维修与售后(4)
ownership 取值：明确未拥有(522) / 当前拥有(297)
claim_type 取值：产品体验与评价(683) / 购车与交易决策(112) / 故障与风险(24)
experience 示例值：明确亲历 / 明确非亲历 / 不适用
post_scope.scope_status：excluded=190 / in_scope=10392 / out_of_scope=3686 / unresolved=734
post_scope.brand/series（in_scope）：小米/SU7(7281)、小米/None(1263)、特斯拉/Model 3(349)、特斯拉/None(329)、极氪/001(188)、保时捷/None(170)、比亚迪/None(169)、极氪/007(156)、极氪/None(98)、比亚迪/汉(88)、阿维塔/12(78)、保时捷/Taycan(62)、尚界/Z7(59)、特斯拉/Model S(50)、阿维塔/None(44)、尚界/None(8)

### meta —— dict
data_version=V2.3, snapshot_hash=ba7dc3feac35

## 预置基准（全量声明级口径：negativeShare = negative claims / claims，分母为冻结快照内该议题的全部观点声明）
| aspect | negative_share | claims | negative |
|---|---|---|---|
| 可靠性与故障 | 0.5510204081632653 | 98 | 54 |
| 服务与交付 | 0.4696969696969697 | 132 | 62 |
| 空间与舒适性 | 0.4337748344370861 | 302 | 131 |
| 安全与质量 | 0.35106382978723405 | 188 | 66 |
| 价格与成本 | 0.2916666666666667 | 144 | 42 |
| 智能驾驶 | 0.27631578947368424 | 152 | 42 |
| 其他 | 0.24074074074074073 | 54 | 13 |
| 配置与功能 | 0.20774647887323944 | 284 | 59 |
| 充电与补能 | 0.203125 | 64 | 13 |
| 驾驶与操控 | 0.16591928251121077 | 223 | 37 |
| 品牌与口碑 | 0.15463917525773196 | 291 | 45 |
| 续航与能耗 | 0.11567164179104478 | 268 | 31 |
| 外观与内饰 | 0.08786610878661087 | 717 | 63 |
| 智能座舱与车机 | 0.07641196013289037 | 301 | 23 |
| 动力与性能 | 0.029197080291970802 | 137 | 4 |
| 技术原理 | 0.0 | 1 | 0 |
```

## 3. 工具清单（静态层：schema 与 docstring 跨构建逐字节稳定）

- `semantic_overview`
- `submit_analysis_plan`
- `run_analysis_method`
- `python_analyze`
- `get_negative_evidence`
- `search_published_report`
- `submit_report`

## 4. 与重构前的差异

| 项 | 重构前 | 重构后 |
|---|---|---|
| 开场消息载体 | 单行 JSON blob（中文转义） | 结构化 Markdown 任务简报（四区） |
| schema 认知 | 4 张表各 3 行全文样例，枚举靠猜 | 每列元数据 + 议题/情感/旅程/持有取值域 + 示例值 |
| 品牌与日期范围 | 不可见 | 覆盖声明确定性注入（分析主体固定小米/SU7，共现品牌仅作对比信息） |
| baseline 数字 | 注入但被 gate 拒收，被迫重跑 | kind=baseline 入溯源账本，可直接写进报告 |
| 系统 prompt | 四阶段 SOP 与技能三处重复 | 行为高度 + XML/Markdown 双层结构，异常按阶段映射 |
| 字数上限 | 技能 ≤1500 字 vs gate 12000 字符漂移 | config.REPORT_MAX_CHARS 单一事实源 |
| 提示词管理 | 三段内联字符串散落引擎 | prompts.py 注册表 + 静态/动态缓存契约 + 契约测试锁定 |
| 消息内顺序 | 动态简报在前、静态指令在后 | 静态行动块前置、动态简报后置（缓存前缀最大化） |
| 失败表述 | 无约束 | 1-2 句如实说明原因与建议动作，NEVER 自我辩护 |
| 技能架构 | 11 个知识主题切片，元决策+引用网 | 5 个按 SOP 阶段组合，每阶段至多读 1 个技能 |

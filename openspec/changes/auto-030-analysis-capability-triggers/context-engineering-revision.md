# 深度分析上下文工程修订方案（auto-030 设计附件）

状态：探索产出，待并入 design.md。日期：2026-10-27。
范围：`08_semantic_services/agent_engine.py`、`agent_tools.py`、`sandbox.py`、`report_gate.py` 中
深度分析 Agent 所见上下文的重构。不改变数据边界与门禁语义（P2 除外，见 2.2）。

## 1. 依据的原则

来源（2026-10-27 检索验证）：

- Anthropic, *Effective Context Engineering for AI Agents*（2025-09-29）
- Manus 上下文工程实践（社区整理版，KV-cache / append-only / 保留错误）

| # | 原则 | 要点 |
|---|---|---|
| C1 | 最小高信号 token 集 | 找到使期望结果概率最大化的最小高信号集合；罪在低信号填充而非长度 |
| C2 | 注意力预算 / context rot | 上下文是边际收益递减的有限资源；越长召回越不可靠 |
| C3 | Right altitude | 系统提示处于"过硬编码"与"过泛"之间的金发姑娘区间；行为指引只说一次 |
| C4 | 渐进披露 | 让 agent 分层自主发现上下文；元数据本身是行为精炼机制 |
| C5 | Just-in-time | 维护轻量标识符，运行时经工具动态加载；与少量预置（如 CLAUDE.md）混合 |
| C6 | 压缩 / 工具结果清除 | 长任务近上限时摘要重开；最安全的轻量形式是清除旧工具结果 |
| C7 | 结构化笔记 | 里程碑状态外置于上下文之外（文件/任务清单），按时拉回 |
| C8 | KV-cache 稳定前缀 / append-only / 保留错误 | 前缀逐 token 稳定；上下文只追加；错误留在上下文供自我修正 |
| C9 | 子代理隔离 | 脏活在独立窗口干，只回传精炼结论（本项目暂不需要，见 5） |

## 2. 现状问题 → 原则 → 修订

### 2.1 P1 枚举值与覆盖范围缺失（违背 C1/C5）——优先级 P0

**现状**：`semantic_frames_info()`（sandbox.py:230-254）对四张语义表各给列名、行数、3 行样例。
agent 拿不到 aspect 精确名称清单、品牌清单、日期范围与格式、sentiment/journey/ownership 取值域。
计划阶段拼错议题名烧错误预算；沙箱阶段猜列名/取值烧代码预算。

**修订**：overview 增加 per-column 元数据，服务端确定性生成：

- 枚举列：取值清单（含计数）；claims 侧枚举必须标注"来自精选子集"
- 日期列：min/max 与格式
- 品牌：`SELECT DISTINCT brand FROM semantic_post_scope` 提取
- 类型与口径注记（全量口径 / 精选子集）

**原则依据**：这是 C5 的混合模式（Anthropic 以 CLAUDE.md 为例）：预置"不可猜的最小集合"，
全量数据仍经工具 just-in-time 加载。枚举清单属于 schema（高信号、必预置），行数据属于内容（低信号、按需取）。

### 2.2 P2 baseline 数字过不了门禁（违背一致性）——优先级 P0

**现状**：baseline 由 `_baseline()`（agent_engine.py:100-109）服务端预生成注入开场消息，
SOP 允许直接引用（deep-analysis/SKILL.md:14,43）。但 report_gate 的数字溯源
（report_gate.py:63-79）只认 `verified_steps` 里的工具/代码结果——baseline 从不进入 verified_steps，
其数字写入报告即被判"来源外数字"拒收。结果：精心设计的预计算被门禁作废，
每次任务被迫重跑 baseline 同款统计，SOP 与门禁自相矛盾，模型在两份指令间摇摆。

**修订**：baseline 注入开场消息时同步记入 `verified_steps`（`kind: "baseline"`），
并满足 gate 校验路径（verifier 侧为该 kind 定校验规则）。预生成数字取得合法溯源身份，
SOP 的"NEVER 重新探索"恢复成立。报告侧不放松：baseline 数字仍须逐个可核验，只是账本多了合法来源。

### 2.3 P3 载体与噪声（违背 C1/C2）——优先级 P1

**现状**：`_opening_message` 是单行 `json.dumps` 大 blob（agent_engine.py:115-117），
中文长文转义；claims 样例行把 content/statement/title/url 全文带入——计划阶段需要 schema，不是三段用户原话。
输入侧注入无预算管理（沙箱输出侧反而有 8000 字符上限，sandbox.py:30）。

**修订**：开场消息重构为"任务简报"（完整示例见第 4 节）：

- Markdown 结构化分区，紧凑 schema 表替代整行样例
- 长文本字段一律不进简报；示例给"每列 2-3 个示例值"而非整行
- 简报总长设确定性上限（建议 4000 字符，超限优先裁剪示例值，永不裁枚举与覆盖声明）

### 2.4 P4 同一规则三处表述、已实际漂移（违背 C3）——优先级 P1

**现状**：四阶段 SOP 在 ROLE_PROMPT、开场消息尾部指令、deep-analysis SKILL.md 三处重复且措辞各异。
已发生漂移：report-authoring 说正文 ≤1500 字，report_gate.py:31 拒 >12000 字符。

**修订**：分层定则——

- 系统提示：只承载行为高度（角色、硬约束、异常处理原则），一次说清
- 技能库：承载流程细节与领域规则（渐进披露，现状已达标）
- 开场消息：只承载数据（简报），不再携带指令段
- 硬参数（字数、预算、上限）收敛到单一常量源，技能与 gate 引用同一处

### 2.5 P5 预算突停（违背状态可见性）——优先级 P2

**现状**：错误返回带 `error_budget_left`，但 18 次成功调用上限渐进耗尽时 agent 无感知，
直到突然 `tool_call_budget_exhausted`。

**修订**：成功响应尾部附轻量计数（如 `"budget": {"calls_left": 12, "errors_left": 5}`）；
达到 80% 阈值后响应附一行警告。确定性生成，不烧额外调用。

### 2.6 P6 长运行无压缩（违背 C2/C6/C7）——优先级 P2，观察后决定

**现状**：消息历史单调增长（证据最多 20 条带引文、python 输出 8K），128 层递归上限。
模型对早期注入（计划纪律、口径红线）的注意力随上下文膨胀而稀释。

**修订（暂缓）**：按"最简单可行"原则，先在真实任务上量化 token 曲线与失败相关性；
有数据后再选 C6（工具结果清除）或 C7（deepagents 文件系统 scratchpad 存中间结论）。
KV-cache 现状核对：系统提示每 job 恒定（稳定前缀满足）；消息流 append-only（langgraph 天然满足）；
错误留上下文（Manus "keep the wrong stuff in"，与现有自我修正设计一致，保持）。

## 3. 修订方案设计（决策）

- **D-CTX1 任务简报**：开场消息改为四区结构——研究请求 / 数据覆盖声明 / 数据目录 / 预置基准，
  后接一段行动指令（≤5 行）。执行段（方案 B resume 后）的简报另含已批准计划与进度账本。
- **D-CTX2 溯源合法化**：baseline 以 `kind: "baseline"` 入 verified_steps；gate/verifier 增加该 kind 的校验路径。
- **D-CTX3 单一事实源**：字数等硬参数收敛到 config；系统提示/技能/工具 docstring 分层去重，
  以工具 docstring 为校验规则的唯一权威（agent_tools 已是该角色）。
- **D-CTX4 简报生成器**：服务端新增确定性函数生成任务简报（同一函数同时服务表单校验的品牌/时间窗口清单，
  保证"用户看到的可用区间"与"agent 看到的覆盖声明"同源）。

## 4. 完整上下文示例（修订后）

### 4.1 大纲阶段开场消息（用户提交 brief 后）

````markdown
# 任务简报

## 研究请求
- 主题：近三个月充电体验的负面反馈为何变多？用户主要抱怨什么？
- 品牌范围：小米SU7（当前快照唯一品牌；用户未指定，系统已默认，请在报告口径中写明）
- 时间窗口：2025-08-01 ~ 2025-10-18（用户指定"近三个月"，落在快照覆盖区间内）
- 对比对象：无

## 数据覆盖声明（服务端确定性提取，勿再验证）
- 快照：V2.3（hash: a1b2c3d4e5f6…，构建于 2025-10-20）
- 品牌清单：小米SU7（仅此一个；post_scope.brand）
- 日期范围：2025-01-02 ~ 2025-10-18（claims.date 与 evidence.date）
- 口径分区：
  * metrics = 全量声明级（每议题 claims/posts/negative/negative_posts/negative_share）
  * claims / evidence = core/potential 精选子集（不代表全部用户声音）
  * journey / ownership / experience / time 维度仅描述精选子集
- 预置基准：已登记溯源账本（kind=baseline），数字可直接写入报告正文，
  无需重跑同款统计。

## 数据目录
### frames.metrics —— 全量声明级指标（17 行）
| 列 | 类型 | 说明 |
|---|---|---|
| aspect | str | 议题名，精确取值见下 |
| claims / posts / positive / negative / neutral / other | int | 声明级计数 |
| negative_posts / posts | int | 帖子级计数 |
| negative_share | float | negative/claims，0-1 |
| caliber_note | str | 口径说明（固定文案） |

aspect 取值（17 个，必须精确匹配）：
可靠性与故障(312) / 充电与补能(198) / 空间与舒适性(154) / 价格与性价比(141) /
智能驾驶(96) / 车机与互联(88) / 售后服务(71) / 外观设计(64) / 内饰用料(52) /
续航达成(47) / 动力操控(39) / 安全(31) / 交付与提车(22) / OTA与软件更新(18) /
保险与权益(12) / 用车成本(9) / 其他(6)
（括号内为精选证据条数，供覆盖度参考）

### frames.claims —— 精选观点事实（core/potential 子集，1024 行）
| 列 | 类型 | 说明 / 取值 |
|---|---|---|
| claim_id | str | 20 位十六进制，报告引用必须携带 |
| post_id | str | 可联结 frames.post_scope |
| aspect | str | 同上 17 值 |
| sentiment | str | 负面(617) / 正面(289) / 中性(118) |
| content | str | 观点陈述（长文本，不在本简报展示） |
| claim_type | str | 体验描述 / 求助投诉 / 对比评价 |
| ownership | str | 车主(703) / 关注者(241) / 未标注(80) |
| experience | str | 示例值：充电慢 / 表显不准 / 底盘异响…（自由文本） |
| journey | str | 购买决策(214) / 使用体验(589) / 售后维保(141) / 未标注(80) |
| date | date | 2025-01-02 ~ 2025-10-18，ISO 格式 |
| title / url | str | 来源帖标题与链接 |
| evidence_ok / source_set | int/str | 证据质量标记 |

### frames.evidence —— 精选观点证据（862 行）
列与 claims 基本同构，另含 quote（用户原话）；仅含 quote 非空行。

### frames.post_scope —— 帖子→产品范围映射（1830 行）
| 列 | 类型 | 说明 |
|---|---|---|
| post_id | str | 联结键 |
| product_id / raw_name | str | 产品标识与原始名称 |
| scope_status / scope_level | str | 范围标记 |
| brand / series | str | 品牌与车系（当前仅 小米SU7 / SU7） |

### meta —— dict
{"data_version": "V2.3", "snapshot_hash": "a1b2c3d4…", "built_at": "2025-10-20 14:32"}

## 预置基准（负向占比 Top 5，全量声明级口径；其余 12 个议题省略，需要时用工具查）
| aspect | negative_share | claims | negative |
|---|---|---|---|
| 充电与补能 | 0.472 | 198 | 93 |
| 可靠性与故障 | 0.441 | 312 | 138 |
| 售后服务 | 0.415 | 71 | 29 |
| 车机与互联 | 0.388 | 88 | 34 |
| 续航达成 | 0.371 | 47 | 17 |

---

请读取 deep-analysis 技能，然后调用 submit_analysis_plan 提交分析草案。
本预算：成功工具调用 ≤18，错误 ≤6。简报内的基准与枚举可直接使用；长文本与全量数据经工具获取。
````

**相对现状的变化**：17 个议题名及其计数、sentiment/ownership/journey 的取值域与分布、
日期范围、品牌清单、baseline 的溯源身份——这些原先 agent 只能从 3 行样例里赌的东西，
现在全部确定性给出；原先 3 行带全文的样例行被 schema 表 + 枚举替代；
口径分区与精选子集警示内嵌在元数据里，而不是只活在技能文件里。

### 4.2 执行阶段开场消息（大纲审查通过，方案 B resume 后）

````markdown
# 执行简报

计划已获用户批准（草案 v2，用户编辑过 w3 的时间范围）。按计划执行，NEVER 修改或重新提交计划。

## 已批准计划
{"coverage": "先取充电与补能负面占比与月度走势，再对负面最高的两个子话题取证据",
 "use_python": true,
 "workstreams": [
   {"id": "w1", "question": "充电与补能负面占比及月度走势（近三个月 vs 此前）",
    "dimension": "time", "aspect": "充电与补能",
    "method": "negative_claims_by_month", "requires_evidence": false},
   {"id": "w2", "question": "充电与补能主要负向说法",
    "dimension": "aspect", "aspect": "充电与补能",
    "method": "top_negative_claims", "requires_evidence": true},
   {"id": "w3", "question": "快充与家充桩的抱怨分布（白名单方法无法交叉分组）",
    "dimension": "other", "aspect": "充电与补能",
    "method": "python_analyze", "requires_evidence": false}
 ]}

## 进度账本（确定性核对，报告提交前须全部完成）
- 待执行：w1, w2, w3
- 已执行：无
- 证据账本：无
- 预置基准已入溯源账本，可直接引用

## 执行约束（继承自系统提示，此处仅提醒）
- python 代码 ≤40 行，禁止 import 与 I/O；frames 枚举与日期范围见大纲阶段简报（已在你上文）
- 数据不支持某 workstream 时：执行后如实记录空结果，并在报告"限制"中解释，NEVER 凑结论
````

**注意**：执行段不再重复数据目录——它已在大纲阶段消息里，且同 thread resume 后仍在上下文中
（append-only）。这正是方案 B 相对拆段方案 A 的上下文红利：探索发现无损带入执行。

### 4.3 简报里"不出现"的东西（对照 C1）

- 整行样例数据（3 行全文样例 → 取消，由 schema + 枚举替代）
- 长文本字段全文（content/quote/statement → 经工具获取）
- 重复的 SOP 指令（开场只留 ≤5 行行动指令；规则在系统提示与技能里各说一次）
- 时间戳类易变值进入系统提示（稳定前缀不受影响）

## 5. 明确不做（最简单可行原则）

- **子代理架构（C9）**：MAX_WORKSTREAMS=6、单 agent 顺序执行的规模下，引入 sub-agent 是过度设计。
- **压缩/笔记（C6/C7）**：先量化真实任务的 token 曲线；曲线证明必要后，
  优先做工具结果清除（比摘要压缩安全），再考虑 scratchpad。
- **枚举无限膨胀**：experience 等自由文本列不枚举（只给示例值）；
  枚举清单按计数排序、设 top-N 上限，防快照变大后简报爆炸。

## 6. 验证方式

1. 确定性单元测试：简报生成器输出含全部枚举/覆盖字段；裁剪逻辑在超限时长文本先裁、枚举不裁。
2. 门禁回归：baseline 数字写进报告不再触发"来源外数字"；非 baseline 伪造数字仍被拒。
3. 行为验收（配置 LLM 环境）：同一批问题在修订前后各跑一遍，
   对比：计划一次通过率、python 首/二次执行成功率、错误预算消耗、报告 gate 拒绝次数。
4. token 计量：记录修订前后单任务总 token 与分阶段分布，作为 P6 是否启动的依据。

## 7. 实施窗口

方案 B（interrupt_on 门禁）落地时执行段开场消息必然重写——本方案与之一并在同一变更内实施，
避免二次开膛。任务拆分建议并入 tasks.md 第 4 节（深度分析门禁状态机）相邻位置。

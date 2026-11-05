# Proposal

- **Change ID**: `auto-039-semantic-layer`
- **Human Owner**: 待指派（本变更在 Owner 指定并完成规格评审前不得进入业务实现）
- **规格评审状态**: 待评审（reviewer、日期、reviewed commit、结论均未产生）
- **阶段**: 规划（本变更只产出规格与设计，不含实现）

## Why

`08_semantic_services` 目前没有一个语义层，只有一份被复制的数据字典。同一批业务定义散在六处（镜像视图 DDL、指标目录字典、分析方法的 SQL 字面量、简报数据字典、中文标签表、工具与技能文档），改动一个指标名需要同步十余个文件；唯一的一致性检查只验证"标识符存在"，不验证"定义是否同一件事"。

定义分裂已经产出两个可复算的错误：其一，`negativeShare`（全量口径）与原语 `negative_share`（精选口径）绑定为同一指标，同一议题两级口径相差 65%（品牌与口碑 15.5% vs 25.5%）；其二，按产品维度分组时 `LEFT JOIN` 使观点行放大 2.17 倍（819 → 1780）。根因不是编码失误，而是模型里缺三样东西：数据集粒度、关系基数、口径层级。

现在做的另一个理由是口径本身没有被记录。对外标注"全量声明级口径"的指标，其真实分母是四级筛选后的 3 356 条观点，而不是 26 936 条全量抽取结果；这条筛选链只在已失效的脚本里存在，任何读者都无法从产物反推。下游分析只能依赖文案，无法依赖数据。

## What Changes

- **新增 5 个 Agent 可见数据集**：`claim`（观点）、`post`（帖子）、`product`（产品层级）、`mention`（帖子×产品桥接）、`user`（作者）。不提供任何预聚合表；聚合由查询时派生。
- **新增口径阶梯（population ladder）作为一级建模对象**：`extracted` 26 936 → `su7_linked` 18 087 → `su7_primary` 7 024 → `experience` 3 356 → `firsthand` 942 → `curated` 819，每一级有名称、谓词、规模与来源。对外主口径定为 `experience`（L4）。
- **新增声明式语义模型**：数据集、关系与基数、维度与枚举、指标（类型/口径/粒度/可加性/可用维度）、命名查询、策略与覆盖，全部写在单一模型工件中；语义视图 DDL 由模型生成，不再手写视图。
- **新增单一查询协议**：`query(metrics, dimensions, filters, time, order, limit)`，返回行 + 口径 + 覆盖 + 版本 + 查询标识。原 10 个分析方法降级为模型中的命名查询，对外调用方式保留。
- **新增数据构建链路**：从采集库与冻结抽取/归一产物建 staging 表，经键对齐后生成 core 表，再由模型生成语义视图。构建校验源文件哈希，不一致拒绝复用旧产物。
- **新增模型访问面**：`describe`（一次返回全部定义与覆盖）替代当前多份手写目录；错误码化拒绝（未知指标、维度对该指标非法、超出覆盖、粒度冲突、枚举非法、维度过多）。
- **BREAKING（数值）**：修正产品维度分组放大后，按产品切分的计数与占比会下降（观点总数 819 → 实际去重后口径）。需重跑依赖产品维度的报告。
- **BREAKING（措辞）**：标注"全量声明级"的指标改称 L4 体验类口径并附规模；引用该指标的既有报告文案需同步。
- **不改变**：HTTP 路径、MCP 工具名、报告问答、审核发布流程、既有报告的结构与结论。

### 明确排除（Out of Scope）

1. 不重新运行抽取模型、不修改 `01_ingestion`、`04_extraction`、`05_normalization` 的产物与代码。
2. 不把无产品指代的 3 585 条观点默认归入 SU7；该业务判断维持现状，记为已知局限。
3. 不引入外部语义层产品、不新增运行时依赖（沿用标准库 + 现有依赖）。
4. 不接线在建变更占用的模块；本次只交付新增文件与规格，接线属于后续变更。
5. 不写入 `openspec/specs/`（正式规格），不归档任何在建变更。

## Capabilities

### New Capabilities

- `data-semantic-model`: 业务数据集的定义、粒度与主键、实体关系与基数、口径阶梯、维度与枚举规范、指标定义与可加性、语义视图的生成与可见性边界、数据血缘与版本、构建期校验与数值回归。
- `agent-data-access`: Agent 与外部消费者可用的数据访问契约——语义目录描述、单一查询协议与响应信封、命名查询兼容、类型化错误码、覆盖面与样本量披露、结果随附的口径/版本/快照标识。

### Modified Capabilities

无。当前 `openspec/specs/` 为空，没有已存在的正式能力需要变更。

## Impact

- **新增代码**：`offline_analysis_pipeline/08_semantic_services/semantic/`（模型加载与校验、DDL 生成、查询编译、目录导出）、`semantic/etl/`（staging → core 构建）、`semantic/model.yaml`、配套测试与固定数据回归用例。
- **只读依赖**：`data/stock/db/ingestion.sqlite3`、`04_extraction/results/contract-passed.jsonl.gz`、`05_normalization/results/mention-mapping.jsonl.gz`、`05_normalization/results/taxonomy.json`。
- **受影响的下游**：`research/service.py`（/api/stats、/api/claims）、`research/analysis_methods.py`、`task_brief.py`（简报数据字典与表单选项）、`agent_tools.py`（工具描述）、`terminology.py`（标签）、`integrations/mcp_server.py`、`verifier.py`（口径校验方式）、`db_mirror.py`（被语义视图替代）。这些模块的改造在接线阶段进行，需等在建变更合并。
- **并行约束**：`auto-025`、`auto-027`、`auto-028`、`auto-030`、`auto-031`、`auto-032`、`auto-033`、`auto-034` 正在修改上述下游文件，其中 `auto-030` 与 `auto-032` 占用 `analysis_methods.py`、`catalog.py`、`task_brief.py`。本变更新增文件为主，接线须待相关变更交付并由 Owner 决定顺序。
- **数据影响**：镜像由 1.9 MB 增至约 15 MB（装入全量 26 936 条观点）；单次聚合仍为毫秒级，不需要预聚合。
- **风险**：口径阶梯的谓词依赖上游归一产物中的 `status`/`role` 字段语义，若上游重跑改变判定规则，阶梯各级规模会变；故构建期必须记录源文件哈希与各级规模，并要求回归用例随规模变化显式更新。

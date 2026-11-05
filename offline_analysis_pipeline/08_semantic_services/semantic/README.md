# 语义层（`semantic/`）

本包是 Agent 可见数据的唯一定义源。所有业务概念写在 `model.yaml`；代码只负责解释这份声明，不得内置指标名单、口径文案或维度枚举。

## 分层

```
spec  <  model  <  build / compile  <  execute  <  catalog  <  adapters
```

下层不得引用上层，由 `tests/test_semantic_model.py::LayeringTest` 静态断言。新增模块时先决定它属于哪一层，再决定放哪个目录。

| 目录 | 职责 | 不做什么 |
|---|---|---|
| `spec/` | 不可变领域对象与共享词表 | 不读写文件、不连库、不生成 SQL |
| `model/` | 加载与校验模型 | 不解释查询、不做统计 |
| `build/` | 源数据 → staging → core → 语义视图 | 不处理请求 |
| `compile/` | 查询 → 执行计划 → SQL | 不执行、不连库 |
| `execute/` | 执行与响应信封 | 不做业务判断 |
| `catalog/` | 目录导出与中文标签 | 不重复定义口径 |
| `adapters/` | HTTP / MCP / Agent 工具的薄适配 | 不含业务逻辑 |

## 校验命令

在 `08_semantic_services/` 目录下执行：

```powershell
python -m semantic.model            # 校验 semantic/model.yaml 并打印摘要
python -m semantic.model 其他路径.yaml
```

- 退出码 `0`：文档结构合法且内部一致。
- 退出码 `2`：被拒绝，原因打印到 stderr，形如 `populations.experience.filter: ...`。

单元测试：

```powershell
python -m unittest tests.test_semantic_model
python -m unittest tests.test_semantic_compile tests.test_semantic_execute
python -m unittest tests.test_semantic_build   # 会真实构建一次语义库（约 15–20 秒）
```

## 查询：编译 → 执行

```python
from semantic.execute import execute, execute_saved
from semantic.spec import QuerySpec

execute(QuerySpec(metrics=("negativeShare", "claims"), dimensions=("aspect",),
                  order=({"field": "negativeShare", "dir": "desc"},), limit=5))
execute_saved("curated_sentiment_mix", {"aspect": "充电与补能"})
```

- 编译在 `compile/`：先校验指标/维度/口径/覆盖/上限，再定粒度与连接，最后渲染 SQL 与绑定参数；模型里的任何文本都不会进入标识符位置。
- 执行在 `execute/`：只读连接 `data/semantic.db`，返回行 + 口径文案 + 覆盖（薄样本分组）+ 模型版本 + 快照哈希 + `query_id`。
- 产物版本与模型不一致时直接报 `STALE_ARTIFACT`，不接受"拿旧口径回答新问题"。
- 口径成员来自 `claim_population`；视图本身不带口径过滤，否则只能查询一级口径。

**多归属**：一条观点提到 N 个车型时计 N 次。这个口径由 `claim_product` 数据集（一行 = 观点 × 车型）承载，对应 `productClaims` / `productNegative` / `productNegativeShare`（观点×车型粒度）与 `productPosts`（按帖子去重）。它不能加回 `claims`：两级粒度不同，同一次查询里混用会被编译期拒绝。

**仍然拒绝**：其余一对多路径（例如经 `post→mention` 直接按提及切分观点级指标）会放大行数，编译器以 `FANOUT_RISK` 拒绝，而不是给出放大后的数字。

## 目录：一次调用拿到"能问什么"

```python
from semantic.catalog import describe

catalogue = describe()                 # 读库：带枚举、覆盖区间与各级规模
definition = describe(with_values=False)  # 只读模型：不连库也能导出定义
```

```powershell
python -m semantic.catalog            # 输出 JSON
python -m semantic.catalog --no-values
```

目录里没有第二份定义：指标清单、口径文案、`allowed_dimensions` 都来自模型；分类维度的取值从库里按频次取，排除值不出现；时间维度覆盖区间按实际数据校正。取值空间超过 `max_rows` 的维度（例如观点标识）不做整表枚举，只给 `top_values` 与 `distinct_values`。

## `model.yaml` 字段

### 顶层

| 字段 | 含义 |
|---|---|
| `model_version` | 模型版本，随结果一起返回；口径变化必须递增 |
| `schema` | 结构版本，当前 `autoinsight-semantic-1` |
| `snapshot.paths` | 数据来源路径（相对 `offline_analysis_pipeline/`）；摘要由构建写入元信息 |
| `datasets` | Agent 可见的数据集 |
| `relationships` | 数据集之间的连接路径与基数 |
| `populations` | 样本口径阶梯 |
| `dimensions` | 可切片的维度 |
| `metrics` | 指标 |
| `saved_queries` | 命名查询（对既有分析组合的兼容入口） |
| `policies` | 查询硬上限与禁止面 |

### `datasets.<name>`

| 字段 | 必填 | 说明 |
|---|---|---|
| `relation` | 是 | 对 Agent 暴露的关系名 |
| `source` | 是 | 物理表（core 层），不对外暴露 |
| `grain` | 是 | 一行代表什么：`claim`/`post`/`mention`/`product_node`/`user`/`snapshot_meta` |
| `primary_key` | 是 | 主键；只有 `mention` 允许复合键 |
| `population` | 否 | 默认口径，必须是同数据集上的口径 |
| `description` | 是 | 一句业务说明 |

数据集只能有一种粒度。多种粒度混在一张表里时，系统会在加载阶段拒绝——这是重复计数的源头。

### `populations.<name>`

| 字段 | 必填 | 说明 |
|---|---|---|
| `dataset` | 是 | 成员所在的数据集 |
| `source` | 是 | `rule`（可由谓词重算）或 `frozen`（构建期导入，不可本地重算） |
| `parent` | 否 | 上级口径，形成包含关系；同一数据集、不得成环 |
| `filter` | 否 | 谓词；空表示全集 |
| `note` | 否 | 业务说明，会进入口径文案 |

`rule` 与 `frozen` 的区别必须如实标注：规则成员由构建期重算，冻结成员由导入决定、本地无法复算，把后者标成规则会把"未知"变成"零"。

`curated` 现在用 `rule`：两条分支取并集——拥有者的亲历体验，以及未拥有者购车前的表达，两支都落在 `su7_primary` 之内（第一支另限为体验类说法）。`ownership` 是帖子属性，为了让成员判定直接落在事实行上，构建期在 `fct_claim` 物化一份，切片仍走 `post` 维度。

口径成员由构建写入 `claim_population(claim_id, population)`，每一级的规模都能在库里按 `population` 计数复核，无需重算整条阶梯。

### `dimensions.<name>`

| 字段 | 必填 | 说明 |
|---|---|---|
| `dataset` / `column` | 是 | 维度取值来自哪里 |
| `type` | 是 | `categorical` / `time` / `entity` |
| `label` | 是 | 中文名 |
| `enum_source` | 否 | `query`（动态取自快照，默认）或 `static` |
| `enum` | 条件 | `static` 时必填；`query` 时由构建写入 |
| `alias` | 否 | 别名 → 规范值，例如 `混合 → 正负混合` |
| `excluded` | 否 | 明确排除的取值及原因由 `note` 记录 |
| `grain` / `coverage` | 条件 | 时间维度必填粒度；覆盖区间由构建校正 |
| `requires` | 否 | 需要先经过的数据集（如 `product` 需经 `post`） |

### `metrics.<name>`

| 字段 | 必填 | 说明 |
|---|---|---|
| `type` | 是 | `simple` / `ratio` / `derived` |
| `dataset` / `population` | 是 | 定义在哪个数据集、属于哪一级口径 |
| `grain` | 是 | 统计单位；默认必须等于数据集粒度 |
| `additive` | 是 | 是否可以跨分组相加；比率必须为 `false` |
| `agg` / `field` / `filter` | 条件 | `simple` 必填 `agg`；`count_distinct` 必填 `field` |
| `numerator` / `denominator` | 条件 | `ratio` 必填，须为同数据集、同口径、同单位的指标名 |
| `expression` | 条件 | `derived` 必填，只能引用已定义指标 |
| `allowed_dimensions` | 是 | 允许的维度；维度所在数据集必须有声明的关系路径 |
| `synonyms` | 否 | 供自然语言映射使用 |

**口径不同的同一业务概念必须是两个指标。** `negativeShare`（体验口径）与 `curatedNegativeShare`（精选口径）因此是两个名字，而不是一个指标的两个参数。

### `saved_queries.<name>`

命名查询是查询协议的固定组合，用于兼容既有调用与计划里的既定分析。它不得带自己的计算逻辑。

| 字段 | 说明 |
|---|---|
| `summary` | 一句话说明 |
| `metrics` / `dimensions` | 组合内容；`kind: meta` 时可为空 |
| `filters` | `$param` 表示引用参数 |
| `params` | 参数声明，至少含 `type` |
| `order` / `limit` | 排序与行数上限，不得超过策略值 |
| `kind` | `query`（默认）或 `meta` |

### `policies`

| 字段 | 说明 |
|---|---|
| `max_rows` | 单次查询返回行数上限 |
| `max_dimensions` | 单次查询维度数上限 |
| `thin_sample_threshold` | 低于该值的分组标记为薄样本（只警告，不删数据） |
| `forbid` | 不可访问的物理表模式 |

## 表达式约束

模型里的 `filter`、`column`、`expression` 只能写：列名、常量、比较运算、括号与白名单函数。以下内容一律被拒绝并指明原因：

- SQL 关键字（`select`/`drop`/`union` 等）
- 语句分隔符 `;` 与注释 `--`、`/* */`
- 超长表达式（> 300 字符，应拆分为模型字段）

查询语句由编译器组装，模型作者写的任何内容都不会进入标识符位置。

# 组合查询：语义聚合怎么写

## 何时用

按维度聚合、跨指标对比、查询被拒需要改法时。

## 最小工作流

1. 先定**指标**（算"什么"）——每个指标自带口径、粒度、可加性
2. 再定**维度**（按"什么"切）——必须在指标的 `allowed_dimensions` 内
3. 最后加**过滤与时间**——过滤值必须来自目录枚举
4. 一次可并行多个指标——但必须同口径、同粒度

## 可直接改用的查询

```python
{"metrics": ["negativeShare", "claims"],   # 比率 + 分母，成对取
 "dimensions": ["aspect"],                  # 最多 2 个
 "filters": {"sentiment": "负面"},
 "time": {"start": "2026-01", "end": "2026-06"},
 "order": [{"field": "negativeShare", "dir": "desc"}],
 "limit": 16}
```

改的地方只有三处：`metrics`（名字查目录）、`dimensions`（查 allowed 清单）、`filters`（值查枚举）。其余结构照抄。

## 四条硬规则

1. **比率不可加**：`additive: false` 的比率不能跨分组求和或相乘。要总量就同时取分子分母指标，在代码里重算——不拿分组百分比再平均。
2. **多归属换指标，不换维度**：按车型计数用 `productClaims`（观点×车型），不给 `claims` 加车型维度；两者不能互相加回（一条观点提多个车型会记多次）。
3. **跨口径 = 两次查询**：同查询内指标必须同口径；要对比两级口径就发两次，报告里并列并各自标注。
4. **明细也是这个协议**：要行级清单时把 `claim_id` 放进 dimensions 配合 limit，返回行仍带口径与 query_id。

## 被拒时怎么读

| 错误码 | 含义 | 动作 |
|---|---|---|
| `UNKNOWN_METRIC` / `UNKNOWN_DIMENSION` | 名字不在模型里 | 用返回的可用清单改名 |
| `DIMENSION_NOT_ALLOWED` | 该指标不允许按此维度切 | 看 allowed 清单，或换指标 |
| `POPULATION_MISMATCH` | 一次查询混了不同口径 | 拆成两次查询 |
| `FANOUT_RISK` | 该连接会放大行数 | 换数据集（用多归属数据集），不硬连 |
| `OUT_OF_COVERAGE` | 时间超出覆盖 | 改到区间内并在报告注明 |

错误信息自带可用替代，照着改即可；同一个错重复两次就说明方向错了，换思路而不是改参数。

## 自查一句

拿到结果先看信封：`caliber` 是报告措辞来源（直接引用），`population`/`grain` 决定分母与单位，`coverage.thin_buckets` 非空则该分组要在报告标注样本不足。

# 数据契约

本模块消费 `06_reporting/analysis/` 冻结分析数据，产出双投影报告。本文档定义来源清单、每文件职责与替换方式；上游字段变化时先对照本文档评估，再决定适配或升级契约版本。

## 来源清单（当前为上一版本数据，占位）

| 文件 | 职责 | 报告消费位置 |
|---|---|---|
| `summary.json` | 总规模、cohort、evidence 检查、ownership、核心情感、时间范围、Claim 字段 | 摘要、漏斗、身份分布 |
| `profiles.json` | 6 个用户群 × 议题 × 情感分布 | 旅程对比、全景议题表 |
| `aspect-sentiment.csv` | 主分析集（体验/风险）16 议题精确计数 | 议题×情感主表与两图 |
| `scope.json` | 竞品白名单与共提及计数 | 竞品共现章 |
| `reviewed-cases.json` | 11 个定向复核案例（引文/链接/表达性质/边界） | 典型用户声音 |
| `verification.json` | 上游 12 项校验声明 | 方法说明 |

抽取/映射版本：V2.3 修复抽取 + AUTO-018 V2 delivery-r3。

## 接缝设计

1. **答案册**：`output/numbers.json` 是全部统计值的唯一出口，由 `builder` 构建期计算；`render` 与两份成品不直接读上游数据文件。
2. **令牌解析**：`configs/content.json` 与 `configs/template.html` 中的 `[[NUM:key]]` 在渲染期从答案册取值；答案册缺键即构建失败，不允许静默缺数。
3. **门禁**：`verify` 核对图表完整、令牌全部解析、Agent 版覆盖全部关键数字、两份成品抽样数字一致、案例数量、来源文件哈希（对照 `output/data-version.json`）。

## 替换方式（新版本数据）

新数据按上表职责落位 `analysis/` → `python run.py all` → 核对 `evidence/verify-latest.json` 全绿 → 人审变化清单覆盖的叙述结论。若上游字段改名/增删，先更新 `builder` 的取数映射并在本文件记录，再重建；禁止跳过校验直接采用新数据产物。

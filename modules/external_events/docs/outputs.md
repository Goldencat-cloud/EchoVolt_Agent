# 产出文件与评估口径

## 一、`outputs/research/` —— 事件时间线

| 文件 | 说明 |
|---|---|
| `小米_SU7_timeline.json` | **工具原始产出**（schema v2，69 事件）。时间窗 2022-10-28~2026-10-03，`status=partial`，过滤统计：噪声 6 / 窗口外 22 / 重复 URL 67 / 成员级忽略 50 / 整簇忽略 14 / 低权威丢弃 4。事件字段见下。 |
| `小米_SU7_timeline.txt` | 同内容的可读版（按日期升序，含覆盖度与权威分），给人看。 |
| `小米_SU7_timeline_v2.json` | **人工精修事件轴**（schema v4，83 事件）。在 v1 基础上合并拆分、补漏与纠偏，字段为 `id/date/precision/type/subtype/title/provenance/tool_refs/sources`；`tool_refs` 可回指 v1。消费方做趋势分析/共鸣分析建议读 v2，需要完整 `sources`/`summary` 明细时按 `tool_refs` 回查 v1。 |
| `小米_SU7_timeline_v2.txt` | v2 的可读版。 |
| `小米_SU7_timeline_resonance.json` | 事件-评论共鸣分析（17 个事件）。字段：`related_rate_before/after`、`resonance_pp`（百分点差）、`examples`（含 `post_id`，可回挂原文评论）。汇总：中位数 +10.0pp，Q1 0.0pp，Q3 +28.3pp，正向占比 64.7%。 |
| `苹果_iPhone15_timeline.json` / `.txt` | **跨域泛用验证**（11 事件）：同一套流程不改代码跑手机领域，证明不依赖行业词表。 |
| `事件口碑关联图.png` | 事件与口碑（评论量/共鸣）关联的可视化。 |

### v1 事件字段（schema v2，`docs/openspec/specs/.../spec.md` 为契约）

```
event_id, event_date, date_precision(day/month/year/unknown), date_missing,
event_type(product/competitor/policy/tech/public_opinion/other), subtype,
relevance(core/context), title, summary,
media_coverage{source_count, max_tier, level}, authority(0-100),
sources[{source_domain, source_tier, confidence, url, published_date, title}]
```

- `media_coverage` 只表示**媒体覆盖面**（可能含投放），**不是影响力**；真实影响由 resonance / influence 评估度量。
- `authority` = 最高来源置信度 + 独立域名印证加成（+10/+15），上限 100；< 50 的事件不输出。
- 每个事件的 `sources[].url` 即溯源入口，可逐条回查原文报道。

## 二、`outputs/eval/` —— 评估结果

| 文件 | 说明 |
|---|---|
| `gold_events.json` | 人工金标事件集（41 个），工具层评估的 Ground Truth。 |
| `tool_quality_eval.json` | **工具层质量**：召回、精确率、聚类纯度、摘要忠实度 + 审计轨迹。 |
| `influence_eval.json` | **价值层评估**：伪事件对照（检验 A）+ 波峰对齐随机基线（检验 B）。 |
| `calibration_set.json` | 判定员校准集（50 条，含 LLM 判定与人工/交叉标注位）。 |
| `calibration_labels.json` | 交叉标注（GLM）回填的标签。 |
| `judge_calibration_report.json` | 校准报告：一致率、精确率、召回率、混淆矩阵、分歧明细。 |
| `calibration_review.md` | 人工复核清单（方案 C：复核 20%）。 |

### 工具层质量（对 41 个金标事件，语义匹配 + 日期 ±3 天）

- 整体召回 **14/41 = 34.1%**；**关键事件召回 11/15 = 73.3%**
  （上市发布类 5/5、政策召回类 3/5、事故舆情类 3/5）。
- 漏失集中在**交付里程碑/官方战报类（15 条）**——此类信息多来自官方微博与销量快讯，
  新闻检索天然覆盖弱；另有诉讼节点类 2 条、资质/申报流程类 2 条漏失，说明 policy 检索模板对司法/流程类查询覆盖不足。
- 事件精确率 **56/69 = 81.2%**（9 个为媒体议论/预告类"软聚合"）；事实精确率 **97.1%**，**捏造 0 个**。
- 聚类纯度（抽样 20 事件）：成员级纯成员 72/105 = 68.6%；污染主要来自站点首页/导航页、FAQ 导购页等无语义结构文本
  ——字符 n-gram 相似度在此类文本上失效，建议配置 `EMBEDDING_*` 换成语义向量。
- 摘要忠实度（抽样 15）：15/15 主干事实可在来源标题找到依据，未发现编造；
  注意 `sources` 只持久化标题不持久化正文片段，数值细节只能对标题验证。

### 价值层评估（诚实结论）

- 检验 A（放大倍数）：真实事件中位 **1.037x** vs 伪事件中位 **0.997x**，**p = 0.303**（不显著）。
- 检验 B（波峰对齐）：真实波峰命中率 **66.7%**，全程随机基线 **45.0%**，事件纪元内随机基线 **62.3%**，
  判定为 **`trivial_or_inconclusive`**（未超过基线 +0.1）。
- 结论：**"外部事件能解释评论量波峰"目前未被统计检验证实**。请勿把这些数字当作正相关证据使用；
  若要继续推进，需要更密的事件轴（如 v2 的 83 事件）与按事件类型分层的检验。

### 判定员校准

- 50 条全部标注，与交叉标注**一致率 100%**，P/R 均为 1.0。
- 注意：这是"LLM 判定员 vs 另一个 LLM 交叉标注"的一致率，**不等于人类判定准确率的无偏估计**；
  人类复核 20% 后的终版才应作为对外结论（见 `calibration_review.md`）。

## 三、重新生成

```bash
python -m mcp_server                       # 或直接 scripts/verify_research_tool.py 实调一次 → 覆盖 outputs/research/
python scripts/analyze_resonance.py        # → outputs/research/小米_SU7_timeline_resonance.json
python scripts/eval_influence.py           # → outputs/eval/influence_eval.json
python scripts/make_judge_calibration.py --build   # → outputs/eval/calibration_set.json
python scripts/make_judge_calibration.py --score   # → judge_calibration_report.json + calibration_review.md
```

`gold_events.json` 与 `tool_quality_eval.json` 的一部分判定由人工完成，脚本不覆盖它们。

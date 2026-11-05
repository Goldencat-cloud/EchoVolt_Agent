# 冻结数据审计记录

审计日期：2026-10-25  
输入目录：`offline_analysis_pipeline/06_reporting/analysis/`  
核对方式：读取现有 JSON/CSV、报告版本清单与报告说明；未重跑 01–05 管线或调用外部模型。

## 数据范围与版本

- `summary.json` 记录 9,529 条来源帖子、26,936 条观点声明、15,002 条提及；时间范围为 2022-10-28 至 2026-10-03。
- 同一汇总记录中，“当前拥有且亲历使用”队列为 148 帖/297 条观点；“明确未拥有的购车前表达”为 255 帖/522 条观点。两队列适用边界不同，不可混作同一用户群。
- `output/data-version.json` 明确标记数据为“上一版本数据（V2.3 抽取 + AUTO-018 V2 delivery-r3），占位性质”。该版本不适合对外冒充当前正式数据版本，需作为演示快照标记并在产品显示“临时样本”。
- `summary.json` 的 evidence checks 为 22,971 passed、3,965 needs_review；这些是自动校验状态，不能等同于人工语义审核。
- 所有 26,936 条观点都存在结构化 `aspect/content/sentiment/evidence` 字段；此字段完整计数不代表内容准确。帖子级 ownership 是模型标注，不是实名或车辆所有权核验。

## MVP 数据字典

| 数据/字段 | 用途 | 口径/限制 |
|---|---|---|
| `aspect-sentiment.csv: aspect` | 议题筛选 | 16 个议题；名称以快照为准 |
| `claims`, `posts` | 规模和分母 | 声明数与去重帖子数是不同统计单位 |
| `negative`, `claims`, `negativeShare` | 观点级负向比例 | `negativeShare = negative / claims`。例如空间与舒适性为 131/302=43.4%；这是观点声明比例，不是帖子比例 |
| `negative_posts`, `posts` | 去重帖子级计数 | 舒适性为 113/239；二者比例约 47.3%，与 CSV `negativeShare` 不同。MVP 返回原始计数，避免误用观点级比例冒充帖子级比例 |
| 观点 `aspect/sentiment/content` | 证据筛选与展示 | 来自冻结分析输出；不重新推断标签 |
| `ownership/experience/journey` | 用户阶段过滤 | 仅表示源分析中的分类；覆盖/准确度有限 |
| `evidence[].quote` | 可展开原文依据 | 保留引文原文，不将模型概述伪装成原文 |
| `url`, `title`, `date`, `post_id`, `claim_id` | 可追溯引用 | 当前 core/potential/evidence-pack 内记录均有 URL 与 evidence；上游 extraction JSONL 本身不含可展示 URL，不可单独引用 |
| `data_version` | 版本标识 | 使用报告版本文件中的占位标签并附输入清单 hash；标记为临时样本 |

## 观点索引覆盖

- `core-claims.json` 297 条，`potential-claims.json` 522 条；去重 key 共 819 条。抽查式程序核对显示这 819 条均包含 URL 与 evidence。
- `evidence-pack.json` 有 15 个议题；“空间与舒适性”包含 44 条 core 与 38 条 potential 观点证据，且 `aspect-sentiment.csv` 有对应统计，因此可作为端到端演示候选议题。
- 该 819 条索引远小于汇总中的 26,936 条声明；观点查询结果只能代表被精选进入 core/potential 的证据集合，界面必须显示“精选证据样本”，不得声称穷尽所有用户声音。
- `reviewed-cases.json` 有 11 条，记录描述为 Codex 指向来源复核；没有足够证据表明它们经过团队成员的语义审核。报告发布仍需非作者队友审阅。

## 质量问题与演示建议

- 旧报告封面称“舒适性”负面占比最高，但同报告表格显示可靠性 55.1%、服务与交付 47.0%、空间与舒适性 43.4%。因此旧文案不得用于事实问答，也不得复制为本次发现。
- 建议完整演示议题：“空间与舒适性负向观点比例及其支持观点”。统计按 131 条负面声明 / 302 条声明计算；另有 113 条负向帖子 / 239 条议题帖子。精选证据有来源链接；生成器必须说明证据覆盖只来自 82 条精选观点，且当前快照为临时样本。
- 不在本 Change 中重跑抽取、规范化或模型处理；不得把旧版占位数据称为比赛正式数据。公开部署前还需 Owner 确认来源内容、引文和 URL 的展示授权。

## 完整性检查

本记录依据 `summary.json`、`aspect-sentiment.csv`、`core-claims.json`、`potential-claims.json`、`evidence-pack.json`、`reviewed-cases.json` 和 `output/data-version.json`。该检查说明字段和样例可用，不构成对上游统计、语义分类、公开授权或正式研究结论的独立验证。

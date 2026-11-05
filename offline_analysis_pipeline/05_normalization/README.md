# SU7 产品 taxonomy 与语境归一 · V2

当前交付数据目录是 **delivery-r3/**。final/、reviewed/、delivery/、delivery-r2/ 是本轮排查时的中间版本；V1 保持不变。后续分析使用 delivery-r3/mention-mapping.jsonl 与 delivery-r3/taxonomy.json。

## 改了什么

按用户确认采用品牌 → 车系 → 明确配置的 taxonomy。每条产品提及只落一个最深节点，年款、版本和代际保留为提及属性，不再为“SU7 Max 年款未知”“2024款 SU7 版本未知”等组合创建额外产品实体。

口语别名使用 aliases.json 的显式词典及 SU7 论坛来源、标题和同帖语境消歧。酥妻、酥七、苏七、速七、SU7 等可归小米 SU7；毛豆3/毛豆三归特斯拉 Model 3。明确竞品优先：“金彭 SU7”留金彭，“尚界酥妻”只确认尚界品牌并复核其车系。只说小米汽车保持品牌层；小米 SUV 不默认 SU7。多车比较中的 Max/标准版仍需结合指代，不能一概套用默认车型。

## 本轮结果

15002 个提及完整覆盖：3118 个到品牌、10740 个到车系、220 个到明确配置；734 个仍无法落点、190 个非整车或集合称谓单列。14078 个可落 taxonomy，相对 V1 新增 3169 个可归类提及。可落点与语义待复核可同时成立：属性缺证据、引文定位或冲突等保留 review_required，共 1514 个提及需要进一步复核。

taxonomy 有 125 个品牌、541 个车系、7 个精确配置节点，共 673 个非根节点。它们是语料中的称谓节点，不等于已核实的在售车型目录。品牌和车系通过 parent_id 连接，不再作为平行、不相干的实体组合。

`direct_mentions` 是直接落本节点的提及；`rollup_mentions` 包含本节点和子节点。两者不可相加。`rollup_posts` 是该节点范围内独立帖子数；跨主题/车型的帖子可能重叠，不得直接相加成人数。

## 使用入口与文件

- `delivery-r3/review.html`：taxonomy 树、按节点及层级筛选、原帖链接、原文证据、归类依据、标注保存与导出。标注存浏览器 localStorage，使用独立 V2 命名空间，不读取 V1 人工标注；请导出备份。
- `delivery-r3/taxonomy.csv` / `.json`：节点、父子关系、直接落点和向上汇总数量。
- `delivery-r3/mention-mapping.csv` / `.jsonl`：逐提及 node_id、ancestor_ids、resolution_level、版本/年款属性、依据与待复核原因。JSONL 保留原始产品对象。
- `delivery-r3/claim-product-links.jsonl`：原 Claim 到局部提及和 taxonomy 的连接；原比较方向、角色不改。
- `delivery-r3/alias-mapping.csv`、`review-queue.csv`：实际原词映射与频次、待复核样例。
- `aliases.json`、`delivery-r3/alias-dictionary.json`：规则来源与口语词典。
- `delivery-r3/v1-comparison.json`：前后映射状态对照；V1 组合实体数与 V2 层级节点数不是相同统计量。
- `delivery-r3/analysis-readiness.json`：下一步分析的字段可用性、时间及作者键覆盖，尚未输出需求结论。
- `delivery-r3/checks.json`、`manifest.json`：覆盖、层级、外键、输入哈希和生成文件清单。
- `normalize_taxonomy.py`：本轮离线分析脚本，复用 V1 的字符串/证据/配置表读取 helper；依赖版本由 manifest 哈希固定。
- `test_taxonomy.py`：16 个与用户规则相关的边界测试。
- `next-analysis-research.md`：归一后需求分析路线与一手资料。

## 验证与适用范围

21 个测试通过，包括口语别名、品牌只落品牌、版本不新建节点、明确竞品优先、多车型指代、完整配置匹配、年款不推断、原型车不混配置、手机不作汽车。全量检查通过：15002 提及恰好覆盖、最深节点唯一、父子与外键完整、祖先无重复、树形汇总一致、无 null 组合实体、猜想图不进入明确配置、源文件哈希不变。

规则映射尚未做全量人工语义验收。论坛语境可以补车型名称的省略，不能补用户拥有状态、经历、年款和具体配置，不能把缺产品引用的 Claim 全部赋给 SU7。模型/语料里的传闻车型只作为论坛称谓保留，不代表官方车型存在性或当前在售确认。

本轮没有模型 API 调用、embedding 或需求聚类运行。业务服务接入、代码提交/PR/合并和最终人类交付验收未执行。

## 复现

在 G:/AutoInsight 根目录执行，输出目录必须不存在：

```powershell
python -m unittest discover -s collaboration/result/auto018-product-entity-normalization/v2 -p test_taxonomy.py -v
python collaboration/result/auto018-product-entity-normalization/v2/normalize_taxonomy.py --output collaboration/result/auto018-product-entity-normalization/v2/reproduction
```

脚本输入包括修复后 V2.3、V1 的已核查映射与 helper、原始元数据 CSV、用户提供的 SU7 配置表和 aliases.json。各输入 SHA256 见 delivery-r3/manifest.json。

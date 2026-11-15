# Design

## Context

参见 proposal.md。当前修复后文件包含 9529 帖、15002 个产品提及和 2343 个不同原名。程序契约通过不证明名称或车型存在性正确。正式 specs 暂无能力记录。

## Goals / Non-Goals

**Goals:** 独立、保守、可复现的数据整理与复核包。

**Non-Goals:** 业务服务、自动联网车型库、LLM 调用、跨平台用户合并及事件标准化。

## Decisions (V1 historical)

1. 一次性分析记录和派生数据均放 result 新目录，不修改现有工具和抽取数据。分析过程留存 notebook 和同源可运行脚本，属于本次授权的离线数据处理，不代表业务代码交付。
2. NFKC、空白和拉丁字母大小写是基础规范化；车型数字、尾缀和中文词义不做模糊匹配。仅使用语料中明确品牌+车系共现的证据登记候选；这是语料名称库，不是官方车型存在性库。
3. `canonical_id` 标识品牌/车系/年款/版本/代际组合；`brand_id`、`series_id` 用于父级汇总。完整组合不等同于市场 SKU：未知年款不与已知年款合并。哈希 ID 来源字段写入 manifest。
4. 逐提及输出保留 `(post_id, local_product_id)`、original、evidence、canonical_id、parent IDs、status、method、review_reasons。非 resolved 记录的 canonical_id 为空；可以保留仅用于导航的 candidate/parent，而不能计入已确认车型。
5. 证据检查使用冻结输入中的命名 block 和来源类型。只归一当前产品本身可证明的字段，不把相邻竞品或用户爱车标签静默迁移。含歧义简称、未证实字段、非整车对象、集合品牌及昵称进入复核或排除。
6. 标准实体表、逐提及映射、名称映射频次、Claim 关联、报告、可搜索 HTML、检查结果和文件清单独立交付。人工复核尚未完成；规则覆盖率不解释为准确率。
7. 配置表 2411 行按字符串 specid 汇总为 9 个条目。`74430` 是“2024款 SU7 L 猜想图”，不进入正式配置候选。配置表未包含 Ultra，保留为语料实体。没有年款或完整配置描述时只给 catalog_candidates，不因候选唯一而补齐年款或精确 specid。
8. 用户允许 Qwen 辅助。按 unresolved/ambiguous 的高频原名取最多 20 项，各给一条对象原文证据、现有失败原因和配置表摘要，一次请求。响应仅为候选建议，Codex 逐项检查证据充分性；未接受的建议仍在 review-queue，不写成 resolved。
9. 配置表精确匹配使用 `autohome:spec:<specid>` 实体键；同一配置不同原名归到同键。信息不足的语料组合使用确定性 tuple 哈希，保留父车系而不伪装成已精确识别的配置。

## Risks / Trade-offs

- [别名遗漏] → 首轮偏保守，输出按频次排序的复核队列。
- [模型字段超出原文] → 以本条原文证据支持程度为质量门，异常记录不自动接受。
- [虚构车型或新闻传闻] → 名称库只声称论坛提及，保留原帖；不声称官方存在、上市或配置事实。
- [不同粒度被合并] → 版本、年款、代际独立；SU7 Ultra Prototype 与量产 Ultra、创始版与普通版分开。

## Migration Plan

数据整理使用新 v1 目录；下游可以选择通过映射连接原 Claims，不替换 V2.3 文件。回滚仅需不使用此目录。当前工作树有用户变更，不切分支或提交。未来业务接入需记录规格审批、专用分支与交付 PR。

## Validation (V1 historical)

2026-10-18 本地离线整理完成，当前交付为 `collaboration/result/auto018-product-entity-normalization/v1/final/`，规则 1.2。中间 data、data-v2、data-final 目录仅供诊断，不作为交付。

- 输入 9529 帖、15002 个提及、2343 个原名；resolved 10984、unresolved 3844、ambiguous 2、excluded 172。实体 966 个，包含品牌、车系、缺失字段组合和精确配置，不是 966 款已核实汽车。
- 165 个提及关联 7 个 specid；29212 条原 Claim—产品连接可连接新映射。
- 源哈希、全覆盖、主键、实体/父层外键、同 specid 同实体、未知年款和猜想图不精确关联、昵称不自动解歧检查通过，详见 checks.json。
- Qwen 单次 16 项的严格 JSON 请求因代码围栏格式失败；回读原文建议并逐项形成 codex-review.json，零条自动采纳，没有重试。
- 浏览器实际检查最终 HTML：15002 条分页、按 post_id 搜索、配置 specid 65768 和原文显示、昵称待复核、标注保存/刷新恢复及 JSON 下载。界面测试标注恢复未复核，下载仅为 UI 测试，不属于人工语义审阅。预览截图 v1/review-preview.png。
- `openspec validate auto-018-product-entity-normalization --strict --no-interactive`、`git diff --check` 通过。本次没有业务服务改动，业务集成测试不适用。notebook 尚未执行，分析同源脚本已运行。
- 人工语义验收、正式规格审批、业务接入、分支提交和 PR 均未完成。

## V2 Decisions

本节取代 V1 中“不用论坛语境、昵称不解歧、按 null 组合建实体”的规则。用户已在本轮明确确认并要求实施，授权证据见 proposal.md。

- taxonomy 固定为 root → brand → series → configuration；配置仅使用明确 specid，节点不包含未知年款组合。规范 ID 按品牌/车系语义生成，提及通过 node_id 加 ancestor_ids 连接。
- 所有年款、版本、代际是 mention attributes；未知保持 null，不因属性冲突丢弃已经可以识别的品牌/车系。配置仍需年款和完整名称或等价的明确限定；猜想图不进入量产配置。
- 归一优先级：本条明确品牌车型/明确排除词 → 口语别名与本条证据 → 标题/同帖无冲突对象 → SU7 论坛默认语境。小米或小米汽车单独出现只落品牌；小米 SUV 只落品牌并保留类别，不套用 SU7。
- 口语词典显式版本化：酥妻/酥七/苏七/苏7/速七等指向 SU7，但“尚界酥妻”等明确品牌冲突落尚界并待复核；毛豆3、毛豆三、毛豆Y等按别名归对应特斯拉车系。纯数字简称结合明确品牌/同帖对象；不由论坛默认上下文认定所有产品均为 SU7。
- 复用 V1 中可检查的明确名称映射作为候选并重新落层，且原字段优先级不高于本条证据。每帖提供原文 block 和来源指纹，标注 own_evidence/title/post_context/forum_alias 等依据。
- 输出 taxonomy、mention-mapping、claim-product-links、层级汇总、alias-dictionary、review-queue、V1 对照、checks、manifest、HTML 复核页；按单一最深落点及祖先路径分别汇总，不将父/子计数直接相加。
- 所有新分析脚本和测试/复核材料仅放 `collaboration/result/auto018-product-entity-normalization/v2/`，Codex 单写者，无并行接口变动。不扩数据源、不修改 V1、不启动付费抽取。

## V2 Analysis Research

按用户追加请求，调研归一后的需求主题归并、人群/场景切片、证据复核及验证流程；研究文件是方法建议，不构成新的分析模型实施清单。外部信息采用一手方法和工具文档，实际语料支持程度以本地字段检查为准。

## V2 Validation

2026-10-18：当前数据交付为 `v2/delivery-r3/`，V1 及 V2 中间目录均保留。本轮离线变更不切换 dirty 工作树、不提交或发起 PR。

- 15002 个产品提及：3118 品牌、10740 车系、220 配置、734 未解决、190 非整车/集合；14078 可映射，其中较 V1 新增 3169 个。1514 条有复核标记，允许已知车系落点与未知/冲突属性同时保留。
- taxonomy 125 品牌 + 541 车系 + 7 specid 配置，共 673 个非根节点；它是语料称谓分类，不是官方车型存在性或在售车型库。未按年款/版本的空值组合造实体。
- 21 个边界测试通过，覆盖原始字段缺失、真实口语、品牌/车系父子、比较目标归属、明确竞品优先、模糊 Max、原型车、年款不推断和手机排除。
- 全量覆盖、主键/外键、祖先不重复、树形汇总、原始输入哈希、无猜想图配置、明确配置需要年款检查通过。代码/测试也记录输入 SHA256。
- 浏览器验证 V2 节点/层级筛选、真实“酥妻”映射、原帖链接展示、标注保存与刷新恢复、JSON 导出；测试标注恢复未复核，未伪装成人工语义验收。证据 v2/verification.json、review-preview.png。
- 调研基于当前 26936 Claims、18087 个 SU7 关联 Claims 与作者/时间元数据覆盖；提出主题词典—证据卡—场景矩阵的分析路线。没有执行主题聚类、embedding、模型重抽或新的 Qwen 请求。
- 相关 Change 严格校验与 git diff --check 作为本地交付检查。最终人工语义验收、业务服务接入、代码审查、交付 PR 和合并未执行。

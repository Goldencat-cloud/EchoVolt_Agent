# Proposal

Change ID：`auto-018-product-entity-normalization`。人类 Owner：当前对话用户（实名待补）。状态：`REVIEW_READY`。

## Why

用户于 2026-10-18 确认使用 AUTO-016 V2.3 修复数据并要求先做实体归一。已有单帖产品 ID 不能跨帖使用，名称大小写、空格与粒度差异影响需求聚合。

## What Changes

- 对修复后 `contract-passed.jsonl` 的产品提及做离线整理，V2 采用品牌 → 车系 → 有明确 specid 的配置 taxonomy；逐提及只落到能识别的最深节点，不再按空值组合创建实体。
- 年款、版本、代际作为提及属性保留。使用汽车之家 SU7 论坛来源、标题、同帖上下文与口语别名词典消歧；明确品牌/车型与冲突信息优先于论坛默认对象。保留原对象、局部 ID、证据和规则来源。
- 采用 resolved / ambiguous / unresolved / excluded 状态；无法证明的映射不进入已归一统计。
- 纳入用户追加提供的 `G:/Download/su7_配置明细_长表.csv` 快照，区分 8 个在售/停售条目与 1 个猜想图。仅在原帖年款及完整配置名称均支持时关联 specid；未收录不证明车型不存在。
- 原数据只读，不重新调用模型，不修改单帖抽取契约；本次不做事件归一、用户身份合并、属性词表、需求聚类或业务服务开发。

## Capabilities

### New Capabilities

- `product-entity-normalization`：已有论坛产品提及的可追溯、保守跨帖归一。

### Modified Capabilities

无；当前正式 specs 为空，AUTO-016 与 AUTO-017 保持原样。

## Impact

V1 保留在 `collaboration/result/auto018-product-entity-normalization/v1/`；本轮新增 `v2/` 的 taxonomy、提及映射、分析复现脚本、验证与复核页。不改现有抽取工具、单帖契约或应用服务。

授权证据：用户“对的，你先帮我做一下实体归一。”支持本次离线数据操作。业务功能实施、规格审阅人/日期/审阅 commit/正式验收与 PR 均待记录，本次不声称这些审批完成。当前 dirty 工作树不切分支，不覆盖其他 Change；未来工程实现需专用 `change/auto-018-product-entity-normalization` 分支和唯一交付 PR。

用户另明确“实在不行你也可以调用qwen进行实体归一。”，授权必要的有界辅助判断。最多先选 20 个高频歧义名称，各附一条原始对象及其证据，调用一次现有 Qwen API；不扩全量、不自动重试、不自动应用建议。

## V2 scope approval

2026-10-18，人类 Owner 当前对话用户明确提出“能到哪个层级就到哪个层级”“做成 taxonomy”，并要求将“酥妻”等口语写法结合 SU7 论坛来源归类；对上述方案明确“开始做”。本轮对话构成本次离线 V2 范围、接口和实现授权；审阅 commit 暂无（未提交工作树），以本节与相关文件哈希定位，不虚构已审 commit。正式交付验收、PR 和服务接入仍未完成。用户追加要求调研归一后的分析路线，属于研究材料，不自动授权运行新模型实验。

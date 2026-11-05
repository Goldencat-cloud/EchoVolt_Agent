# Proposal

Change ID：`auto-020-forum-evidence-model`。人类 Owner：当前对话用户（实名待补）。状态：`REVIEW_READY`，仅指建模提案待审，不表示已批准业务实施。

## Why

SU7 论坛已有逐帖 Claim 和产品归一结果，但缺少可以稳定连接、验证和导出的跨帖数据模型。需要把产品客观配置、作者评价、作者时点状态及分析推导分开，避免将试驾者视为 SU7 持有者、将负面表达写成产品事实或丢失证据。

## What Changes

- 定义 `forum-evidence-model/1.0`：User、Post、Claim、Product、Evidence、Event 六类核心实体，及带主外键的产品提及映射、属性字典、配置值、比较记录和用户状态配套结构。
- 产品目录采用重点品牌／车系白名单；品牌、车系、明确配置共用 Product 目录节点，通过 HAS_PARENT 组织，不做不同语义类型之间的 ISA 推理。Aspect、情感、场景和需求不新增业务节点。
- 细化产品属性的三层语义：字典定义、带来源的客观配置值、Claim 中针对属性的评价；未知与范围外记录保留原词，不强制实体化或补齐属性。
- 为现有 V2.3 与 AUTO-018 delivery-r3 制定无损适配、版本／来源／证据／归一状态契约；复用中文枚举，不覆盖原抽取。AUTO-017 的 need_signals 方案保持独立，本版不切换到新抽取契约。
- 定义可操作的 JSONL 交换表、SQLite 验证存储、图节点／关系投影、错误代码、导入顺序、回滚方式、查询验收与定向语义复核流程。SQLite 是待审批的本地实现默认选项，不是本轮已部署组件。
- 规划最小离线导入及证据查询验证；不增加 Agent 算子、聊天 UI、主题模型或新付费调用。
- 纳入 `G:/Download/user_profiles.csv`，增加按抓取时点保存的用户资料配套表；平台字段、代词推断、IP属地与原CSV地域分别保留，不作为真实身份或持有车辆认证。
- 2026-10-19获用户确认，先执行独立的探索图试建P1–P3：全量现有抽取集与用户资料连接、节点/边/辅助记录导出及本地交互预览；不等于实施全部正式模型与SQLite/严格查询任务。

## Capabilities

### New Capabilities

- `forum-evidence-model`：已有论坛抽取与产品目录的可追溯建模、无损适配、验证和图投影契约。

### Modified Capabilities

无。当前正式 specs 为空。AUTO-016/017/018 的 Prompt、Schema、代码和历史结果均只读；AUTO-019 算子骨架不作为本 Change 的依赖或实施入口。

## Impact

本轮只新增本目录下 proposal、design、delta spec、tasks；不写代码、不建数据库、不重跑抽取、不切换 dirty 工作树、不提交或创建 PR。当前基线 HEAD 为 `35d6c095dc35c59ef0a5127e16fe601224832553`，所在分支 `change/auto-016-modular-post-extraction`，存在大量既有未提交文件，全部保留。

上段为最初提案阶段范围。2026-10-19追加授权：用户在已展示四份文档改动和限定试建范围后回复“嗯嗯”，同意资料快照修订与一次离线试建。正式全套模型仍待审批；试建在专用工作区/开发分支进行，源数据只读，不改当前dirty工作树的代码，不提交/创建PR/部署服务。人类Owner为当前用户；无已审提交可填，审阅对象为本次对话列出的变更及试建范围，reviewed_commit=null（未提交文件），不虚构commit批准。

未来实施的建议文件范围、独占写入者、导入接口及测试见 design.md。实施前须获得本提案规格批准，建立专用 `change/auto-020-forum-evidence-model` 开发分支与唯一交付 PR；不能把本轮写文档授权解释成业务实施或合并授权。

### Review record

- 请求来源：2026-10-18，用户“给我一个建模提案，细化到可操作的程度。”
- 授权范围：生成可审阅建模提案；不是已审批准后的实施。
- 审阅人、审阅 commit、规格 verdict：待人类 Owner 记录；本轮尚无该提案提交，不虚构已审 commit。
- 待审批的建议默认值：design.md 第2节本地存储、第7节范围白名单、第14节复核门；它们已经具体化，但不是已获批准的实施决定。未批准前不开始实施。

### Planning validation

- 2026-10-19：四份规划artifact已齐备；`openspec validate auto-020-forum-evidence-model --strict --no-interactive`通过。
- `git diff --check`通过（仅覆盖tracked diff）；另对本Change新增文档执行尾随空白检查，无命中。
- 这仅证明规划文件的结构与基本格式检查通过；没有执行模型导入、查询、业务测试或人类语义验收。tasks全部保持未勾选。

上述为最初规划检查记录，后续状态以design末尾Pilot evidence为准：2026-10-19已完成用户授权的探索图P1–P3及用户资料快照接入，原24项正式实施仍未开始。完整提案仍待批准；有限试建不作为正式模型或语义接受。

# Design

## Context

现有 V2.1 将帖子 block、图片说明、产品实体、claims、events、作者状态和摘要一次提交给 Qwen。抽检已发现 quote 省略号/跨片段拼接、车型过度归一化、图片说明升级为作者事实、画像证据不逐项覆盖，以及低价值表达单独成 claim。

本设计只服务单贴信息抽取。跨帖子聚合、产品分析和决策支持由后续 Change 负责。

## Goals / Non-Goals

**Goals:**

- 让每个命题都能回挂到同一帖子中的原始证据。
- 保留原始提及，保守处理车辆、非整车对象、事件和作者明确事实。
- 把比较关系作为单贴命题的可选结构，不把它扩展成独立决策模块。
- 用阶段缓存、条件跳过和固定 100 条样本控制成本并可复盘。
- 保留九根字段并按最新V2.3 Schema校验claims子结构，同时保留历史V2.1结果的读取能力，不混淆版本。

**Non-Goals:**

- 不做跨帖子实体合并、事件时间线、排名、推荐或购买决策。
- 不核验外部新闻/政策，不把论坛背景或图片说明当作作者事实。
- 不重跑全量语料、不修改历史结果、不自动删除帖子或图片。
- 不引入向量数据库、复杂 Agent 编排或新模型供应商。

## Decisions

### 1. 三个最小阶段

先以完整改进契约 `prompts/full-v2.2.md` 为语义来源，再生成两个阶段Prompt。V2.1原文快照保持不变；完整定义、枚举、边界和示例的分配由 `migration-v2.2.json` 逐节记录，禁止用缩写分类表替代。

1. **输入与证据准备（确定性）**：读取并冻结 `004_A4_图片策展_主链路终版.csv`，规范 block_id、来源类型、图片说明边界、输入哈希和固定种子样本；不调用模型。
2. **候选证据抽取（Qwen）**：发现稀疏候选，保留连续 quote、block_id、说话者/转述状态和原始提及；不做车型补全、事件摘要或作者画像推断。
3. **单贴命题与对象整理（条件 Qwen + 确定性适配）**：在候选证据上保守归一化对象，整理去重后的体验/问题/需求/评价、事件提及、明确作者事实和可选比较关系，生成单贴摘要和 V2.1 兼容包。

比较是主张上的可选关系，沿用中文枚举 `A优于B/A弱于B/A与B相当/存在差异但方向不明/无法判断`。保留作者明确表达的购买建议或决策，不由模型自行生成总体优劣或建议。

### 2. 中间格式以证据为主

V2.3候选包含 `candidate_id`、`raw_mentions`、`raw_text`、`speaker`、`source_status` 和 `evidence[]`；不使用少数互斥kind标签丢弃行业/技术/转述信息。证据为真实block_id、source_type=text/image_summary和可回挂quote。最终整理保留原九根字段，比较保留在claims内，不重命名products或post_summary。运行时把标题复制为首个普通文本block T0，输入根title仍保留；不重新调用视觉模型；URL/路径和空summary不算图片理解。

### 3. 确定性质量门

对每个 quote 做对应 block 回挂校验：先做精确匹配，再保守接受空白/标点归一化及同一block内有序省略号片段；无法回挂仍失败。并检查 block_id、枚举、ID 唯一性和引用关系。质量门失败时保留 raw response 供审查，但不生成可交付记录。

### 4. 保守对象与事件规则

同帖明确指向同一车辆时去重，同时保留 `mention_text`。品牌、车系、年款、版本无法由帖子确认时使用未知值；“毛豆”、无品牌简称和仅图片疑似车型不得借论坛背景补全。车衣、贴膜等非整车对象可保留为相关提及，不进入车辆产品表。事件仅记录帖子支持的外部发生事项并生成简洁摘要；作者态度、影响或解释另记命题，不自动建立因果关系。

### 5. 成本与缓存

- 阶段缓存键包含完整输入哈希、阶段名、提示词版本、Schema 版本、模型和图像处理配置。
- 已验证阶段缓存命中时跳过调用；候选为空不证明原帖无信息，不能仅凭此生成空包或删除帖子。
- 后续模型读取完整原帖和既有图片说明，候选仅用于导航，允许补回遗漏。以稳定前缀、缓存和有限调用数控制成本，不截断语义输入。
- 记录调用数、输入/输出/缓存 token、延迟、命中、跳过和失败原因。
- 首轮使用当前完整图文整合数据固定种子 `20261016` 抽取 100 条，与同 100 条的 V2.1 结果对照；若端到端 token 超过 2 倍且抽检没有明确收益，则停止扩展。

### 6. 兼容和回滚

最新完整Prompt与阶段版本为V2.3，输出Schema为2.3；V2.2保持历史完整契约，旧candidate-v1、post-pack-v1和taxonomy-v1为历史草稿。运行器未接入新契约前不得启动实验。旧结果只读保留，模块化结果放独立目录。

### 7. V2.3四项局部契约变更

experience_basis仅判断作者亲历依据，使用明确亲历/明确非亲历/无法判断/不适用；statement_type保留表达性质，原预期/假设语义保留在content中。

comparison仅在claim内，包含product_ids与带证据的relations，每个关系为subject_product_id/object_product_id/aspect/relation/evidence；只记录明示关系，不补传递关系，不为多品共现制造比较。

sentiment_score删除，以sentiment_intensity弱/中/强/无法判断替代；中性使用null，不明确必须无法判断。使用情境为claims[].usage_context={summary,evidence}或null，不扩展为长期画像。

定义详见完整Prompt 6.10/6.11/6.13/6.15，结构详见schemas/post-output-v2.3.json。程序验证器为tools/post_contract_v23.py，验证结构及引用，不负责证明语义准确。

### 8. 全量失败修复与单次定向重跑

`single-v23-full` 保持只读，新产物写入 `single-v23-full-repair1`。修复器先重新读取 manifest、冻结输入、失败 review 和 raw response，核对 554 个失败 ID、输入哈希和原始文件哈希，然后按下列顺序处理：

1. 只忽略 Unicode 空白、分隔符和标点后仍为同一 block 连续字符的 quote，可作为格式差异重新校验；不得忽略字母、数字、汉字、符号含义或字符顺序。
2. quote 按现有规则只能匹配一个其他 block 时，可纠正 `block_id` 和由 block 类型确定的 `source_type`；零个或多个候选时拒绝修复。
3. 只有调用目录名、manifest post_id、冻结输入 post_id、输入哈希和缓存/请求身份均一致时，才纠正 payload `post_id`。
4. 其他错误不做字段删除、补写、重排或语义猜测，进入根因清单和定向重跑队列。

修复器输出逐条 audit，包含原始 review/payload 哈希、修复后 payload 哈希、规则、字段路径、重校验错误和最终状态。修复后的 payload 与原 raw response 分开保存。

定向重跑继续使用 `full-v2.3.md`、2.3 wire/local Schema、`qwen3.8-27b`、temperature 0、thinking false 和 max_tokens 8192；并发降为 3，以减少此前集中传输失败的影响。每个新调用目录只允许创建一次，失败目录不得自动再次发送。旧代码把底层传输/JSON异常统一为 `api_transport_or_json_error`，新运行额外记录不含消息和敏感内容的异常类型，便于区分网络、超时和JSON解析根因。

最终生成修复清单、重跑清单、逐条最终状态和 9701 条覆盖报告。9147 条原通过记录直接引用原结果且逐字节核对；只有白名单修复后通过或重跑后通过的记录进入新的契约通过集合。合并成功仍不表示人工语义准确率已测量。

## Risks / Trade-offs

- 调用次数增加：用阶段缓存、条件跳过和紧凑输入控制，并以固定 100 条对照实测。
- 阶段压缩丢失上下文：每个候选保留原始 quote、block_id 和 raw_text。
- 实体仍可能过度归一化：默认未知并保留原始提及。
- 事件转述可能低价值：要求事件有明确发生事项，纯转述不复制全部信息点。
- 结构化通过不等于语义正确：保留人工抽检和问题清单，不把 Schema/quote 通过率当准确率。

## Migration Plan

1. 先实现阶段契约、缓存 manifest 和质量门，不改变 V2.1 入口。
2. 从 `004_A4_图片策展_主链路终版.csv` 按 `20261016` 固定种子抽取 100 条，做 V2.1 与模块化影子对照。
3. 生成独立模块化结果目录、逐帖包和对照报告，不覆盖历史输出。
4. GPT/人类 Owner 审阅成本与语义报告后，才决定是否将入口设为默认。

## Open Questions

- v23-run1历史试跑HTTP400；后续用户明确继续实施，diagnostic-original-schema单次请求取得服务端Grammar error，确认不支持uniqueItems。v23-run2把该关键词仅从wire schema移除，本地完整Schema和Prompt仍要求去重，两个探针已通过并开始批量。不是降低最终验收约束。
- 验证留档：collaboration/result/auto016-modular-post-extraction/v23-run1含manifest、inputs、calls、progress、failures、diagnosis及review.html。已报告12931 Token仅覆盖两次成功请求，失败请求用量未知。程序检查不代表语义准确。

- 人类 Owner、规格审阅人和交付分支尚未指定。
- 非整车提及是否单独落到 `related_products`，待下游查询需求确认；本 Change 先保留原始提及。
- 成本停止线需由 100 条对照实测确认。
- 9 条历史截断均达到 8192 completion tokens；本轮按用户要求原参数重跑一次，若仍截断则保留失败。任何拆帖、压缩Prompt或降低信息完整性的适配须另行设计和批准。

## 完整Prompt单调用补充实验

固定200新帖（seed=2026101603，排除v23-run2的100帖），输入同源且完整保留。full-v2.3.md原样冻结，作为system稳定前缀；单个原帖JSON作为user输入，输出按2.3 Schema strict解码，wire仅去除不支持的uniqueItems，本地完整检查不变。并发3、每帖最多一次、max_tokens8192、无thinking。先dry-run再从200样本中做一个短帖探针，复用其成功记录，不额外增加样本/付费对照。传输/权限/结构化端点错误停止扩展；内容门失败保留继续。成功、结构解析成功但业务门失败与API失败分开统计；全量未授权启动。保留标题证据现有局限，不静默改Prompt或Schema。所有输入、脚本、Prompt、Schema和任务包hash冻结。允许文件：tools/auto016_single_v23_200.py、相应测试、本Change试验记录及delegations/single-v23-200、collaboration/result/auto016-modular-post-extraction/single-v23-200。

你负责原提示词的第一阶段：发现候选和定位证据。下方将完整提供用户原始 V2.1 契约，所有定义、语义边界和示例仍有效。

任务：输出一个 JSON 对象 {"schema_version":"candidate-v1","candidates":[]}。

kind 是内部路由标签，不替代原 claim_type、statement_type 等分类。允许 experience、problem、need、evaluation、comparison、event_mention、author_fact、information、technical、industry、other。分别覆盖经历、问题、需求/决策、评价、比较、事件、作者明确信息、事实/转述、技术机制、行业政策及其他有价值候选。可重叠时选主要一种，不为标签重复候选。
候选包含 candidate_id、kind、raw_text、speaker、source_status、evidence；raw_text保留原始表达和限定语。speaker 使用 author/quoted_other/unknown；source_status 使用 author_text/quoted_text/image_summary/unknown。
原契约的产品、事件、作者信息及重要观点均需覆盖；不得只留下符合少数kind的内容。后续阶段仍读取完整原帖，候选不是唯一事实来源。

硬约束：
- 每个候选引用真实text/image block的连续原文，source_type沿用text/image_summary；根title仅提供语境，不能创建虚构标题block。
- 必须填写真实 block_id、source_type、speaker 和 source_status。
- 图片只能描述图片中明确可见的信息；图片说明或图片内容不能单独证明作者拥有、购买、年龄、预算、偏好或情绪。
- 不补全品牌、车系、年款、配置，不把论坛名称当作帖子事实。
- 本阶段不生成最终摘要或分类结果，但必须保留原文明示的购买建议、决策和理由作为候选，不替作者产生新建议。禁止人格推断、跨帖结论和外部核验。
- 证据不足就不输出候选，不用低置信度包装猜测。

只输出合法 JSON，不输出 Markdown 或解释。

仅本阶段的临时输出结构覆盖原契约第3节的最终输出要求，其余定义保持。原6.3示例中的“产品评价”与6.4正式枚举不一致，分类按6.4“产品体验与评价”执行；原文件保留不改。

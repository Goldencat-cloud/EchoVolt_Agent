# corpus-cleaning 变更（delta）

## ADDED Requirements

### Requirement: 清洗只读边界
清洗模块 SHALL 以只读方式连接 stock 业务表，MUST NOT 修改 posts/users/product_* 原值；全部清洗产出写入独立标注表（schema 版本化），并可全量重跑（同 cleaning_version 同输入 → 同输出）。

#### Scenario: 原值不被修改
- **WHEN** 清洗运行前后对比 posts 表 9994 行
- **THEN** 业务列值与 record_hash 不变，仅新增标注表行

### Requirement: 删除帖与空行剔除
系统 SHALL 剔除含"本楼已被删除"等删除标记的行，以及既无文本也无任何媒体的行；仅含图片/视频的纯媒体帖 SHALL 保留。剔除与保留依据当年审核列（legacy_body_match_status）与 content_segments_json 判定，不依赖在线探测。

#### Scenario: 删除帖剔除
- **WHEN** 帖子正文含"本楼已被删除"标记
- **THEN** 该帖标注 excluded=post_deleted，不进入语义子集

#### Scenario: 纯媒体帖保留
- **WHEN** 帖子正文为空但 content_segments_json 含图片/视频段
- **THEN** 该帖保留，polished_text 为空

### Requirement: review_required 定级
系统 SHALL 依 2026-10-22 抽查结论对 226 条 review_required 定级：正文空且有图片段者保留为图片帖（polished_text 为空、不标 excluded）；正文与媒体段皆空者标 excluded=empty_no_media。Owner 2026-10-22 指示：历史帖被删除情况量级小且库内无法确证，SHALL NOT 做专门的在线探测或疑似删除标注；当年审核列中的删除标记文本仍按删除帖剔除。

#### Scenario: 存活纯图帖放行
- **WHEN** 帖子正文空且 segments 含图片段
- **THEN** 该帖不标 excluded，按图片帖进入多模态输出

#### Scenario: 无媒体帖排除
- **WHEN** 帖子正文与媒体段均为空
- **THEN** 该帖标 excluded=empty_no_media，库中保留行，不进入语义子集

### Requirement: 产品别名映射
系统 SHALL 维护产品别名映射表 product_aliases：alias 归一键、canonical 目标（series_id 或 spec_id）、alias_type（official/variant/community/competitor）、来源与确认状态。别名 SHALL 从三处生成：官方名规则切分变体；语料高频短语挖掘（归一匹配或编辑距离阈值内）；人工种子与确认。映射 SHALL 仅向上归一（细粒度叫法到粗粒度 canonical）：车系名、品牌名或无配置语境的短语 MUST 只解析到 series 级，MUST NOT 映射到具体 spec_id；仅当别名自身含完整配置语义（官方 spec 全名）时才 MAY 指向 spec_id。映射 SHALL 幂等可重跑；未确认别名 SHALL NOT 被抽取阶段消费。

#### Scenario: 官方名变体
- **WHEN** spec_name 为"2026款 后驱标准版"
- **THEN** 生成剥离年份的变体别名，canonical 指向该 spec_id

#### Scenario: 语料社区叫法
- **WHEN** 语料中"su7max"归一后与官方名变体匹配
- **THEN** 生成 community 别名指向对应 canonical，来源标记为语料挖掘

#### Scenario: 禁止向下细粒度解析
- **WHEN** 语料仅提及车系名"su7"，未含任何配置语境
- **THEN** canonical 解析到 SU7 车系（series 级），MUST NOT 指向任何具体配置 spec_id

#### Scenario: 待确认不消费
- **WHEN** 挖掘候选无法机械消歧
- **THEN** 该别名状态为待确认，抽取阶段不使用

### Requirement: 文本去重（精确+归一近重复）
系统 SHALL 对非空正文做归一化（NFKC 全→半角、ASCII 小写、连续空白压为单空格）生成 norm_key 分组，同组仅首条 is_duplicate=False，其余 True 并共享 dedup_group_id；空文本不参与去重（dedup_group_id=0）。norm_key SHALL NOT 用于输出文本归一。

#### Scenario: 归一近重复合并
- **WHEN** 两帖正文仅差大小写、全/半角或多余空白
- **THEN** 归一后同组，仅首条 is_duplicate=False

#### Scenario: 空文本不参与
- **WHEN** 帖子正文为空
- **THEN** dedup_group_id 为 0，不进入任何分组

### Requirement: 系统废串与纯符号标注
系统 SHALL 将命中 `查看详情|我要申诉|加载中|点击展开|展开更多` 的正文标 excluded=system_junk，将仅由退化装饰符号组成的正文标 excluded=gibberish；两类行 MUST NOT 从库中物理删除。

#### Scenario: 系统废串
- **WHEN** 正文含"查看详情"等废串
- **THEN** excluded=system_junk，行保留

#### Scenario: 纯符号
- **WHEN** 正文非空且全部字符为装饰符号
- **THEN** excluded=gibberish；空文本与纯 emoji 不标

### Requirement: 深度净化 polished_text
系统 SHALL 生成 polished_text：HTML 实体解码、全角数字归一半角（SHALL NOT 对输出使用 NFKC 以保留全角标点）、剥离 @提及/#话题#/URL、剔除 emoji（不设独立 emoji 列）、折叠空白；基于 posts.clean_text 叠加，原始 body_text 不变。

#### Scenario: 符号剥离
- **WHEN** 正文含 @user、#话题# 或 URL
- **THEN** polished_text 中被移除，emoji 剔除且不单列

#### Scenario: 全角标点保留
- **WHEN** 正文含全角标点
- **THEN** polished_text 保持全角原样

### Requirement: 多模态平行清洗 polished_multimodal
系统 SHALL 基于 content_segments_json 生成 polished_multimodal：text 段应用与 polished_text 同款净化；image/video 段的 URL/ID SHALL 原样保留（SHALL NOT 执行 URL 剥离），保序输出。

#### Scenario: 图片 URL 保留
- **WHEN** segments 含 image 段
- **THEN** polished_multimodal 中该 URL 与原值一致，总量前后一致

### Requirement: 隐私脱敏
系统 SHALL 在 polished_text 与 polished_multimodal 的 text 段对手机号（1[3-9]\d{9}）、显式 QQ 号（QQ+5-11位数字）与≥7位连续数字打码；原始 body_text 保留不脱敏。

#### Scenario: 手机号打码
- **WHEN** 正文含手机号
- **THEN** polished_text 中为 138****5678 形式，原始列不变

### Requirement: 变更标记与 clean 子集视图
系统 SHALL 输出 text_changed 标记（polished_text 与归一基座不同；归一基座 = 原文去零宽字符、折叠连续空白并去首尾空白，口径与旧管线 text_content 规范化一致，用于校验锚点复算；净化输出本身不受基座影响）；clean 高置信子集 = 排除 excluded 非空、is_duplicate=True、polished_text 为空的行，以库视图或导出文件呈现；原始行 MUST NOT 物理删除。

#### Scenario: 子集过滤
- **WHEN** 查询 clean 子集
- **THEN** 不含 excluded 非空、is_duplicate=True、polished_text 空的行，且每行可经 post_id 回挂原文

### Requirement: 水军与广告识别
系统 SHALL 以规则法与库内聚合标注垃圾内容：广告帖（联系方式模式与促销话术关键词组合命中）标 excluded=advertising；水军嫌疑（同作者≥3帖norm_key相同、跨账号共享norm_key、新号爆发发帖）标 spam_suspect=1 并记录 spam_reasons_json。规则明细 MUST 写入字段契约文档；水军嫌疑 SHALL NOT 自动排除出子集，仅供人工复核与下游降权。

#### Scenario: 广告帖排除
- **WHEN** 正文同时命中联系方式模式与促销话术关键词
- **THEN** excluded=advertising，行保留在库中，不进入语义子集

#### Scenario: 协同模板帖标记
- **WHEN** 不同作者的多帖共享同一 norm_key
- **THEN** 相关帖 spam_suspect=1，spam_reasons_json 记录命中的作者与帖 ID 明细

### Requirement: 标注落库（只入库，不做 CSV 导出）
系统 SHALL 将标注写入 stock 库标注表 cleaning_annotations：每帖一行，post_id 主键、cleaning_version 与 generated_at 列；列清单 SHALL 至少含 excluded、norm_key、dedup_group_id、is_duplicate、polished_text、polished_multimodal、text_changed、spam_suspect、spam_reasons_json；posts 原值 MUST NOT 修改，行数与 9994 一一对应；SHALL NOT 输出独立 emoji 列与用户/车主分群列（Owner 2026-10-22 指示：用户分群属特征工程，归信息抽取阶段），SHALL NOT 生成 CSV 导出文件。

#### Scenario: 对齐落库
- **WHEN** 清洗完成
- **THEN** cleaning_annotations 每行 post_id 与 posts 一一对应，post_id 与 cleaning_version 构成可重跑版本标识

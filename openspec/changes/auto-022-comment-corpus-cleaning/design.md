# auto-022-comment-corpus-cleaning Design

## 1. 输入与旧契约迁移映射

输入为 stock 库（9994 帖，只读业务表）。旧 CSV 清洗契约逐条映射：

| 旧 spec Requirement | 新架构落点 | 处置 |
| --- | --- | --- |
| 内容字段归一与保序（text_content/multimodal_content） | posts.body_text / content_segments_json（含 locator，更强） | 已取代，不重建；清洗直接引用 |
| 数字字段提取整数 | posts.view_count/reply_count（已 9994 整数化，legacy-4 重导） | 已取代 |
| JSON 结构化字段解析（作者信息） | posts.author_context_json（7字段）+ users 表；profile_raw 已按存储精简原则移除 | 已取代 |
| 时间字段解析与相对时间反推 | posts.published_at/time_precision/time_basis（explicit/list_page_time） | 已取代 |
| 可追溯主键 post_id | posts.post_id 主键 | 已取代 |
| 基本文本规范化（实体/空白） | posts.clean_text（采集层） | 已取代；深度净化在其上叠加 |
| 删除帖与空行剔除 | 清洗层新实现 | 待建 |
| 文本去重（norm_key/dedup_group_id/is_duplicate） | 清洗层新实现 | 待建 |
| 系统废串/纯符号 gibberish 标注 | 清洗层新实现（excluded 列） | 待建 |
| 文本净化 clean_text（@/#/URL/emoji 剥离、全角数字归一） | 清洗层新实现 | 待建（命名调整见决策3） |
| 多模态平行清洗 | 清洗层新实现（基于 content_segments_json） | 待建 |
| 隐私脱敏 | 清洗层新实现 | 待建 |
| 车主分群 owner_segment | 移出清洗范围（Owner 2026-10-22 指示：属特征工程，归 B 阶段信息抽取） | 移出 |
| clean 子集视图与标注输出 | 清洗层新实现（SQLite 视图/表 + CSV 导出） | 待建 |

## 2. 关键决策（待 Owner 审查）

### 决策1：输入走库、不走 CSV
旧 spec 假设 23 列 CSV；新契约以 stock 库为唯一输入（01_ingestion 已完成结构化）。CSV 原件仅作追溯（source_snapshots）。旧"是否匹配正文"审核列已存于 source_snapshots.issues_json.legacy_body_match_status，清洗层读取用于删除帖判定。

### 决策2：输出形态——只入库，不做 CSV 导出（Owner 2026-10-22 指示）
清洗标注写入 stock 库标注表 cleaning_annotations，post_id 主键，cleaning_version 列；不修改 posts 原值；可全量重跑。落库列清单（每行一帖）：
- 标识：post_id、cleaning_version、generated_at
- 剔除级：excluded（空 / post_deleted / post_removed_suspect / empty_no_media / system_junk / gibberish / advertising）
- 去重：norm_key、dedup_group_id、is_duplicate
- 净化：polished_text、polished_multimodal、text_changed
- 风险标记：spam_suspect（0/1）、spam_reasons_json（命中规则明细，可解释）
理由：B 阶段（抽取/索引）直接 SQL 消费；CSV 导出取消（Owner 指示），人读场景用 SQL/DB Browser 即可。
用户/车主分群移出清洗范围（Owner 2026-10-22 指示：属特征工程，归 B 阶段信息抽取）。

### 决策3：净化列命名——polished_text，避免与 posts.clean_text 混淆
采集层已有 posts.clean_text（基本规范化）；旧 spec 的 clean_text 是更深净化（@/#/URL/emoji 剥离）。若同名会语义混乱。清洗输出列定名 `polished_text`（深度净化文本）与 `polished_multimodal`；旧 spec 术语在 spec delta 中映射说明。

### 决策4：226 条 review_required 定级规则（Owner 2026-10-22 简化指示）
- 正文空且有图片段：保留为图片帖，polished_text 为空，不标 excluded；
- 正文与媒体段皆空（约21条）：标 `excluded=empty_no_media`；
- 历史疑似被删帖：量级小且库内无法确证，Owner 指示不做专门监测与标注，不设 post_removed 类别；当年审核列中的删除标记文本仍按 post_deleted 剔除。

### 决策5：去重与标注口径沿用旧实测值作校验锚点
旧实测：9994→剔除删除帖3+空行21→9970；重复61；废串4+gibberish1；clean 子集 9701；URL 前后 22681 一致；text_changed 667。新输入与旧 CSV 同源（9994），预期数字可复算；允许个位数漂移但须逐项解释（例如 21 条无媒体帖在新规则下属 excluded=empty_no_media，与旧"空行21"预期吻合）。

### 决策6：pure-text 拼接口径
旧 spec text_content 为"全文 JSON 中 text 片段拼接"。新库 content_segments_json 的 text 段即同一内容（body_text 为其拼接），清洗层不重复拼接，直接以 body_text 为准，校验其与 segments text 段一致性（抽样）。

### 决策7：水军与广告识别——规则法+库内聚合（Owner 2026-10-22 新增要求）
调研结论（外部搜索）：识别精度阶梯为规则65%→ML80%→图论90%→LLM87%；stdlib-only 清洗层选择规则法+库内聚合，可解释零依赖。
- 广告帖（内容规则，确定性较高）：正文命中联系方式模式（微信号/电话/QQ变体）与促销话术关键词（低价/优惠/代购/转让/贷款/加V等）的**组合**才标 excluded=advertising，避免"这车广告打得好"类误伤；短链/外链堆叠为辅助信号。
- 水军嫌疑（库内聚合，只标不排）：spam_suspect=1 依据——同作者≥3帖 norm_key 相同；跨账号共享同一 norm_key（协同模板帖）；registered_at_raw 与发帖时间接近且 platform_post_count 异常。r1/r2 仅对未剔除行且归一键长度 ≥8 生效（Owner 抽查指示：排除"小米su7"类超短常见语与已剔除内容噪声）。spam_reasons_json 记录命中规则明细，供人工复核与下游降权；不武断排除（规则法精度有限）。
- 复用：norm_key/dedup 分组与隐私脱敏的联系方式正则直接复用。

## 3. 模块结构

```
02_cleaning/
  src/corpus_cleaning/        # contracts(规则常量) polish(净化/归一) annotate(剔除/去重)
                              # spam(水军嫌疑) aliases(别名映射) store(建表/落库) pipeline(主管线) cli
  tests/                      # 单元+集成（真实库副本：锚点复算/只读边界/确定性重跑）
  tools/                      # run_cleaning.py（CLI 包装）、inspect_*.py（人工抽查脚本）
  docs/                       # data-contract、field-mapping、evidence
  pyproject.toml              # autoinsight-cleaning 入口（stdlib-only，零依赖）
```
依赖：Python 3.11 stdlib-only；只读连接 stock（WAL 已开），写仅限标注表。
CSV 导出已按 Owner 指示取消（决策2），views/export 并入 store/pipeline。

## 4. Verification Record

实施级验证已完成（2026-10-22，AI 实施，**未经人类代码审查**）：60 项测试通过（含 stock 库副本上的
锚点复算、只读边界 record_hash 对照、同版本确定性重跑、人工 confirm/reject 不被覆盖）；实测报告见
`02_cleaning/docs/evidence/cleaning-run-20261022.md`。锚点复算：删除帖 3/3、空媒体 21/21、
重复 61/61、废串 4/4、gibberish 1/1、text_changed 667/667 全对齐；clean 子集 9694（-7 = 新增
advertising 剔除 7 条，逐项解释见证据）；多模态媒体段前后一致（23693=23693，绝对数与旧 22681 的
口径差异与 -20 图片差额已在证据中说明）。Owner 代码审查与验收（任务 3.6）待执行。

### 决策8：产品别名映射表来源（Owner 2026-10-22 新增）
表 product_aliases（alias_norm 主键、canonical_series_id/canonical_spec_id、alias_type、source、status、created_at），四类来源按置信序：
1. official：库内权威名——product_specs.spec_name（9配置全名）与 series 表车系名/品牌名，直接登记；
2. variant：官方名规则切分变体——剥离年款前缀（2026款）、配置后缀组合，机械生成；剥掉配置语义的变体 canonical 相应上移到 series 级；
3. community：语料挖掘——对 9994 帖正文做车名短语统计（与官方名归一匹配/编辑距离阈值），高频候选进表，标 status=pending 待人工确认；归一规则复用 norm_key（NFKC/小写/压空白）；
4. competitor：竞品车名表——人工种子起步（帖内高频提及的竞品牌/车系），后续可从公开车系库扩充；纯人工确认。
规则：映射方向只向上归一（细粒度叫法 → 粗粒度 canonical），禁止向下展开——车系名/品牌名/无配置语境的短语 MUST 只解析到 series 级，MUST NOT 映射到具体 spec_id；仅当别名自身含完整配置语义（官方 spec 全名）时才指向 spec_id。挖掘候选不自动消费；alias_type 与 status 分离；幂等重跑。产出时点：与清洗同遍历（2.x）挖掘，人工确认后供 B 阶段抽取消费。

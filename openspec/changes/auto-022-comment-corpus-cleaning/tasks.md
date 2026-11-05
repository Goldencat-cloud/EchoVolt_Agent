# auto-022-comment-corpus-cleaning Tasks

## 1. 模块骨架与只读边界

- [x] 1.1 建 02_cleaning 模块（src/corpus_cleaning、tests、tools、docs），Python 3.11 stdlib-only，只读连接 stock；记录基线（9994 帖、review_required 226、模块版本）。
- [x] 1.2 旧 CSV 列→新库列映射文档（docs/field-mapping.md），覆盖旧 spec 23 列与标注列的对应关系；旧实测数字（9970/61/9701/22681/667 等）登记为校验锚点。

## 2. 标注实现（按 spec delta 逐条）

- [x] 2.1 删除帖与空行剔除判定（读 legacy_body_match_status + segments 构成），输出 excluded=post_deleted / empty_no_media（后者含 21 条无媒体帖的初始分级）。
- [x] 2.2 226 条 review_required 定级落地：正文空且有图保留为图片帖、正文媒体皆空标 excluded=empty_no_media（Owner 简化指示：不做疑似删除标注，见 design 决策4）。
- [x] 2.3 文本去重：norm_key 生成、分组、dedup_group_id/is_duplicate；空文本不入组。
- [x] 2.4 系统废串与纯符号标注（excluded=system_junk/gibberish）。
- [x] 2.5 深度净化 polished_text：实体解码、全角数字归一、@/#/URL 剥离、emoji 剔除、空白折叠；全角标点保留。
- [x] 2.6 多模态平行清洗 polished_multimodal：text 段同款净化、媒体段原样保留、保序。
- [x] 2.7 隐私脱敏：手机号/QQ/≥7位数字打码（仅 polished 列）。
- [x] 2.9 text_changed 标记与 clean 子集视图（库视图）。
- [x] 2.10 标注表落库（cleaning_annotations：excluded/norm_key/dedup_group_id/is_duplicate/polished_text/polished_multimodal/text_changed/spam_suspect/spam_reasons_json/owner_segment + post_id 主键、cleaning_version、generated_at），只入库不做 CSV 导出。
- [x] 2.11 水军与广告识别：广告帖组合规则（联系方式模式×促销话术）标 excluded=advertising；库内聚合水军嫌疑（同作者重复/跨账号同 norm_key/新号爆发）标 spam_suspect=1 + spam_reasons_json，不自动排除；规则明细入字段契约文档。

## 3. 校验与验收

- [x] 3.1 单元测试覆盖每条 spec 场景；fixtures 用库内真实行抽样（含 226 条样本）。
- [x] 3.2 实测数字复算：对照旧锚点（剔除 24、重复 61、clean 9701、URL 22681、text_changed 667、废串 4、gibberish 1），漂移逐项解释。
- [x] 3.3 review_required 定级复算：226 条逐类计数与抽查结论一致（纯图/已删/无媒体）。
- [x] 3.4 只读边界验证：清洗前后 posts 表 9994 行 record_hash 不变。
- [x] 3.5 实测报告与证据文件（docs/evidence/），openspec validate --strict 通过。
- [ ] 3.6 Owner 审查实测报告并记录批准结论；交付分支与 PR，不自行合并。

## Workflow follow-up

- 本 Change 输入为 stock 库当前状态（含 legacy-4 重导成果）；若 9.6 之后采集侧再有数据变更，须在 3.2 复算前说明基线。
- 历史帖在线可访问性仅抽样标记，不做全量探测；全量探测是否值得属于清洗 Change 范围外的新决策，需另行 Owner 批准。
- B 阶段（抽取/向量索引）消费本 Change 的 clean 子集与 polished_multimodal；列名 polished_text 与 posts.clean_text 的语义区别须在交付文档中显著说明。
- [x] 2.12 产品别名映射：建 product_aliases 表（决策8四类来源），official/variant 机械生成，community 语料挖掘（同遍历统计），待确认不消费；映射只向上归一（细→粗），车系名/无配置语境短语不得映射到 spec 级（含配套测试用例）；与清洗同跑输出挖掘候选清单供人工确认。

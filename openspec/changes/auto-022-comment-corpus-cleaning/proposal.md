# auto-022-comment-corpus-cleaning

## Why

采集与存储（auto-021-data-ingestion）已完成：stock 库 9994 帖按新契约结构化入库（阅读/回帖数补齐、标签数组化、溯源快照完备）。清洗阶段（离线管线 A1）的旧契约与脚本已由合作方移交至 `02_cleaning/handover/`（spec：comment-corpus-cleaning_spec.md；脚本：clean_corpus.py、deep_clean.py），面向旧管线的 23 列 CSV 文件输入。

新架构下输入已变为 SQLite 库（8 表，结构化程度远超 CSV），旧契约中约半数需求已被采集层实现取代（数字整数化、作者信息结构化、时间解析、post_id 主键、有序分段 content_segments_json、基本文本规范化），其余为真实待建能力（去重、废串/纯符号标注、深度净化、隐私脱敏、车主分群、删除帖剔除、clean 子集视图、标注输出）。需要一次规范迁移：将旧 CSV 清洗契约映射到库架构，剔除已被取代项，落地为 02_cleaning 模块。

## What Changes

- 新建 `offline_analysis_pipeline/02_cleaning` 模块（Python，stdlib-only，对齐 01_ingestion 风格），输入为 stock 库，输出清洗标注与高置信子集。
- 迁移旧契约至库架构（映射见 design）：
  - **新增能力**：精确+归一近重复去重（norm_key/dedup_group_id/is_duplicate）、系统废串标注（excluded=system_junk）、纯符号 gibberish 标注、删除帖与空行剔除、深度文本净化（@提及/#话题#/URL 剥离、emoji 剔除、全角数字归一、HTML 实体解码）、多模态平行清洗（媒体 URL 原样保留）、隐私脱敏（手机号/QQ/≥7位数字打码）、text_changed 变更标记、clean 高置信子集视图。
  - **已被采集层取代（不重建）**：数字整数化、作者信息结构化、时间解析与相对时间反推、post_id 主键、有序分段保留、基本文本规范化（实体解码/空白折叠）。
  - **语义映射调整**：旧 spec 的 `text_content` 对应库中 `posts.body_text`；旧 `multimodal_content` 对应库中 `content_segments_json`（结构更强：含 locator）；旧"是否匹配正文"审核列对应库中 `source_snapshots.issues_json.legacy_body_match_status`。
- 226 条 review_required 处置（依据 2026-10-22 在线抽查结论，见 01_ingestion/docs/evidence/live-acceptance-20261021.md 附录）：存活纯图帖按图片帖规则保留；已删除帖默认排除出语义子集并保留库中标记；无媒体帖人工抽查定级。清洗层不做在线可访问性全量探测（仅抽样）。
- 输出形态：清洗标注写回 SQLite（标注表 cleaning_annotations，schema 版本化），**只入库、不做 CSV 导出**（Owner 2026-10-22 指示，design 决策2）；不修改 stock 业务表原值。另建 product_aliases 产品别名映射表（Owner 2026-10-22 新增，design 决策8，映射只向上归一）。

## Scope

**范围内**：02_cleaning 模块、旧契约迁移映射、去重/标注/净化/脱敏/子集视图、清洗标注的库内落位、与旧实测数字（9970→9701 等）的复核校验、实测报告与证据。**范围外追加（Owner 2026-10-22）**：用户/车主分群（属特征工程，归 B 阶段信息抽取）。

**范围外**：图片下载与图片本体（A4）、三元组抽取/向量索引（B 阶段）、报告与体验建模、agent 在线分析、采集层行为变更（auto-021 范围）、stock 业务表历史值的修改（清洗只新增标注，不改原值）。

## Capabilities

### Modified
- （无——comment-corpus-cleaning 此前未成为正式 spec，openspec/specs 为空）

### Added
- `corpus-cleaning`：语料清洗标注与高置信子集契约（去重、标注、净化、脱敏、分群、视图、输出）。

## Impact

- 代码：新增 `02_cleaning/`（src + tests + tools + docs），复用 01_ingestion 的 storage 读取（只读连接）与 basic 清洗函数。
- 数据：stock 库新增清洗标注表/列（schema 版本化迁移）；原业务表 9994 行不修改。
- 实测数字：旧 spec 记载 9994→9970（剔除删除帖3+空行21）→9701（clean 子集）基于同一 CSV 源，新架构下应可复算校验；输入差异（本次 review_required 标记、legacy-4 重导）可能造成个位数差异，须逐项解释。
- 协作：Owner 审阅 proposal/design/spec/tasks 并批准后实施；交付走独立分支与 PR，同 auto-021 流程。
- Owner：待补（实名）。批准状态：**APPROVED-TO-IMPLEMENT（Owner 2026-10-22 会话指示"先把22做完"批准实施；决策2 只入库、决策4 定级简化、决策7 水军广告识别、决策8 别名映射及向上归一约束均为 Owner 会话确认）。3.6 Owner 代码审查与验收仍待执行。**

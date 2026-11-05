# 旧 CSV 列 → 新库列映射（auto-022 任务 1.2）

旧契约（`02_cleaning/handover/specs/comment-corpus-cleaning_spec.md`）假设 23 列 CSV 输入；
新架构以 stock 库为唯一输入（决策1）。映射如下：

## 已被采集层取代（不重建）

| 旧 CSV 列 / 能力 | 新库落点 |
| --- | --- |
| `post_id`（自帖子链接派生） | `posts.post_id`（主键） |
| `title` / `source_url` | `posts.title` / `posts.source_url` |
| `text_content`（全文 text 段拼接） | `posts.body_text`（决策6：拼接已由采集层完成） |
| `multimodal_content`（有序分段 JSON） | `posts.content_segments_json`（更强：含 locator；段字段 `kind`/`value`） |
| `created_at`（发布时间解析） | `posts.published_at` + `time_precision`/`time_basis` |
| `views` / `replies`（中文单位剥整数） | `posts.view_count` / `posts.reply_count`（legacy-4 重导已整数化） |
| `image_count` / `images` / `video_ids` | 由 `content_segments_json` 派生（kind=image/video） |
| `tags` | `posts.tags_json`（数组化） |
| `author_*` 9 列（作者信息解析） | `posts.author_context_json`（7 字段）+ `users` 表 |
| `作者爱车` | `posts.author_context_json.declared_vehicle`（清洗不分群；B 阶段抽取侧使用） |
| 基本文本规范化（零宽/空白折叠） | `posts.clean_text`（但实测采集层未折叠空白，见 data-contract 基座口径） |
| `是否匹配正文`（审核列） | `source_snapshots.issues_json`（legacy_audit）；删除帖判定以正文标记文本为准（实测 3 条） |

## 清洗层新增（本 Change 产出，写 `cleaning_annotations`）

| 旧 spec 列 | 新列 | 说明 |
| --- | --- | --- |
| `norm_key` / `dedup_group_id` / `is_duplicate` | 同名 | 归一基座与去重参与范围见 data-contract |
| `clean_text`（深度净化） | `polished_text` | 决策3：避免与 `posts.clean_text` 混淆 |
| `clean_multimodal` | `polished_multimodal` | text 段同款净化，媒体段原样保留 |
| `excluded` | 同名 | 枚举扩展：post_deleted / empty_no_media / system_junk / gibberish / advertising |
| `non_chinese` / `is_long` / `quality_score` / `high_confidence` | 不再输出 | 旧管线簿记列；高置信语义由 `v_clean_subset` 视图承担 |
| `text_changed` | 同名 | 基座=归一基座（见 spec delta 与 data-contract） |
| —（新增） | `spam_suspect` / `spam_reasons_json` | 决策7 水军嫌疑（只标不排） |
| —（新增） | `cleaning_version` / `generated_at` | 版本化与可重跑 |

## 别名映射（新表 `product_aliases`）

无旧对应物；来源与约束见 design 决策8。official/variant 来自 `product_specs`
（spec_name/series_name/brand_name），community 来自语料挖掘，competitor 为人工种子。

## 校验锚点（决策5）

| 锚点 | 旧实测 | 新实测（2026-10-22） | 结论 |
| --- | --- | --- | --- |
| 删除帖 | 3 | 3 | 一致 |
| 空行（无媒体） | 21 | 21 | 一致 |
| 重复行 | 61 | 61 | 一致（dedup_groups 9704 亦同旧 9704 唯一键） |
| 废串 | 4 | 4 | 一致 |
| gibberish | 1 | 1 | 一致 |
| text_changed | 667 | 667 | 一致 |
| clean 子集 | 9701 | 9694 | -7 = 新增 advertising 剔除 7 条 |
| 多模态 URL 前后一致 | 22681=22681 | 23693=23693 | 前后一致不变量成立；绝对数口径差异见 evidence |

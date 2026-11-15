# 清洗输出字段契约（auto-022 任务 2.8/2.11 配套）

## cleaning_annotations（每帖一行，post_id 主键）

| 列 | 类型 | 契约 |
| --- | --- | --- |
| `post_id` | TEXT PK | 与 posts 一一对应（9994） |
| `cleaning_version` | TEXT | 版本标识；同版本重跑幂等（整表替换） |
| `generated_at` | TEXT | UTC ISO8601 |
| `excluded` | TEXT | '' / post_deleted / empty_no_media / system_junk / gibberish / advertising；判定优先级按此顺序 |
| `norm_key` | TEXT | 归一基座再 NFKC+小写+压空白；空文本为 ''（dedup_group_id=0） |
| `dedup_group_id` | INTEGER | 首条为组 id；空文本 0 |
| `is_duplicate` | INTEGER | 同组非首条 =1 |
| `polished_text` | TEXT | 深度净化文本；纯图帖为 '' |
| `polished_multimodal` | TEXT | 平行分段 JSON；媒体段 value 原样 |
| `text_changed` | INTEGER | polished_text ≠ 归一基座 |
| `spam_suspect` | INTEGER | 0/1；只标不排，不影响子集 |
| `spam_reasons_json` | TEXT | 命中规则明细（含 excluded_rule 命中依据），可解释 |

（无用户/车主分群列——Owner 2026-10-22 指示：分群属特征工程，归 B 阶段信息抽取。）

### 归一基座（norm_key 与 text_changed 共用）

基座 = `body_text` 去零宽字符（U+200B/200C/200D/FEFF）→ 折叠连续空白为单空格 → 去首尾空白。
口径与旧管线 `text_content` 规范化一致（决策5 锚点复算的前提）。`polished_text` 的净化输出
不受基座选择影响（净化链末端同样折叠空白）。

## 规则明细（实现于 `src/corpus_cleaning/`，常量见 `contracts.py`）

### excluded 判定

- **post_deleted**：body/基座/clean_text 任一含 `本楼已被删除`（实测 3）。Owner 指示不做疑似删除标注（决策4）。
- **empty_no_media**：基座空 且 无 image/video 段（实测 21）。纯图/纯视频帖保留（excluded=''）。
- **system_junk**：命中 `查看详情|我要申诉|加载中|点击展开|展开更多`（实测 4）。
- **gibberish**：去 emoji/空白后无汉字字母数字，且余量全部 ∈ `* • · . 。，、`（实测 1）；纯 emoji 不标。
- **advertising**：联系方式模式（手机号 / QQ号 / 微信类变体 / ≥7位数字）**×** 促销话术（低价|优惠|代购|转让|出售|车贷|贷款|月供|分期|返现|特惠|内部价|底价|秒杀|清仓 等）**组合**命中（实测 7）。外链堆叠（≥3 URL）仅为辅助信号，单独不构成。

### 水军嫌疑（spam_suspect，只标不排；阈值均为 contracts.py 可调参数）

- `r1_same_author_repeat`：同作者 ≥3 帖 norm_key 相同（实测命中 12 帖；抽查为同一账号
  反复发送相同长文，信号准确）。
- `r2_cross_author_key`：同一 norm_key 出现于 ≥2 个作者（协同模板；实测 15 帖）。
  **仅对未剔除行且归一键长度 ≥8 生效**——首轮实测 46 帖中混入"小米su7"（×9）、
  "不值"等超短常见语及废串/删除标记文本，Owner 抽查后加过滤（2026-10-22）。
- `r3_new_account_burst`：注册→发帖 ≤30 天 且 platform_post_count ≤5（实测 482 帖）。
  抽查结论：混有真实新车主（2024-03/04 发布高峰 159 帖与 SU7 上市潮吻合）与
  车商/推广号（如"置力名车广场"注册当天连发 VIN 帖），是"嫌疑"不是判定；
  下游只应作降权/复核信号。阈值收紧属 Owner 决策。
- 并集去重后 spam_suspect=1 共 508 帖（见 evidence）。

### 净化链（polish_text，顺序固定）

HTML 实体解码 → 全角数字归一（禁 NFKC 输出）→ 剥 URL → 剥 @提及 → 剥 #话题# →
手机号打码 `138****5678` → QQ 号打码 `QQ****` → ≥7 位数字打码 `****` → 剔 emoji → 折叠空白。
全角标点保留；emoji 不设独立列。polished_multimodal 的 text 段同款；媒体段 value 原样保留。

### 用户/车主分群（不在本模块）

Owner 2026-10-22 指示移出清洗范围：分群属特征工程，归 B 阶段信息抽取。
author_context_json.declared_vehicle / users.declared_vehicle（后者 0 填充）可作其输入。

## product_aliases（alias_norm 主键；Owner 2026-10-22 重构为显式规范链）

| 列 | 契约 |
| --- | --- |
| `alias_norm` | 归一键（norm_key）——语料写法的归一形式 |
| `alias_display` | 展示名（竞品为"品牌 车系"） |
| `alias_type` | official / variant / community / competitor |
| `source` | product_specs / rule_strip_year / rule_strip_config / rule_strip_brand / rule_series_combo / corpus_mining / manual_seed |
| `status` | confirmed（official/variant 自动） / pending（community/competitor，人工确认后才可消费） / rejected（人工拒绝，重跑保留） |
| `match_method` | exact（权威名/规则精确生成） / fuzzy（编辑距离 ≤2 的挖掘候选，归属未定） / seed（人工种子） |
| `canonical_brand_name` / `canonical_series_name` / `canonical_series_id` | 规范品牌/车系（名称+ID） |
| `canonical_spec_id` / `canonical_spec_name` | 仅 spec 级别名填写（官方全名或仅剥年款） |

**回溯语义（供 B 阶段 LLM 抽取）**：抽取得到的产品提及 → `norm_key(提及)` → 查
`product_aliases.alias_norm` → 只消费 `status='confirmed'` 行 → 得到规范链
（品牌/车系/配置）。pending 行不消费；fuzzy 候选的 canonical 为空（编辑距离匹配可能
指向其他车型如 M7/L7，归属由人工确认时填写）。

**解析视图**：`v_alias_resolved`（原始写法→规范品牌/车系/配置，中文列名，DB Browser 直接看）。

写策略：official/variant 永不删除（INSERT OR IGNORE）；community/competitor 仅整批替换
status=pending 行；人工 confirm/reject 永不被重跑覆盖。竞品行 id 类字段为 NULL
（库内无对应实体），规范名为纯文本。
候选过滤（Owner 抽查后加，2026-10-22）：候选须含数字/以汉字开头/长度≥4；与已知别名互为
包含的切词碎片（"买SU7""米SU7"）不算拼写变体；竞品种子优先于社区候选（"YU7"归
competitor）；模糊候选不预设归属。剥配置词元按长度降序（避免"长续航"误剥"超长续航"出
"超"字垃圾）。

## 视图

`v_clean_subset` = excluded='' AND is_duplicate=0 AND polished_text!=''，附 polished 列与
spam 标记。B 阶段消费本视图即"高置信子集"；注意 `polished_text`（深度净化）≠
`posts.clean_text`（采集层基本规范化），交付文档已显著区分。

## CSV 导出

无（Owner 2026-10-22 指示：只入库）。人读场景用 SQL / DB Browser。

## 下游消费指南（B 阶段）

### spam_suspect 弱降权信号的用法（只降权，不排除）

1. **抽取分层省预算**：先抽 `spam_suspect=0`（9486 帖），spam=1 的 508 帖降优先级或抽样抽。
2. **证据置信**：报告引用某帖作证据时，spam=1 的引用降排序权重（如 ×0.5）或在展示时标注
   "存疑帖（命中水军规则: <reasons>）"。
3. **统计口径**：舆情计数出两个口径——全量 vs `spam_suspect=0`，两者差异大说明该结论被
   重复/模板帖驱动，需人工复核。
4. **禁止**：不得仅凭 spam_suspect 把帖子从证据集中物理剔除（r3 对新车主论坛误报率高）。

### 产品提及回溯（别名映射）

```sql
-- LLM 抽取出提及 "su7max" → 规范链
SELECT canonical_brand_name, canonical_series_name, canonical_spec_name
FROM product_aliases
WHERE alias_norm = ? AND status = 'confirmed';   -- norm_key(提及)；只消费 confirmed
```
批量场景：把抽取产物中的提及归一后 LEFT JOIN 本表，未命中/仅 pending 的提及进"待确认
清单"积累人工处理，不阻塞抽取。

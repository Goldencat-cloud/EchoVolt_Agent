# auto-022 清洗实测报告（2026-10-22）

实施环境：Windows，`C:\Users\Lenovo\anaconda3\python.exe`（Python 3.13.9，stdlib-only 实现）。
输入基线：stock 库 `offline_analysis_pipeline/data/stock/db/ingestion.sqlite3`（9994 帖，
legacy-4 重导成果，review_required 226 = 正文全空）。

## 命令

```powershell
# 单元+集成测试（60 项，含真实库副本上的锚点复算与只读边界验证）
C:\Users\Lenovo\anaconda3\python.exe -m unittest discover -s offline_analysis_pipeline/02_cleaning/tests -p "test_*.py"
# dry-run 统计（不写库）
...\02_cleaning\tools\run_cleaning.py --db ...\data\stock\db\ingestion.sqlite3 --dry-run
# 正式落库（cleaning_annotations 9994 行 + product_aliases 84 唯一别名 + v_clean_subset 视图）
...\02_cleaning\tools\run_cleaning.py --db ...\data\stock\db\ingestion.sqlite3
```

## 锚点复算（决策5）

| 锚点 | 旧实测 | 新实测 | 漂移 | 解释 |
| --- | --- | --- | --- | --- |
| 删除帖 | 3 | 3 | 0 | 一致 |
| 空行（无媒体） | 21 | 21 | 0 | 一致 |
| 重复行 | 61 | 61 | 0 | 一致（dedup_groups=9704，与旧"9704 唯一键"一致） |
| 废串 | 4 | 4 | 0 | 一致 |
| gibberish | 1 | 1 | 0 | 一致 |
| text_changed | 667 | 667 | 0 | 一致（归一基座口径，修复过程中由 2706 校正至此，见"边界说明"） |
| clean 子集 | 9701 | 9694 | -7 | 恰为新增 advertising 剔除 7 条（旧管线无此规则） |
| 多模态 URL 前后一致 | 22681=22681 | 23693=23693 | 口径差 | 前后一致不变量成立；见下 |

**URL 绝对数口径差异**：旧锚点 22681 仅统计图片 URL（视频走独立 video_ids）；新统计为
content_segments 中 image+video 段总数 = 22661 图 + 1032 视频 = 23693。图片 -20 差额
（22681→22661，其中 9 条为 smiles 表情 gif 仍在段中）源于 legacy-3→legacy-4 重导的解析差异，
未逐条溯源，已记为待查项（不影响"清洗前后一致"不变量）。清洗核心不变量：**清洗前后
媒体段总数一致（23693=23693），媒体 URL 原样保留**。

## 226 条 review_required 定级复算（任务 3.3）

quality_state='review_required' 的 226 条全部为正文空帖：205 条含图片段（保留为图片帖，
polished_text 空、不标 excluded）、21 条无任何媒体（excluded=empty_no_media）。与 2026-10-21
在线抽查结论（存活纯图帖 + 已删帖混合）及 Owner 简化指示（决策4：不做疑似删除标注）一致。

## 水军嫌疑报告（Owner 要求；抽查后规则修正）

首轮实测 spam_suspect=538；Owner 抽查（2026-10-22，inspect_spam.py 输出）发现 r2 噪声：
"小米su7"（9 帖超短文本）、"不值""工业垃圾"等常见短句、废串/删除标记文本被计入协同模板。
修正：r1/r2 仅对未剔除行且归一键长度 ≥8 生效。修正后 spam_suspect=1 共 **508 帖**：

| 规则 | 命中帖数 | 抽查结论 |
| --- | --- | --- |
| r1_same_author_repeat（同作者≥3帖同文） | 12 | 准确：同一账号 2025-02 反复发送相同 SU7 性能长文 |
| r2_cross_author_key（跨账号同 norm_key） | 15 | 过滤后剩余为真实模板嫌疑（如 4 个账号同发"贴车衣"求推荐、2 账号同日同发"外观美到不行"模板文） |
| r3_new_account_burst（注册≤30天且发帖≤5） | 482 | 混合信号：含车商/推广号（"置力名车广场"注册当天连发 VIN 帖、车补口令推广帖）与真实新车主（2024-03/04 上市潮 159 帖）；属"嫌疑"非判定，下游仅作降权 |

r3 若需收紧（如 ≤7 天/≤2 帖）属 Owner 决策，参数在 contracts.py。

## 广告识别

excluded=advertising 共 **7 帖**（联系方式×促销话术组合命中），均保留库中、不入子集。
这 7 条即 clean 子集 -7 漂移的全部来源。

## 废串误删评估（Owner 问询）

system_junk 全量 4 帖的正文**均只有"查看详情 我要申诉"9 字**（正文加载失败占位符），无任何
实质内容被整帖排除；含废串词的其余 3 帖正文为"本楼已被删除 查看详情 我要申诉"，已按
post_deleted 优先处理。**当前语料零误删**。边界提示：若未来采到"正常正文+末尾废串"混合帖，
应把规则改为局部清洗，属新决策需 Owner 批准。这 4 帖的图片仍在其 content_segments 中，
多模态索引（auto-023）不受影响。

## r3 阈值敏感性（Owner 问询，决策：维持 30天/5帖）

阈值网格（总命中 / 其中 2024-03~04 上市潮帖）：

| | cnt≤1 | cnt≤2 | cnt≤3 | cnt≤5 |
|---|---|---|---|---|
| gap≤3 | 166/41 | 238/69 | 285/88 | 322/100 |
| gap≤7 | 176/45 | 257/77 | 309/97 | 354/111 |
| gap≤14 | 192/53 | 279/88 | 343/110 | 408/129 |
| gap≤30 | 235/74 | 332/112 | 405/136 | 482/159 |

结论：上市潮真新车主在任何阈值下都占约 1/3——r3 本质区分不了"上市期新车主"与"新号营销"，
收紧只是等比例砍掉两类。故维持 gap≤30/cnt≤5 定位为弱降权信号；车商兜底交给 advertising
内容规则与人工复核。

## 用户/车主分群（移出）

Owner 2026-10-22 指示：分群属特征工程，归 B 阶段信息抽取。cleaning_annotations 不含
owner_segment 列；首轮实测值（owner 799 / other 3627 / unknown 5568）仅存档于本报告 git 历史。

## 产品别名映射

- 84 个唯一别名落库：official（spec 全名/车系名/品牌名）+ variant（剥年款/剥配置/车系短名组合，含"su7max"等无空格形态）= confirmed；community 候选 50 条 + competitor 种子 10 条 = pending。
- 语料覆盖：12 个已知别名在语料中命中 4641 次。
- 向上归一约束经测试验证（spec 级别名仅官方全名/剥年款两类；community 一律 series 级）。

## 只读边界验证（任务 3.4）

集成测试在 stock 库**副本**上运行完整管线后，对比原库：posts 9994 行 post_id+record_hash
逐行一致；业务列抽查一致。写操作仅限 cleaning_annotations / product_aliases / v_clean_subset。

## 测试

60 项全部通过（unittest discover）。覆盖：净化链各规则、全角标点保留、脱敏三模式、
QQ 非号码不误伤、多模态 URL 保留、删除/空媒体/废串/gibberish/纯 emoji 豁免、
去重归一合并与空文本豁免、广告组合命中与非组合不误伤、水军三规则与缺字段跳过、
别名向上归一不变式、幂等重跑、人工 confirm/reject 不被覆盖、真实库基线/锚点/只读边界/确定性重跑。

## 边界说明（诚实记录）

1. text_changed 漂移修复过程：初次按"去首尾空白"字面口径实测 2706（+2039），定位为基座
   差异（旧锚点在阶段1规范化后的 text_content 上计算；body_text 保留原始空白，其中纯空白
   触发 2290）。修正为归一基座口径后 667=667，spec delta 已同步措辞。净化输出本身两口径一致。
2. URL -20 图片差额待溯源（legacy-3→4 解析差异），已记待查项。
3. 本 Change 的实施与测试均由 AI（Codex 角色）完成，**未经人类代码审查**（任务 3.6 待 Owner）。
4. 实测基于当前库状态；若 9.6 之后采集侧再有数据变更，3.2 复算需说明基线（见 tasks follow-up）。

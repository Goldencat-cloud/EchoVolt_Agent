# comment-corpus-cleaning Specification

## Purpose

将汽车之家小米 SU7 原始论坛评论数据清洗为一份干净、可追溯、可直接进入三元组抽取与向量索引的语料，作为离线管线 A1 的数据准备环节。

定义汽车评论语料的高置信清洗与质量标注契约：去重、噪声标注、文本净化、多模态平行清洗、隐私脱敏，并以 flag+keep 方式保留全部原文以满足可追溯。清洗产出两列对齐的净化文本（`clean_text` 正文 + `clean_multimodal` 多模态），不设独立 emoji 列。

## Requirements

### Requirement: 内容字段归一与保序
系统 SHALL 以解析后的 `全文` 文本作为权威文本内容字段 `text_content`，解析 `[["text","..."]]` 结构并将所有 `type=="text"` 片段拼接；`正文` 经验证为 `全文` 的严格子集且冗余，SHALL **不输出** `matched_snippet` 字段。

系统 SHALL 额外输出 `multimodal_content`：保留 `全文` JSON 的**有序分段序列**（含 `text`/`img`/`vid` 及其出现顺序），以 JSON 串存储（如 `[{"type":"text","v":"..."},{"type":"img","v":"url"},...]`），供下游还原"文字↔图片/视频"的对应关系，满足 B5 可追溯。

#### Scenario: 正常全文解析
- **WHEN** 某行 `全文` 为合法 JSON 数组且含文本片段
- **THEN** 该行 `text_content` 为非空拼接文本，`matched_snippet` 字段不出现在输出中

#### Scenario: 保序分段保留
- **WHEN** 某行 `全文` 含交错结构（如 `text,img,text,img`）
- **THEN** 该行 `multimodal_content` 按原顺序保留每个分段的 `type` 与内容，使下游可定位"某句文字后跟随的具体图片/视频"

#### Scenario: 全文无文本片段
- **WHEN** 某行 `全文` 解析为空或仅含图片/视频分段
- **THEN** 该行 `text_content` 为空字符串，`multimodal_content` 仍保留其媒体分段（纯媒体帖保留）

### Requirement: 数字字段提取整数
系统 SHALL 将 `浏览数`、`回帖数`、`列表图片数` 中的中文单位剥离并转为整数；缺失或无法解析时记为 0 或空，其中列表图片数缺失表示"无图"。

#### Scenario: 带单位数字
- **WHEN** `浏览数` 值为 "146 浏览"
- **THEN** 输出 `views` 为整数 146

#### Scenario: 列表图片数缺失
- **WHEN** `列表图片数` 为空
- **THEN** 输出 `image_count` 为空，且不被当作错误

### Requirement: JSON 结构化字段解析
系统 SHALL 解析 `图片链接`、`视频ID`、`作者信息` 三个 JSON 串：`图片链接` 转为真实图片 URL 列表并过滤 `smiles` 表情 gif；`视频ID` 转为 ID 列表；`作者信息` 解析为结构化作者字段。

#### Scenario: 过滤表情图片
- **WHEN** `图片链接` 仅含 `smiles` 表情 gif URL
- **THEN** 输出 `images` 为空列表（表情不作为图片资源保留）

#### Scenario: 作者信息解析
- **WHEN** `作者信息` 为合法 JSON
- **THEN** 输出 `author_nick`、`author_home`、`author_post_count`、`author_hot_post_count`、`author_reply_count`、`author_reg_date`、`author_location`、`author_car` 等结构化字段

### Requirement: 时间字段解析与相对时间处理
系统 SHALL 将 `发布时间`、`作者注册时间` 解析为 datetime；`帖子相对时间`（"N天前"）SHALL 按爬取日 2026-10-03 反推为绝对日期用于交叉校验，但 SHALL 以 `发布时间` 为权威时间，且不在输出中保留 `帖子相对时间` 原始列。

#### Scenario: 权威发布时间
- **WHEN** `发布时间` 可解析
- **THEN** 输出 `created_at` 为 datetime，且与 `帖子相对时间` 反推值误差在合理范围内

#### Scenario: 相对时间不输出
- **WHEN** 数据含 `帖子相对时间` 列
- **THEN** 清洗输出 CSV 不包含 `帖子相对时间` 原始列

### Requirement: 文本规范化
系统 SHALL 对 `text_content` 去除零宽字符（如 U+200B 等）、折叠多余空白与换行、并 strip 首尾空白；emoji 予以保留。

#### Scenario: 含零宽字符
- **WHEN** 原始文本含零宽字符或多余空白
- **THEN** 输出 `text_content` 已去除零宽字符并折叠空白，且不含首尾空白

### Requirement: 删除帖与空行剔除
系统 SHALL 剔除含"本楼已被删除"等删除标记的行，以及**既无文本也无任何媒体**（`text_content`、`multimodal_content`、`images`、`video_ids` 均为空）的空行。仅含图片/视频、无任何文字的**纯媒体帖 SHALL 保留**，其 `text_content` 留空。

#### Scenario: 删除帖剔除
- **WHEN** `全文` 或 `正文` 含 "本楼已被删除" 标记
- **THEN** 该行不进入输出语料

#### Scenario: 纯媒体帖保留
- **WHEN** 某行无任何文本片段但含图片/视频
- **THEN** 该行保留，`text_content` 为空字符串

#### Scenario: 空行剔除
- **WHEN** 某行既无文本也无任何媒体
- **THEN** 该行不进入输出语料；剔除总量实测 24 行（删除帖 3 + 空行 21，9994→9970）

### Requirement: 车主分群标记
系统 SHALL 为每行输出 `owner_segment`（车主/他车/未知，基于 `作者爱车`），SHALL **不输出** `quality_flags` 与 `content_type` 列。

#### Scenario: 车主分群
- **WHEN** `作者爱车` 含 "小米SU7"
- **THEN** 该行 `owner_segment` 为 `owner`

### Requirement: 冗余作者列合并
系统 SHALL 以解析后的 `作者信息` 结构化字段作为唯一作者数据来源，不在输出中保留与 `作者信息` 完全重复的 9 个独立作者列（作者昵称、作者帖子数等）。

#### Scenario: 作者列去重
- **WHEN** 输出 CSV 生成
- **THEN** 输出不包含与原 `作者信息` JSON 重复的独立作者列，仅保留解析后的结构化字段

### Requirement: 可追溯主键保留
系统 SHALL 从 `帖子链接` 派生 `post_id` 作为每行唯一主键并保留，确保下游 B5 证据回挂能定位到原文评论。

#### Scenario: 主键唯一
- **WHEN** 原始 9994 行均含唯一 `帖子链接`
- **THEN** 输出每行 `post_id` 唯一且非空，可回查原始 `帖子链接`

### Requirement: 清洗输出落位
系统 SHALL 将清洗结果输出为 CSV 至 `data/processed/`，文件名区别于原始同名 CSV，采用 `utf-8-sig` 编码，且不修改原始 `.xlsx` 与已存在的同名 `.csv`。

#### Scenario: 输出不覆盖原始
- **WHEN** 清洗管线运行
- **THEN** 原始 `汽车之家_小米SU7_论坛帖子数据.xlsx` 与已存在的同名 `.csv` 未被修改，仅新增一份清洗语料 CSV

### Requirement: 文本去重（精确 + 归一近重复）
系统 SHALL 对 `text_content` 做归一化（NFKC 全→半角、ASCII 转小写、连续空白压为单空格）生成 `norm_key`，并按 `norm_key` 分组；同组仅保留首条（`is_duplicate=False`），其余标 `is_duplicate=True` 并共享同一 `dedup_group_id`。`norm_key` 仅作去重键使用，SHALL NOT 用于输出文本的归一。

#### Scenario: 精确重复合并
- **WHEN** 两行 `text_content` 归一后字符串完全相同
- **THEN** 两行共享同一 `dedup_group_id`，且仅一行 `is_duplicate=False`

#### Scenario: 归一近重复合并
- **WHEN** 两行仅差大小写、全/半角或多余空白
- **THEN** 归一后键相同，被判为同组并去重（仅留首条）

#### Scenario: 空文本不参与去重
- **WHEN** 某行 `text_content` 为空
- **THEN** 该行不进入去重分组，且 `dedup_group_id` 为 0

#### Scenario: 实测去重量
- **WHEN** 对 9970 行语料执行去重
- **THEN** 实测重复行 61 行（9765 非空 / 9704 唯一键），空文本（纯图片帖）不参与

### Requirement: 系统废串标注
系统 SHALL 将命中正则 `查看详情|我要申诉|加载中|点击展开|展开更多` 的 `text_content` 标 `excluded=system_junk`，且不从语料中物理删除该行。

#### Scenario: 系统废串识别
- **WHEN** `text_content` 含上述任一废串
- **THEN** 该行 `excluded=system_junk`，且仍保留在原始表中（实测 4 行）

### Requirement: 纯符号 junk 标注
系统 SHALL 将仅由退化装饰符号（集合 `*` `#` `·` `.` `。` `，` `、` 等，不含任何汉字/字母/数字/表达性标点）组成的 `text_content`（如 `***`）标 `excluded=gibberish`；空文本与纯 emoji 评论不标 gibberish。

#### Scenario: 纯符号识别
- **WHEN** `text_content` 非空且全部字符为退化装饰符号
- **THEN** 该行 `excluded=gibberish`（实测 1 行）

### Requirement: 空文本即纯图片帖（不剔除）
系统 SHALL 将空 `text_content` 保留（不剔除），其 `clean_text` 为空、不进入 `high_confidence` 子集，但仍可通过 `post_id` 回挂 `images` / `multimodal_content`。

#### Scenario: 空文本保留
- **WHEN** `text_content` 为空
- **THEN** 该行保留，`excluded` 为空，`high_confidence=False`

#### Scenario: 多模态内容保留
- **WHEN** 空文本行携带 `images` 或 `multimodal_content` 媒体分段
- **THEN** 该行保留且可通过 `post_id` 回挂原文与图片

### Requirement: 文本净化（clean_text）
系统 SHALL 生成 `clean_text`：HTML 实体解码（`&amp;`/`&lt;`/`&#NNN;` 等）、仅全角数字 `０-９` 归一为半角（SHALL NOT 对输出文本使用 NFKC，避免将全角标点 `，！？：；` 误转为半角）、剥离 `@提及` / `#话题#` / `URL`、emoji 直接剔除（SHALL NOT 生成独立 `emoji` 列）、保留全角中文标点不动。

#### Scenario: 符号剥离
- **WHEN** `text_content` 含 `@user`、`#话题#` 或 `http(s)://...`
- **THEN** `clean_text` 中这些片段被移除，emoji 一并剔除且不单列

#### Scenario: 全角标点保留
- **WHEN** `text_content` 含全角标点（如 `，`）
- **THEN** `clean_text` 中该标点保持全角原样（实测含 `，` 行数清洗前后一致：7890 = 7890）

#### Scenario: HTML 实体解码
- **WHEN** `text_content` 含 HTML 实体（如 `&amp;`）
- **THEN** `clean_text` 中实体被解码为对应字符

#### Scenario: 全角数字归一
- **WHEN** `text_content` 含全角数字 `０-９`
- **THEN** `clean_text` 中该数字为半角 `0-9`（实测 2 行）

### Requirement: 多模态平行清洗（clean_multimodal）
系统 SHALL 生成 `clean_multimodal`：解析 `multimodal_content` JSON，仅对 `type=="text"` 的文本块应用与 `clean_text` 同款净化（HTML 实体解码、全角数字归一、剥离 @/#/emoji、手机号与长数字打码、空白折叠）；`type=="img"` 等媒体分段的 `v`（图片 URL）SHALL 原样保留、SHALL NOT 执行 URL 剥离。

#### Scenario: 文本块净化
- **WHEN** `multimodal_content` 含 `type=="text"` 分段
- **THEN** 该块 `v` 按 `clean_text` 同款规则净化后重写回 JSON

#### Scenario: 图片 URL 保留
- **WHEN** `multimodal_content` 含 `type=="img"` 分段
- **THEN** 其 URL 原样保留（实测清洗前后 URL 总数一致：22681 = 22681）

### Requirement: 隐私脱敏（clean_text 打码）
系统 SHALL 在 `clean_text` 与 `clean_multimodal` 文本块中对手机号（`1[3-9]\d{9}`）、显式 QQ 号（`QQ` + 5-11 位数字）与 ≥7 位连续数字串打码；原始 `text_content` 保留不脱敏以满足可追溯。

#### Scenario: 手机号打码
- **WHEN** `clean_text` 含手机号
- **THEN** 该号被替换为 `138****5678` 形式，原始列不变（实测 1 行）

#### Scenario: QQ 号打码
- **WHEN** `clean_text` 含 `QQ` 后接 5-11 位数字的显式 QQ 号
- **THEN** 该号被替换为 `QQ****`（实测 0 命中；`QQ音乐`/`奇瑞QQ3`/`qq弹弹` 等非 QQ 号场景不受影响，规则保留作保险）

#### Scenario: 长数字串打码
- **WHEN** `clean_text` 含 ≥7 位连续数字（微信号/QQ 等数字 ID）
- **THEN** 该串被替换为 `****`，原始列不变

### Requirement: 清洗变更标记（text_changed）
系统 SHALL 输出 `text_changed` 布尔标记，标识 `clean_text` 与原文（去首尾空白后）不一致的行，供快速定位被净化过的记录。

#### Scenario: 变更行标记
- **WHEN** `clean_text` 与去首尾空白后的 `text_content` 不同
- **THEN** 该行 `text_changed=True`（实测 667 行）

### Requirement: clean 子集视图（不物理删行）
系统 SHALL 派生 `clean` 高置信子集 = 排除 `excluded` 非空、`is_duplicate=True` 与 `clean_text` 为空的行；子集仅含原始 23 列 + `clean_text` + `clean_multimodal`，不含簿记/标注列（`norm_key`/`dedup_group_id`/`is_duplicate`/`excluded`/`non_chinese`/`is_long`/`quality_score`/`high_confidence`/`text_changed`，这些仅保留在全量标注文件中）；原始 9970 行物理保留以满足 B5 可追溯。

#### Scenario: clean 子集过滤
- **WHEN** 查询 `clean` 子集
- **THEN** 结果不含 `excluded` 非空行、不含 `is_duplicate=True` 行、不含空 `clean_text` 行（实测 9701 行 = 9970 − 61 重复 − 5 废串/乱码 − 203 空文本等重叠后）

#### Scenario: 原文可追溯
- **WHEN** 追溯 `clean` 子集中的任意行
- **THEN** 可通过 `post_id` 回挂到原始 `text_content` 与多模态内容

### Requirement: 标注列输出契约
系统 SHALL 将清洗结果写回 `data/processed/`，全量文件在原始 23 列基础上追加 `norm_key`、`dedup_group_id`、`is_duplicate`、`clean_text`、`clean_multimodal`、`excluded`、`non_chinese`、`is_long`、`quality_score`、`high_confidence`、`text_changed`，且 `post_id` 与原表一一对应；SHALL NOT 输出独立 `emoji` 列。

#### Scenario: 输出列完整
- **WHEN** 清洗完成
- **THEN** 输出文件含上述全部标注列，行数与原始表一致（9970）

#### Scenario: post_id 对齐
- **WHEN** 比对输出与原表
- **THEN** 每行 `post_id` 与原表相同，无新增或丢失行

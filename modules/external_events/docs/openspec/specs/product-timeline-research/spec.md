# Spec Delta

## Purpose

提供对指定【品牌+产品】的可信外部深度调研能力：以 MCP 工具形式产出按时间排序、带来源可信度分级的事件时间线，作为时间趋势分析的外部事件数据源，与本地口碑语料的 `created_at` 时间轴对齐。

## ADDED Requirements

### Requirement: 复合调研工具输出事件集
系统 SHALL 通过 MCP 暴露复合工具 `product_timeline_research(brand, product, aspects?, time_from?, time_to?, domain_hint?)`：输入品牌、产品名、可选的研究主题子集（`product`/`competitor`/`policy`/`tech`/`public`，缺省全部 5 类）与可选领域提示，内部完成检索、价值过滤、**事件聚合**与**中立陈述生成**。完整事件集 SHALL **只写入落盘文件**；工具返回值 SHALL 为**简要结果摘要**（status、事件数、落盘路径），完整事件列表 MUST NOT 作为工具返回值直接进入调用方上下文。工具 MUST 具备跨领域泛用性：查询模板、分级与聚合逻辑 SHALL NOT 预设特定行业。

落盘文件中每个事件（聚合后）MUST 包含：`event_id`、`event_date`、`date_precision`、`event_type`（按事件主语：product/competitor/policy/tech/public_opinion/other）、`subtype`（开放细类）、`relevance`（core/context）、`title`（归一标题）、`summary`（**中立陈述**）、`media_coverage`（媒体覆盖面：`source_count` 独立来源域名数、`max_tier`、`level` high/medium/low——仅度量报道数量，MUST NOT 被解读为真实影响力，媒体覆盖可能含投放）、`authority`（事件权威分 0-100，见来源置信度制度）、`sources`（该事件的原始报道列表，每条含 source_domain/source_tier/**confidence**/url/published_date/title；LLM 逐条去噪判定的无关条目 MUST NOT 出现在其中）。

#### Scenario: 正常调研返回摘要
- **WHEN** 以合法的 `brand` 与 `product` 调用工具，且检索返回可用结果
- **THEN** 返回值为包含 `status`、事件数与落盘文件路径的摘要；完整事件集仅存在于落盘文件中，按 `event_date` 升序且字段完整，同一事件的多个报道已聚合为单条事件

#### Scenario: 跨领域输入
- **WHEN** 输入非汽车领域的品牌与产品（如手机、家电）
- **THEN** 工具 SHALL 正常产出事件集，SHALL NOT 因领域词表缺失而失效

#### Scenario: 检索无结果
- **WHEN** 多路检索均未命中可信来源
- **THEN** 返回空事件列表并附带检索状态说明，SHALL NOT 编造或以模型推测填充事件

#### Scenario: 外部检索服务失败
- **WHEN** 火山引擎 请求超时或返回错误
- **THEN** 全部查询失败时工具返回search_error，部分失败时返回partial；落盘query_stats保留失败原因，SHALL NOT 把检索失败伪装为无结果的成功响应

### Requirement: 综述种子检索
系统 SHALL 在事件检索之外先执行**综述种子检索**：以"大事记/时间线/盘点/回顾"类通用查询模板获取媒体编辑已聚合的高密度事件素材，其结果与事件切片检索结果共同进入候选集。该机制 SHALL 领域无关（任何领域均存在综述类内容）。

#### Scenario: 综述结果进入候选集
- **WHEN** 综述种子查询命中"XX产品大事记"类文章
- **THEN** 其内容作为候选参与后续聚合，`meta.query_stats` 中以 `overview` 主题标注

### Requirement: 启发式可信度分级
系统 SHALL 以**启发式**（非行业词表）对来源域名分级：`T1` = 政府监管域名（`.gov`/`.gov.cn` 等公共后缀，可配置）∪ 调用方显式提供的官方域名 ∪ 自动学习到的品牌官方域名；`T2` = 通用权威媒体清单（领域无关的综合媒体，可配置）；`T3` = 其余来源。品牌与产品关键词 SHALL 从输入参数派生，SHALL NOT 依赖行业专属词表。

#### Scenario: 政府域名自动 T1
- **WHEN** 某来源域名为 `samr.gov.cn` 等政府后缀
- **THEN** 该来源 `source_tier` 为 `T1`，SHALL NOT 依赖人工维护的行业清单

#### Scenario: 官方域名可显式指定
- **WHEN** 调用方传入官方域名列表（如品牌官网）
- **THEN** 命中域名的来源 `source_tier` 为 `T1`

#### Scenario: 未收录域名降权标记
- **WHEN** 某来源域名未命中 T1/T2
- **THEN** `source_tier` 为 `T3`，事件仍保留

### Requirement: 事件日期归一与去重
系统 SHALL 将事件日期归一为 `YYYY-MM-DD` 格式并保留原始精度（`date_precision`：day/month/year/unknown）；无法确定日期的事件 MUST 保留且 `event_date` 置空、以 `date_missing` 标记。系统 SHALL 依据 URL 对事件去重，同一 URL MUST 在时间线中只出现一次。

#### Scenario: 同一 URL 多次命中
- **WHEN** 多路检索命中同一 URL 的事件
- **THEN** 时间线中该事件仅保留一条（保留信息最完整的版本）

#### Scenario: 无日期事件
- **WHEN** 某来源结果不含可解析的发布日期
- **THEN** 该事件保留，`event_date` 为空并带 `date_missing` 标记，不阻塞其余事件输出

#### Scenario: 月级精度保留
- **WHEN** 来源仅给出"2025年11月"级别的日期
- **THEN** 该事件 `event_date` 归一为 `2025-11-01` 且 `date_precision` 为 `month`，SHALL NOT 被误标为日期缺失

### Requirement: 数据时间窗约束
系统 SHALL 支持通过 `time_from` / `time_to` 参数限定调研时间窗：检索 SHALL 在窗口内分年切片执行（保证窗口早期事件可被召回），窗口外的事件 MUST NOT 进入输出。未传时间参数时系统 SHALL 不做窗口过滤，并在 `meta` 中显式标注无窗口。

#### Scenario: 显式时间窗生效
- **WHEN** 调用时传入 `time_from=2024-03-28`、`time_to=2026-10-03`
- **THEN** 返回事件的事件日期均在窗口内，且检索按窗口内年份切片发起（`meta.query_stats` 可见分片查询）

#### Scenario: 未传时间参数
- **WHEN** 调用未传 `time_from` / `time_to`
- **THEN** 结果 `meta.time_window` 为空标记，行为与全时间检索一致，SHALL NOT 报错

### Requirement: 价值过滤与相关性标记
系统 SHALL 以规则漏斗对检索结果做价值过滤：命中营销/软文域名黑名单的条目 MUST NOT 进入输出；`product` 主题的检索结果 SHALL 执行严格离题判定（标题与摘要均不含品牌/产品词即丢弃），其余主题宽进（由聚合阶段的 LLM 判定丢弃）。品牌/产品词 SHALL 从输入参数派生。

#### Scenario: 噪声丢弃
- **WHEN** 某条结果命中黑名单域名或严格离题判定
- **THEN** 该条不出现在事件集中，且过滤情况反映在落盘文件 `meta.filter_stats` 中

#### Scenario: 宽进主题由聚合阶段裁决
- **WHEN** `competitor`/`policy`/`tech`/`public` 主题的候选与品牌无关
- **THEN** 由中立陈述生成阶段标记丢弃并计入 `meta.filter_stats`

### Requirement: 事件聚合与媒体覆盖面
系统 SHALL 将描述同一事件的多个报道聚合为**单条事件**：聚合 SHALL 采用**确定性算法**（文本向量化 + 日期邻近约束聚类，阈值可配置），SHALL NOT 依赖 LLM 做分组决策。聚合后事件 SHALL 携带 `media_coverage`（独立来源域名数 `source_count`、最高来源等级 `max_tier`、按规则映射的 `level`：独立来源 ≥10 为 high、3-9 为 medium、1-2 为 low）。`media_coverage` 仅度量媒体覆盖面，系统与文档 SHALL NOT 将其表述为真实影响力（真实影响力由分析侧的评论-事件语义关联度量，见 resonance 分析脚本）。

#### Scenario: 同事件多来源聚合
- **WHEN** 多条报道日期邻近且文本语义高度相似（同讲一件事）
- **THEN** 聚合为一条事件，`sources` 保留相关原始报道，`media_coverage.source_count` 为独立域名数

#### Scenario: 相似但不同事件不误合并
- **WHEN** 两条报道文本相似但日期超出邻近窗口或语义相似度低于阈值
- **THEN** 保持为独立事件

#### Scenario: 聚合确定性
- **WHEN** 相同的候选输入重复聚合
- **THEN** 产出完全相同的事件分组（SHALL NOT 依赖 LLM 或随机性）

### Requirement: 中立陈述生成与条级去噪
系统 SHALL 在归整每个聚合事件时由 LLM 完成**成员级去噪**：对簇内每条来源报道逐条判定去留（`member_verdicts`，忽略理由 ≤8 字可审计），无关条目（与事件无关、盘点点名、旧闻翻新、生态周边、软文凑数）MUST NOT 进入事件的 `sources` 与 `summary` 依据。`summary` SHALL 为**客观、陈述类的中立陈述**：仅使用保留成员的来源事实（不评价、不推测、不扩写）；LLM 输出 SHALL 经过校验（JSON 合法、摘要非空且长度受限），校验失败或 LLM 不可用时 SHALL **回退**为最优保留来源的原始表述，SHALL NOT 编造。`event_type`/`subtype`/`relevance` SHALL 由该阶段顺带输出（替代领域词表判断）。整簇均无效时 SHALL 丢弃该簇并计入 `meta.filter_stats`。

#### Scenario: 簇内条级去噪
- **WHEN** 某簇内混入与事件无关的条目（如盘点点名、旧闻翻新）
- **THEN** 该条目被逐条忽略且不计入事件 `sources`，其余条目照常聚合成事件，忽略数计入 `meta.filter_stats.member_ignored`

#### Scenario: 中立陈述生成
- **WHEN** 某聚合事件包含多条来源事实
- **THEN** 其 `summary` 为基于多来源交叉的客观陈述，且该事件保留 `sources` 供溯源

#### Scenario: LLM 不可用回退
- **WHEN** LLM 调用失败或输出不合法
- **THEN** 该事件回退使用最优保留来源原始标题与摘要，`meta` 中记录回退数量，SHALL NOT 阻塞其余事件输出

### Requirement: 来源置信度打分与事件权威门槛
系统 SHALL 为每条来源计算**置信度分（0-100）**：基础分按可信度分级（T1/T2/T3 可配置），UGC 自媒体平台（可配置清单）重罚，官方域名与可溯源日期加成。每个事件 SHALL 计算**权威分**（最高来源置信度 + 独立来源印证加成，上限 100）；权威分低于门槛（默认 50，可配置）的事件 MUST NOT 进入事件集（不照单全收），并计入 `meta.filter_stats.low_authority_dropped`。

#### Scenario: 置信度打分
- **WHEN** 某来源为政府域名（T1）且有可溯源日期
- **THEN** 其置信度接近满分；UGC 平台来源即使挂靠权威主域也被重罚

#### Scenario: 低权威事件拦截
- **WHEN** 某候选事件仅由低置信来源（如单一 UGC 自媒体）支撑
- **THEN** 该事件不进入事件集，拦截数反映在 `meta.filter_stats.low_authority_dropped`

#### Scenario: 多来源印证提升权威分
- **WHEN** 事件由多个独立域名共同支撑
- **THEN** 其权威分获得印证加成，高独立来源数事件的权威分显著高于单来源事件
### Requirement: 密钥与端点配置化
系统 SHALL 从环境变量读取 火山引擎 访问配置（key 与 API 端点地址）；API 端点地址 MUST 可配置以支持代理/镜像部署。中立陈述生成所用 LLM 端点（key/模型/地址）SHALL 同样从环境变量读取；LLM 配置缺失或不可用时系统 SHALL 以回退模式降级运行（SHALL NOT 崩溃）。`VOLCENGINE_SEARCH_API_KEY` 缺失时系统 SHALL 返回明确配置错误，SHALL NOT 崩溃或进入无凭据重试。

#### Scenario: LLM 降级模式
- **WHEN** 环境中未配置 LLM 端点或 LLM 调用全部失败
- **THEN** 工具仍产出事件集（事件采用回退表述），`meta` 显式标注 LLM 未生效

#### Scenario: 端点可配置
- **WHEN** 环境变量指定了自定义 火山引擎 API 端点地址
- **THEN** 所有检索请求发往该自定义端点而非默认官方地址

#### Scenario: 缺失 API Key
- **WHEN** 环境中未配置 `VOLCENGINE_SEARCH_API_KEY` 时调用工具
- **THEN** 返回明确的"配置缺失"错误信息，指明缺失的环境变量名

### Requirement: 调研产物落盘
系统 SHALL 将每次调研的完整结果写入 `outputs/research/<brand>_<product>_timeline.json`，内容 MUST 包含 `schema_version`、生成时间、检索元数据（时间窗与查询统计）与事件列表，且为合法 JSON。

#### Scenario: 调用后产物存在
- **WHEN** 一次调研成功完成
- **THEN** 对应 JSON 文件存在于 `outputs/research/`，可被解析且含事件列表与生成时间

### Requirement: MCP 服务形态
系统 SHALL 以 MCP server 形式提供工具：默认支持经 stdio 被 MCP 客户端拉起，客户端连接后 `tools/list` MUST 包含 `product_timeline_research`；系统 SHALL 支持以启动参数切换为 HTTP 服务模式，且两种模式下工具行为一致。

#### Scenario: stdio 拉起并列出工具
- **WHEN** MCP 客户端以 stdio 方式启动该 server 并请求工具列表
- **THEN** 返回的列表包含 `product_timeline_research`

#### Scenario: HTTP 模式行为一致
- **WHEN** server 以 HTTP 模式启动且客户端经 HTTP 调用同一工具
- **THEN** 输入输出行为与 stdio 模式一致

### Requirement: 火山引擎搜索归一化
系统 SHALL 使用API Key REST接口，映射Query/Count/Filter.Sites/TimeRange。Content缺失时回退Snippet；Summary SHALL NOT 作为来源原文。RankScore/AuthInfoLevel SHALL NOT 替代项目来源评分。

#### Scenario: ISO发布时间
- **WHEN** PublishTime为2025-05-30T19:35:24+08:00
- **THEN** published_date为2025-05-30、precision为day，保留原时间，不截成月初

#### Scenario: 请求限速与失败
- **WHEN** 并发查询发往同一客户端
- **THEN** 请求按配置间隔启动；全部失败标记search_error，不能标记empty

### Requirement: 本地网页调研入口
系统 SHALL 在本机网页提供调研输入、后台任务状态、事件来源查看与JSON/TXT下载，调用已有事件聚合流程。任务 SHALL 独立保存，服务重启后未完成记录 SHALL 标记中断；SHALL NOT 自动重复运行。网页 SHALL 仅绑定127.0.0.1，配置展示 SHALL NOT 返回凭据。

#### Scenario: 网页完整调研
- **WHEN** 用户提交合法品牌、产品、主题和时间窗
- **THEN** 后台任务开始，页面显示阶段与查询完成数，完成后提供事件与来源、JSON/TXT下载；未配置模型时显示原句回退

#### Scenario: 重复或跨源请求
- **WHEN** 已有网页任务运行，或请求来自其他Origin
- **THEN** 重复任务返回409，跨源请求返回403，不新建调研

### Requirement: Windows一键部署
系统 SHALL 提供deploy.cmd，自动建立独立venv、安装固定版本依赖、保留或创建.env、启动网页与MCP并验证协议。SHALL NOT 输出或提交凭据，SHALL NOT 默认运行付费搜索。已有本工具实例可复用，其他进程占用端口时明确失败。

#### Scenario: 干净目录首次运行
- **WHEN** 用户已安装Python3.11+且在干净目录运行deploy.cmd
- **THEN** 创建venv、安装依赖、启动两个本地服务，健康检查通过后打开网页

#### Scenario: 重复部署
- **WHEN** 服务已启动、配置与历史已存在且依赖hash未变化
- **THEN** 复用服务并保留配置和历史，不重复安装依赖

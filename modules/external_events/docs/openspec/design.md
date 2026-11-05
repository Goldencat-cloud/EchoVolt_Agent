# Design

## Context

deepagents 0.7.21 已装入当前 Anaconda base 环境（未隔离）；`backend/` 现有 FastAPI 骨架与清洗脚本，`/api/ask` 为空壳。前项目 `deep_agents_action` 的 `.env` 含可复用配置：`TAVILY_API_KEY`/`TAVILY_API_URL`（自定义端点）、`OPENAI_API_KEY`/`OPENAI_BASE_URL`、`AGENT_MODEL`、`LANGSMITH_*`。当前环境**缺** `mcp`、`langchain-mcp-adapters`、`langchain-openai`、`python-dotenv`。动机见 proposal.md - Why。

## Goals / Non-Goals

**Goals:**
- 一个可独立进程运行的 MCP server，暴露复合工具 `product_timeline_research`，输出可信分级的时间线 JSON。
- 端点/key 全部环境变量化，支持自定义火山引擎 API 端点（代理/镜像）。
- 产物落盘 `outputs/research/`，为时间趋势分析提供可直接消费的数据文件。
- 开发环境与 Anaconda base 解耦（项目 venv）。

**Non-Goals:**
- 不做 Docker 镜像与编排（另行 deployment change）。
- 不接 `/api/ask`，不实现 B1-B6 循环。
- 不做多产品批量队列、不做搜索引擎抽象层。
- 不打包 Agent Skill（见 `docs/ideas.md` Idea-1）；核心逻辑保持框架无关、CLI 可调，作为将来双壳（MCP/Skill）共用的前提。

## Decisions

### ADR-1: MCP SDK = 官方 `mcp` 包（FastMCP） — 已定
FastMCP 原生支持 stdio 与 streamable-http 双传输，启动参数切换即可满足"默认 stdio、保留 HTTP"的 spec 要求。备选：Tavily 官方 MCP server（ credibility 分级与多路编排逻辑无法内置，工具层职责外泄）、不用 MCP 直接写 langchain tool（违背本次"MCP 壳子"的复用诉求）。

### ADR-2: 火山引擎调用 = httpx 直调 REST（2026-10-11 替换）

POST VOLCENGINE_SEARCH_API_URL（默认官方 API Key 地址），Bearer 鉴权。Query、SearchType=web、Count、Filter.Sites、TimeRange 使用供应商字段；不模拟不存在的 topic=news。归一化 Title/Url/Content（回退Snippet）/PublishTime，忽略模型Summary。RankScore和AuthInfoLevel仅审计，不改变原来源评分。官方接口参考：https://www.volcengine.com/docs/85508/1650263 。

每调研共享客户端锁，默认0.65秒请求启动间隔，无自动失败重试；缺key或401/403快速配置失败，其他错误记录单查询失败。全部失败search_error，部分失败partial。完整ISO日期优先解析，避免截成月初。保留原发布时间；时间线日期仍是报道日期代理，不保证实际事件日期。来源新增可选审计字段，现有schema_version=3与字段含义保持。

### ADR-3: 研究方向与内部编排（代码固定，不靠 prompt） — 已定（v2 修订：跨域泛用）
方向采用"**先铺全量事件轴（主），异动窗口补查（辅）**"。单次调用内部执行两轮检索：①**综述种子**（"{bp} 大事记/时间线/盘点/回顾"——任何领域都有编辑聚合好的综述，密度最高的通用事件源）；②**通用事件切片**（5 研究主题 × 领域无关模板：发布上市/价格/更新升级/召回质量/事故投诉/舆情争议/竞品对比/政策监管/技术动向 × 窗口内按年切片）→ 并发检索 → 规则漏斗（黑名单 + `product` 主题严格离题判定，其余宽进）→ URL 去重 → 日期归一 → **确定性聚类**（ADR-9）→ **LLM 忠实改写与分类**（ADR-10）→ 影响力规则打分 → 按日期升序输出。**跨域泛用性约束**：查询模板、分级、聚合均不预设行业；品牌/产品词从输入参数派生。

### ADR-4: 分级与过滤 = 启发式 + 极小通用规则文件 — 已定（v2 修订）
- `T1`：政府域名后缀（`gov.cn`/`gov`，可配置）∪ 调用方显式传入的官方域名 ∪ 自动学习（结果域名含产品 ASCII token 时升 T1）；
- `T2`：通用权威综合媒体清单（新浪/界面/财联社/汽车之家等，跨行业综合媒体而非行业词表，可配置）；
- `T3`：其余；
- 黑名单：极小通用集（内容农场/软文站）。
行业专属的官方直采（如汽车召回页、乘联会销量）**不属于工具本体**，作为可选 domain adapter 记录于 `docs/ideas.md`。

### ADR-5: 事件集 schema（v3） — 已定
```json
{
  "schema_version": 3,
  "meta": {"brand", "product", "domain_hint", "generated_at", "time_window",
            "status": "ok|partial|empty|search_error", "llm_used": true|false,
            "query_stats": [{"query", "aspect", "hits", "ok"}],
            "filter_stats": {"noise_dropped", "out_of_window", "duplicate_url",
                              "member_ignored", "llm_ignored", "fallback",
                              "low_authority_dropped"}},
  "events": [{
    "event_id", "event_date", "date_precision", "date_missing",
    "event_type": "product|competitor|policy|tech|public_opinion|other",
    "subtype": "开放细类（LLM 判定，回退时用通用关键词映射）",
    "relevance": "core|context",
    "title": "归一标题", "summary": "中立陈述（LLM 忠实拼接，回退=最优来源原句）",
    "media_coverage": {"source_count": 14, "max_tier": "T2", "level": "high|medium|low"},
    "authority": 0-100,
    "sources": [{"source_domain", "source_tier", "confidence", "url", "published_date", "title"}]
  }]
}
```
事件 = 聚合 + 条级去噪后的簇；仅保留成员进入 `sources[]` 可溯源；`media_coverage` 仅度量媒体覆盖面（降级依据见 ADR-11）；`authority` 为事件权威分；schema_version 支撑演进。

### ADR-9: 事件聚合 = 确定性 embedding 约束聚类 — 已定
候选文本（标题+片段前 200 字）向量化 → **单遍聚类**：按日期排序，与既有簇代表比较，"日期邻近（±3 天，可配）AND 余弦相似度 ≥ 阈值（可配）"才合并。**不用 LLM 做分组**（业界实践与 Qwen3-Embedding 新闻去重案例一致：分组要确定、可复现、可调参）。Embedding 实现：优先 OpenAI 兼容 `/embeddings` 端点（`EMBEDDING_MODEL` 配置，如代理支持）；缺省回退为**本地字符 n-gram TF 余弦**（确定性、零依赖、对共享实体词的同事件报道足够有效）。日期缺失的候选拍按"高阈值全局匹配"处理，否则自成一簇。

### ADR-10: 归整 = LLM 条级去噪 + 忠实拼接 + 校验回退 — 已定
每个簇一次批量 LLM 调用（DeepSeek 兼容端点，temperature 0），输出 JSON：`{member_verdicts: [{id, ignore, note}], ignore, title, summary, event_type, subtype, relevance}`。**条级去噪**：簇内每条成员独立判定去留（噪音五类：无关/盘点点名/旧闻翻新/生态周边/软文，note ≤8 字可审计），无关成员不进入事件 `sources` 与 `summary` 依据，仅整簇无效才丢弃（`llm_ignored`）；prompt 约束：**仅使用保留成员的来源事实，不评价、不推测**，来源矛盾时以更权威、更新日期者为准。校验：JSON 合法、摘要非空 ≤150 字；失败或 LLM 不可用 → 回退最优保留来源原句 + 通用关键词映射 subtype（`meta.llm_used=false`、`fallback` 计数）。`media_coverage` 纯规则：独立域名数 ≥10 high / 3-9 medium / 1-2 low。

### ADR-11: 权威性核查制度与 media_coverage 降级 — 已定（防御性设计；实证依据由「评估与优化方案」重建，结论回流前视为待检验）

制度内容（保留，已实现于 task 2.9/2.10）：
a) `influence` 降级改名 `media_coverage`，仅度量媒体覆盖面，不作为真实影响力；
b) 来源置信度打分（分级基础分 - UGC 重罚 + 官方/日期加成，见 `rules.confidence`）；
c) 事件权威分门槛 50，低权威事件不进事件集（`low_authority_dropped`）；
d) LLM 归整时逐条去噪（ADR-10）。

> 修订说明（v4）：初版曾引用一组实证评估（伪事件对照 0.92x/0.89x、Top15 波峰 15/15、
> 共鸣差 +15pp 等）作为制度依据。经复核：该评估脚本未入库不可复现；波峰对齐缺随机日期
> 对照（当前事件密度下 ±7 天窗口几乎覆盖全部日历，15/15 可能为平凡真）；resonance 存在
> 空窗口虚高缺陷且 LLM 判定员未校准。上述证据整体撤回。制度决策保留，依据改为防御性
> 设计原则（未经证实的影响力声称不进 schema、UGC 来源保守降权）；真实效力由评估方案
> 重新检验，结论回流后再决定制度去留与参数。

> **回流结论（v5，2026-10-06，依据 `outputs/eval/` 评估报告）**：
> ①**价值层**：伪事件对照（纪元内基线，task 4.3）显示事件对评论量无显著放大（1.04x vs 1.00x，
> p=0.303）——"事件预测评论量"失灵被复现，制度 a)-d) 维持并被强化验证；波峰对齐真实命中率
> 66.7% vs 纪元内随机基线 62.3%，"事件解释波峰"判定为**事件密度的平凡产物，不成立**，
> 相关表述已从交付材料移除；resonance（修复+校准后）是唯一保留的影响力度量：17 个高覆盖
> 事件分布中位 +10pp、四分位 [0, 28.3]、64.7% 为正，判定员校准一致率 100%（50 条交叉标注 +
> 20% 人工复核确认）。
> ②**工具层**（41 金标准对照）：关键事件召回 73.3%（上市 5/5、监管召回 3/3 全中、事故舆情 3/5），
> 整体召回 34.1%（漏失集中于官方战报类，可解释）；精确率 81.2%（0 捏造，2 重复、9 软性聚合）；
> **聚类纯度 68.6% 为最大短板**（泛文本/垃圾页污染）；摘要忠实率抽检 15/15 无编造，溯源链可用。
> ③**优化立项**：P0 聚类来源清洗、P1 跨月重复合并、P2 补司法/资质查询模板与审计持久化，
> 详见 `outputs/eval/tool_quality_eval.json`；优化实施另立任务，不在本变更内展开。

**返回契约（用户决策）**：完整事件集**只落盘，不作为工具返回值**——工具仅返回摘要（status/事件数/落盘路径），避免大 JSON 撑爆调用方（agent）上下文；趋势分析等消费方一律读文件。

### ADR-6: agent 侧接入 = `langchain-mcp-adapters`（stdio） — 已定
`backend/scripts/verify_research_tool.py` 演示：adapters 以 stdio 拉起 MCP server → `tools/list` → 实调一次并落盘。仅作连通性与行为验证，不改 `/api/ask`。HTTP 模式仅由 server 启动参数提供，客户端切换不在本变更范围。

### ADR-7: 配置管理 = python-dotenv + 工具目录.env

搜索使用VOLCENGINE_SEARCH_API_KEY，兼容官方MCP的ASK_ECHO_SEARCH_INFINITY_API_KEY；完整端点使用VOLCENGINE_SEARCH_API_URL，默认https://open.feedcoopapi.com/search_api/web_search。VOLCENGINE_SEARCH_INTERVAL默认0.65。配置文件与凭据不入库。TIMELINE_OUTPUT_DIR可指定产物路径，本地服务脚本使用.local/research，避免覆盖历史示例。LLM/embedding保持可选原配置。

### ADR-8: 开发环境 = 项目根 `.venv` — 已定
`python -m venv .venv` 隔离，安装 `backend/requirements.txt`（新增 `mcp`、`langchain-mcp-adapters`、`langchain-openai`、`python-dotenv`；httpx 已随现有依赖可用则不重复钉版本）。后续 apply 均在 venv 内执行；现有 Anaconda base 不回滚（不动它）。

## 评估与优化方案（v4 新增）

评估分两层，结论分别驱动不同动作；本节是 ADR-11 制度依据的重建计划。

### E1 工具层：事件集质量评估（金标准对照）
- 金标准：不参照工具输出，独立从官方大事记/权威媒体盘点/监管公告整理 40-60 个关键事件，
  落盘 `outputs/eval/gold_events.json`。
- 四指标：召回率、精确率、聚类纯度（抽 20 事件人工查 sources 混入）、摘要忠实率
  （summary 每条事实可在 sources 找到，目标 ≈100%）。
- 复用审计尾巴：member_ignored 抽 10 条验误杀；low_authority_dropped 验拦截合理性。
- 驱动：召回不足→校准 include_domains/补 extract 兜底；纯度低→调聚类阈值；忠实率低→收紧 ADR-10 prompt。

### E2 价值层：事件-评论关联检验（修复后重做）
- E2a 脚本固化：伪事件对照检验入库 `backend/scripts/eval_influence.py`，可复现。
- E2b 波峰对齐补对照：除"Top 波峰落在事件±7 天"命中率外，必须同表报告"随机日期落在事件±7 天"
  的基线率；仅当真实波峰命中率显著高于基线，"解释波峰"结论才成立。
- E2c resonance 修复与校准：修空窗口缺陷（前窗口样本不足跳过，不再按 0% 计）；
  人工标注 ≥50 条构建判定员校准集并报告准确率；输出改报分布（中位数/四分位），不单独引用尾部数字。

### E3 决策回流
- E1/E2 结论写回 ADR-11 与交付材料；若基线对照后"波峰解释"不成立，相关表述从交付物移除。
- 优化项按评估结果立项，本变更不预设。

## Risks / Trade-offs

- [Risk] 更换搜索服务后对中文监管/权威源覆盖不足（如 `samr.gov.cn` 可搜性差）→ Mitigation：apply 首个任务为 spike 实测（"小米SU7 召回"等 2-3 组查询），按实测域名分布校准 `include_domains` 与 `source_tiers.json`；检索为空时如实返回 `status=empty`，不编造。
- [Risk] `published_date` 缺失率高导致大量 `date_missing` → Mitigation：首版如实标记；后续变更可加 extract 抓正文日期兜底（本期不做）。
- [Risk] 代理端点（自定义 `VOLCENGINE_SEARCH_API_URL`）不可用或限流 → Mitigation：单维度查询失败仅降 `partial` 状态；配置错误（401/404）快速失败并回显端点。
- [Trade-off] 复合工具把编排写死在代码里，灵活性低于"agent 自由多轮搜索"→ 换取时间线结构稳定、token 消耗可控、结果可复现，趋势分析场景收益更大。
- [Trade-off] stdio 模式下 MCP server 生命周期跟随 agent 进程 → 部署形态简单；将来跨进程复用时切 `--http`，无需改工具逻辑。
- [Trade-off] 时间窗内按年分片使单次调用检索次数 ≈ 查询模板数 × 年份数（约 45 次/产品）→ 换取窗口早期事件的可召回性；单次总成本仍在几分钱量级。
- [Risk] 规则漏斗误杀（把有效事件当 noise 丢弃）→ Mitigation：黑名单与离题词表保守维护，命中统计进 `meta` 可审计；spike 实测误杀/漏放率，必要时引入 LLM 打分兜底。

## Migration Plan

纯新增，无破坏性变更。回滚 = 删除 `backend/mcp_server/`、`backend/scripts/verify_research_tool.py`、`outputs/research/`，并从 `requirements.txt` 移除新增依赖。

## Open Questions

- Docker/compose 归属：确认另开 deployment change？（倾向：是，本变更 Non-goal）
- 首版是否需要 `extract` 二次抓取正文以提升 `summary` 质量？（倾向：否，先用搜索摘要，按 spike 实测摘要质量再定）
- 价值过滤首版纯规则是否够用，是否引入 LLM 批量打分（core/context/noise 三分类）？（倾向：spike 实测规则漏斗的误杀/漏放率后再定；引入则作为规则层之后的可选第二道）

## 本轮部署与验证记录

独立工作树与venv；仅绑定127.0.0.1:8878。采用本机已配置的搜索API Key环境变量，无明文密钥入库。旧示例与评估保留为历史材料，不能用作火山引擎召回率/准确率。实际检查结果在本轮任务记录中追加。

## 本地网页部署扩展（2026-10-11）

用户要求完整事件聚合工具在本地运行，本轮增加网页入口：127.0.0.1:8879，MCP保留8878。网页调用同一core流程，不改来源评分、聚类、改写回退与事件结构。任务单独落盘.local/web-jobs/<id>/，保存状态与结果；同一网页实例仅一个调研任务，重启中断任务明确标记，不自动重复运行。网页只绑定本机，限制Host/Origin，校验输入；配置状态只显示布尔值，不提供密钥读取入口。

## 一键部署设计与验证（2026-10-11）

入口deploy.cmd启动仅当前进程的Windows PowerShell，清理继承的PSModulePath以避免PowerShell7模块遮蔽5.1模块；deploy.ps1建立独立venv并按requirements-lock.txt安装，使用hash跳过重复安装。不修改系统执行策略，不覆盖.env。健康检查只读配置布尔值和MCP工具列表，不发起搜索或模型任务。启动/停止均核对进程属于本组件目录，拒绝停止其他端口服务。

已验证Windows/Python3.11现有环境及干净含空格路径/Python3.12.3首次安装。干净实例8888/8889健康检查通过；通过deploy.cmd重复运行，.env hash及进程ID保持一致；去除测试进程环境中的搜索凭据后可启动并明确显示未配置。测试实例已停止，用户8878/8879实例保留运行。

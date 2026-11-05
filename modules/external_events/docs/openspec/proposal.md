# Proposal

## Why

本地语料只有车主口碑（带 `created_at`），缺少"产品大事件"这条外部时间轴（发布、价格调整、OTA、召回、监管通报等），导致时间趋势分析无法把口碑波动与外部事件对齐。同时，deepagents agent 需要一个可复用、可溯源的外部调研工具，且产品最终要部署，工具层需要与 agent 进程解耦。

## What Changes

- 新增一个 **MCP server 壳子**（FastMCP 实现，`backend/` 下），对外暴露复合工具 `product_timeline_research(brand, product, aspects?, time_from?, time_to?)`：按 5 个研究主题（本品动作/竞品动态/政策法规/技术动向/舆情热点）在**数据时间窗内**分年切片多路检索，内部完成规则漏斗价值过滤（噪声丢弃，core/context 标记）、日期归一（含 `date_precision` 精度）、URL 去重、可信度分级与两级分类（`event_type` 按事件主语 + `subtype` 细类），直接返回结构化事件时间线 JSON。
- 工具内部调用 **火山引擎 Web Search API**（`SearchType=web`，`PublishTime` 归一化为 `published_date`，`Filter.Sites` 收敛来源）；API 地址与 key 从环境变量读取（`VOLCENGINE_SEARCH_API_KEY` / `VOLCENGINE_SEARCH_API_URL`），不写死官方域名。
- **可信度三级分级**：T1 官方/监管（品牌官网、市场监管总局等）、T2 权威媒体、T3 其他（保留但降权打标），供下游趋势分析按 tier 过滤。
- **时间线产物落盘**：调研结果写入 `outputs/research/<brand>_<product>_timeline.json`（含事件日期、类型、标题、摘要、来源、tier、URL），供后续时间趋势分析（与口碑语料 `created_at` 对齐）消费。
- 传输方式：默认 **stdio**（FastAPI/容器内子进程拉起），保留 HTTP 启动切换能力（同一脚本加启动参数），不做远程服务化。
- 环境整改：建立项目 **venv** 并补齐依赖（`mcp`、`langchain-mcp-adapters`、`langchain-openai`、`python-dotenv`）；新增 `.env.example` 模板（复用前项目 `deep_agents_action` 的 配置：搜索/OPENAI/LANGSMITH 系列，key 本身不进仓库）。
- **评估与优化工作流（v4 新增）**：撤回初版实证评估（脚本不可复现、波峰对齐缺随机对照、resonance 含缺陷），改为两层评估——工具层金标准对照（召回/精确/聚类纯度/摘要忠实率）+ 价值层检验修复与重做（脚本固化、基线对照、判定员校准），结论回流设计依据。ADR-11 制度决策保留，依据改判"待检验"。

## Capabilities

### New Capabilities

- `product-timeline-research`: 对指定【品牌+产品】执行可信来源的深度调研，产出按时间排序、带可信度分级的结构化事件时间线（MCP 工具形式提供），作为时间趋势分析的外部事件数据源。

### Modified Capabilities

（无——现有 capability 尚未归档，本变更不修改任何已发布需求。）

## Impact

- **新增代码**：`backend/mcp_server/`（MCP 壳子 + 火山引擎调研逻辑）；`backend/scripts/` 下新增连通性验证脚本。
- **依赖**：`backend/requirements.txt` 新增 `mcp`、`langchain-mcp-adapters`、`langchain-openai`、`python-dotenv`。
- **配置**：新增 `backend/.env`（gitignore）与 `.env.example`；`.gitignore` 补充条目。
- **产物目录**：`outputs/research/`（时间线 JSON）；`outputs/eval/`（v4 新增：金标准事件集与评估报告）。
- **新增脚本**：`backend/scripts/eval_influence.py`（v4 新增：价值层检验脚本，含基线对照）。
- **下游**：为后续变更（时间趋势分析、B 循环接入）提供工具与数据，本变更不修改 `/api/ask` 行为。

## Non-goals

- 不实现 B1-B6 在线 agent 循环，不修改 `/api/ask` 的现有返回（仅预留 MCP client 接入示例脚本）。
- 不做时间趋势分析本身（只准备数据与工具）。
- 不做 Docker 部署与镜像编排（另行开 deployment change；本变更仅保证 MCP server 可被 stdio 子进程方式拉起）。
- 不做多品牌/多产品批量调研任务队列（单次调用单产品）。
- 本轮用火山引擎替换 Tavily，不引入自动搜索服务切换。
- 不打包 Agent Skill（SKILL.md）：该灵感已记录于 `docs/ideas.md`（Idea-1），届时另开变更；本变更的核心逻辑保持框架无关、CLI 可调，为将来包壳留口。

## Open Questions

- Docker 部署（Dockerfile / compose / 秘钥注入）确认另开 change，本变更不含？（倾向：是）
- 价值过滤首版纯规则是否够用，是否引入 LLM 批量打分？（倾向：spike 实测误杀/漏放率后再定；`event_type` 两级分类已定，见 design ADR-3/ADR-5）

## 搜索服务迁移（2026-10-11）

用户明确要求替换为火山引擎并部署本地；实施分支 codex/volcengine-timeline。范围：REST 客户端、编排映射、日期回归、失败状态、配置、测试及本地 MCP 启动。既有聚类/来源分级保留，旧研究数据与评估不重跑、不覆盖；不涉及体验抽取模块。代码最终审查与合并待完成，历史任务记录不作为本轮验收。

## 本地网页范围补充

用户追加要求工具整体部署到本地。新增网页入口、后台任务与进度、历史记录、事件来源展示和JSON/TXT下载，复用现有聚合core；MCP保留。不接入未配置的LLM、不运行独立的评论影响力评估。网页与MCP仅本机监听，密钥不进入网页响应或仓库。

## 一键部署交付

新增Windows deploy.cmd、环境/依赖初始化、协议健康检查、固定依赖文件及服务停止脚本。仅同步当前组件代码与说明；不上传.env、凭据、venv或测试目录。不自动合并本次代码PR，保持可审查交付。

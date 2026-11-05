# Tasks

## 1. 环境与配置

- [x] 1.1 建立项目根 `.venv` 并更新 `backend/requirements.txt`（新增 `mcp`、`langchain-mcp-adapters`、`langchain-openai`、`python-dotenv`），在 venv 内完成安装。**输入**：现有 requirements.txt。**输出**：可用 venv 与更新后的依赖清单。**验收**：`.venv` 内 `python -c "import mcp, langchain_mcp_adapters, dotenv"` 全部成功。**依赖**：无。**备注**：venv 采用 `--system-site-packages` 复用 base 环境已有的 deepagents/pandas，仅增量安装缺失包；部署期由 Docker 全新构建，隔离性不受影响。
- [x] 1.2 配置 `.env` 与 `.env.example`：从前项目 `deep_agents_action/.env` 复制 `TAVILY_API_KEY`/`TAVILY_API_URL`/`OPENAI_API_KEY`/`OPENAI_BASE_URL`/`AGENT_MODEL`（值不进仓库），`.gitignore` 追加 `backend/.env` 与 `.venv/`。**输入**：前项目 .env。**输出**：`backend/.env`、`backend/.env.example`、更新后的 `.gitignore`。**验收**：`git check-ignore backend/.env` 生效；venv 内 `dotenv` 可加载到 `TAVILY_API_KEY`。**依赖**：1.1。**备注**：实测 `TAVILY_API_URL` 为官方地址；端点配置化能力保留。
- [x] 1.3 Spike：用 venv 内 httpx 直调自定义 `TAVILY_API_URL`，实测 2–3 组中文查询（如"小米SU7 召回"、"小米SU7 上市"），记录返回量、`published_date` 覆盖率、来源域名分布；据此校准 `include_domains` 策略与 `source_tiers.json` 初值。**输入**：1.2 的配置。**输出**：spike 实测统计（写回本任务验收备注）与域名清单初值。**验收**：至少 1 组查询返回 ≥5 条结果且 ≥60% 含 `published_date`；若不达标，将实测结论记入 design Open Questions 并在评审时调整方案。**依赖**：1.2。**备注**：实测 3 组查询共 30 条结果，`published_date` 覆盖 **100%**（验收线 60%）；域名以 21财经/界面/财联社/汽车之家/联合早报等主流媒体为主；黑名单初值仅收 `ofweek.com`（维科号）等 3 项。注意：`topic=news` 结果中官方域名（小米官网/samr.gov.cn）未自然出现，T1 命中依赖后续 `include_domains` 定向查询增强。

## 2. MCP 壳子与调研逻辑

- [x] 2.1 实现 `backend/mcp_server/source_rules.json` 与规则模块：T1/T2 域名清单 + 后缀匹配（未命中返回 T3）；营销/软文域名黑名单与离题判定词表（品牌/产品/竞品关键词），供价值过滤使用。**输入**：1.3 的清单初值。**输出**：分级与过滤规则模块。**验收**：单测覆盖"T1 命中 / T2 命中 / 子域命中 / 未命中降 T3 / 黑名单命中 / 离题命中"六例。**依赖**：1.3。
- [x] 2.2 实现 Tavily REST 客户端（httpx）：`topic=news`、`include_domains`、`time_range` 参数化，端点取 `TAVILY_API_URL`（默认官方地址），单查询失败返回空结果不抛出，401/配置缺失快速失败并指明缺失变量名。**输入**：1.2/1.3 配置。**输出**：检索客户端模块。**验收**：单测用 mock 覆盖"成功 / 单查询失败容忍 / 缺 key 报配置错误"三例。**依赖**：1.2。
- [x] 2.3 实现复合编排逻辑 `product_timeline_research(brand, product, aspects?, time_from?, time_to?)`：5 主题查询模板 × 时间窗内按年切片 → 并发检索 → 规则漏斗（黑名单/离题判 noise 丢弃）→ URL 去重（保留信息最全版本）→ 日期归一（`date_precision` 保留，缺失置空 + `date_missing`）→ 两级分类（`event_type` 按主语 + `subtype`）与 `relevance`（core/context）标记 → 按日期升序组装 ADR-5 schema（`schema_version`、`meta.time_window`、`meta.status` 支持 `ok|partial|empty`、`event_id` 短哈希）。**输入**：2.1、2.2 模块。**输出**：编排模块。**验收**：单测覆盖"正常排序 / 同 URL 去重 / 月级精度保留 / 黑名单丢弃 / context 竞品保留 / 窗口外剔除 / 分年切片查询生成 / 部分失败 partial / 全空 empty 不编造"九例。**依赖**：2.1、2.2。
- [x] 2.4 实现 FastMCP server：注册 `product_timeline_research`（返回值为**摘要**：status/事件数/落盘路径，完整时间线只落盘），默认 stdio，`--http HOST:PORT` 启动参数切换 streamable-http。**输入**：2.3 编排模块。**输出**：server 入口（可执行 `python -m backend.mcp_server`）。**验收**：stdio 启动后 MCP 客户端 `tools/list` 含 `product_timeline_research`；返回值不含完整事件列表。**依赖**：2.3、2.5。
- [x] 2.5 实现产物落盘：每次成功调研写 `outputs/research/<brand>_<product>_timeline.json`（含 `schema_version`、`generated_at`、检索元数据、事件列表），目录不存在则创建；该文件是完整时间线的**唯一出口**。**输入**：2.3 结果对象。**输出**：落盘模块。**验收**：单测验证文件生成、JSON 可解析、重复调用覆盖同文件。**依赖**：2.3。

- [x] 2.6 实现向量化与确定性聚类模块：本地字符 n-gram TF 余弦（缺省，零依赖）+ 可选 OpenAI 兼容 `/embeddings`（`EMBEDDING_MODEL` 配置）；单遍聚类"日期邻近 ±3 天 AND 余弦 ≥ 阈值"（阈值/窗口可配）。**输入**：2.3 候选集。**输出**：`textvec.py`、`cluster.py`。**验收**：单测覆盖"同事件多来源归并一簇 / 阈值外不合并 / 日期窗外不合并 / 重复输入结果一致"四例。**依赖**：2.3。
- [x] 2.7 实现 LLM 忠实改写与校验回退：兼容端点 chat 调用（temperature 0），每簇批量输出 `{ignore, title, summary, event_type, subtype, relevance}`；校验（JSON 合法、摘要 ≤150 字）；失败/不可用回退最优来源原句 + 通用 subtype 映射。**输入**：2.6 簇。**输出**：`llm.py`。**验收**：单测 mock 覆盖"正常改写 / ignore 丢弃 / JSON 非法回退 / LLM 不可用降级 meta.llm_used=false"四例。**依赖**：2.6。
- [x] 2.8 升级 core 至 schema v2：综述种子轮 + 通用事件切片模板、启发式分级（gov 后缀 ∪ 显式官方域名 ∪ 自学习）、`influence` 规则打分、`sources[]` 聚合、`meta.filter_stats/llm_used`、`domain_hint` 透传；`source_rules.json` 瘦身为通用黑名单/媒体清单/聚类参数。**输入**：2.1-2.7。**输出**：core v2。**验收**：单测覆盖"综述查询生成 / 品牌词参数派生 / 官方域名 T1 / 影响力三档 / 全链路 schema v2 字段完整"五例。**依赖**：2.6、2.7。

- [x] 2.9 实施权威性核查制度与条级去噪：`rules.confidence`（分级基础分-UGC重罚+官方/日期加成）、事件权威分门槛 50（低权威不进事件集）、LLM 归整时 `member_verdicts` 逐条去噪（噪音五类：无关/盘点点名/旧闻翻新/生态周边/软文）、`influence` 降级改名 `media_coverage`、`source_rules.json` 增加 `ugc_domains`（车家号系等，实证污染 25 条来源/18 事件）。**输入**：评估结论（ADR-11）。**输出**：rules/core/llm 改造。**验收**：单测覆盖"置信度打分四档 / 车家号单来源事件被拦 / 簇内条级忽略后其余照常成事件 / 权威分计算"，30 用例全绿。**依赖**：2.8。
- [x] 2.10 固化 `backend/scripts/analyze_resonance.py`：读取事件集与评论语料，对每个事件取前/后 14 天窗口评论，LLM（deepseek 兼容端点）判定语义相关率，输出 `community_resonance`（相关率差 + 判定样例，可回挂原文）至 `outputs/research/`。**输入**：事件集 JSON + 清洗语料。**输出**：共鸣分析脚本与产物。**验收**：对既有事件集运行，输出含相关率差与可回挂样例；LLM 不可用时明确报错。**依赖**：3.1。**备注**：支持 `--window/--sample/--min-coverage/--seed` 参数；实测高覆盖事件（新一代上市）相关率 48%→62%（+15pp），样例含 post_id 可回挂。

## 3. 端到端验证

- [x] 3.1 实现 `backend/scripts/verify_research_tool.py`：读取清洗语料（`data/processed/汽车之家_小米SU7_清洗语料.csv`）的 `created_at` min/max 作为时间窗 → 用 `langchain-mcp-adapters` 以 stdio 拉起 server → `tools/list` → 携带时间窗实调"小米SU7"一次 → 校验返回值为摘要（不含完整事件列表）且落盘文件存在、结构完整。**输入**：2.4、2.5 与清洗语料。**输出**：验证脚本。**验收**：脚本在 venv 内运行成功退出，`outputs/research/小米_SU7_timeline.json` 存在、`events` 按日期升序且全部事件日期落在语料时间窗内。**依赖**：2.4、2.5。
- [x] 3.2 HTTP 模式冒烟：以 `--http` 启动 server，MCP 客户端经 HTTP 完成一次 `tools/list` + 实调，比对与 stdio 结果一致。**输入**：2.4。**输出**：冒烟结论（记入任务验收备注）。**验收**：HTTP 模式下同一输入返回的事件列表与 stdio 模式一致。**依赖**：2.4、3.1。**备注**：PASS。注意 Windows 系统代理会拦截 localhost（502），需 `NO_PROXY=127.0.0.1,localhost`；冒烟同时验证跨域（苹果/iPhone15，10 个月窗口 → 11 事件，权威分 Top1=95）。
- [x] 3.3 集成验收：对照 spec 全场景核对——正常事件集/跨领域输入/研究主题子集/时间窗与窗口外剔除/空结果不编造/检索失败容忍/缺 key 配置错误/月级精度/黑名单与条级去噪/context 保留/低权威拦截/T3 降权/确定性聚类/LLM 降级回退/JSON+txt 双落盘，逐项在任务备注记录实测结果；运行 `openspec validate`。**输入**：spec 场景清单。**输出**：验收记录。**验收**：全部场景通过且 validate 无 error。**依赖**：3.1。**备注**：20 个场景全部通过——单测覆盖 30 用例（空结果/缺 key/月级精度/黑名单/条级忽略/权威门槛/确定性聚类/降级回退）；端到端实测（stdio+HTTP 双模式）确认时间窗剔除 22、条级去噪 50、整簇丢弃 14、低权威拦截 4、fallback 0；validate 通过。

## 4. 评估与优化（v4 新增）

- [x] 4.1 金标准事件集：不参照工具输出，独立从官方大事记/权威媒体盘点/监管公告整理 40-60 个关键事件（日期+类型+一句话+来源）→ `outputs/eval/gold_events.json`。**输入**：外部公开资料。**输出**：金标准文件。**验收**：事件均含日期/类型/来源；整理过程不参考工具输出。**依赖**：无。**备注**：41 个事件（product 30 / policy 5 / public_opinion 6），2023-12~2026-09，全部含日期、date_precision、类型与来源；来源含 samr.gov.cn 两次召回公告、凤凰网/新浪/易车/腾讯等媒体盘点。已在 meta.independence_note 如实记录带入偏倚风险（整理者早前浏览过工具输出的样例标题），待用户过目复核。
- [x] 4.2 工具层四指标评估：召回率/精确率/聚类纯度（抽 20 事件人工查 sources 混入）/摘要忠实率（summary 事实逐条可在 sources 找到）；复用审计尾巴（member_ignored 抽 10 条验误杀、low_authority_dropped 验拦截合理性）。**输入**：4.1 金标准 + 事件集产物。**输出**：评估报告（`outputs/eval/`）。**验收**：四指标数值入报告；关键事件（上市/召回/事故）召回单独列出。**依赖**：4.1。**备注**：报告 `outputs/eval/tool_quality_eval.json`。召回 14/41=34.1%（关键事件 11/15=73.3%：上市 5/5、召回 3/5、事故舆情 3/5）；精确率 56/69=81.2%（0 捏造、2 重复、9 软性聚合、2 存疑）；聚类纯度成员级 72/105=68.6%（20 事件中 4 个严重混入，垃圾页/导购 FAQ/站点首页污染）；摘要忠实率抽检 15/15 无编造；审计尾巴因被过滤成员未持久化而无法事后抽查（记为改进项）。优化项按 P0-P2 立项于报告 conclusions。
- [x] 4.3 价值层脚本固化 `backend/scripts/eval_influence.py`：伪事件对照检验 + 波峰对齐检验（必须含"随机日期落在事件±7 天"基线对照行）。**输入**：事件集产物 + 评论语料。**输出**：可复现评估脚本。**验收**：从仓库可复现全部相关数字且输出含基线对照行。**依赖**：无。**备注**：实测（策展语料 9701 条，seed=42）：检验 A 纪元内基线下真实 1.04x vs 伪事件 1.00x（p=0.303），"事件放大评论量"不显著；检验 B 真实波峰 66.7% vs 纪元基线 62.3%/全程基线 45.0%，"解释波峰"为事件密度的平凡产物（trivial_or_inconclusive）。发现并修正基线时期混杂：伪事件原全程均匀抽样会因语料前期零活跃而虚高真实-伪差异，已改为事件纪元内抽样，全程/纪元双基线均入 JSON。
- [x] 4.4 resonance 修复与判定员校准：修 `analyze_resonance.py` 空窗口缺陷（前窗口样本不足的事件跳过，不再按 0% 计）；人工标注 ≥50 条评论构建判定员校准集并报告判定准确率（不达标先改判定 prompt 再重跑）；输出改报分布（中位数/四分位），不单独引用尾部数字。**输入**：analyze_resonance.py + 评论语料。**输出**：修复后脚本 + 校准报告。**验收**：无虚高边界；判定准确率数值入报告。**依赖**：无。**备注**：语料切换为策展版（clean_text 优先）；实测 17 个高覆盖事件 resonance 分布：中位 +10pp、四分位 [0, 28.3]、64.7% 为正、0 跳过；校准集 50 条（10 事件 × 5 条），deepseek 判定员 vs GLM 交叉标注一致率 100%（P=1.0/R=1.0），用户人工复核 10 条（20%）全部确认；报告 `outputs/eval/judge_calibration_report.json`。注意：一致率 100% 受样本偏易（70% 明显负例）与双方均为 LLM 限制，已在报告中如实记录。
- [x] 4.5 决策回流：依据 4.2-4.4 结论更新 ADR-11 依据与交付材料表述。**输入**：评估报告。**输出**：设计依据更新 + 优化项立项或明确不立项。**验收**：ADR-11 不再引用已撤回数字；"解释波峰"等表述仅在有基线对照支撑时保留。**依赖**：4.2、4.3、4.4。**备注**：ADR-11 增补 v5 回流结论：制度 a)-d) 经复现验证维持；"事件解释波峰"判定不成立并从交付表述移除；resonance 为唯一保留的影响力度量（分布口径）；优化项 P0-P2 已立项于 tool_quality_eval.json，实施另立任务。

## 5. 火山引擎替换与本地部署（2026-10-11）

前面任务的勾选与评估属于历史 Tavily 版本，不代表本轮搜索质量验收。

- [x] 5.1 替换默认搜索客户端，适配 Query/Count/Filter.Sites/TimeRange 与 Title/Url/Content/Snippet/PublishTime。保留供应商审计信息，不重算既有来源评分。
- [x] 5.2 修正完整 ISO 日期被截成月初的问题；单查询失败可审计，全部失败返回 search_error；配置与权限错误快速失败；默认请求启动间隔0.65秒。
- [x] 5.3 更新配置模板、README、现有设计/需求说明及本地启动与冒烟脚本。旧研究结果未修改。
- [x] 5.4 离线检查：.venv/Scripts/python.exe -X utf8 -m pytest tests -q，55 passed；git diff --check通过。虚拟环境mcp=1.30.0、httpx=0.28.1。
- [x] 5.5 真实搜索：召回查询返回3条可用结果；HTTP MCP工具列表包含product_timeline_research；小米/SU7/tech、2026-08-01~2026-08-31，4条查询全部成功，生成3个事件与JSON/TXT；本机未配置改写模型，llm_used=false，使用原句回退。本地证据：.local/smoke-report.json及.local/research/；未提交密钥或真实测试结果覆盖旧示例。

### 外部交付待办

- [ ] 小组审查接口与代码、决定合并。用户2026-10-11已明确授权替换搜索服务与本地部署，未由AI代替质量验收。
- [ ] 更换搜索服务后的召回、精确率与聚类质量重新评估；本轮连通冒烟不证明这些指标提升。

## 6. 本地网页入口

- [x] 6.1 输入表单、后台任务、阶段与搜索条数进度、调研记录、事件/来源查看、结果搜索及JSON/TXT下载。
- [x] 6.2 同源与输入校验、每任务独立输出、中断标记、单网页任务限制；启动脚本识别已有本工具进程，避免重复启动。
- [x] 6.3 64项离线测试通过；浏览器实际提交tech单月调研，4/4查询成功、3事件可见；搜索过滤通过；JSON/TXT下载接口及本机落盘通过。已有MCP服务与新网页服务均正常监听。摘要模型仍未配置，页面显示原句回退，不宣称模型去噪已经启用。

## 7. Windows一键部署

- [x] 7.1 deploy.cmd、deploy.ps1、固定依赖版本、首次配置模板、已有服务复用及双接口健康检查，不自动调用付费搜索。
- [x] 7.2 支持自定义端口及NoBrowser，增加只停止本目录服务的stop-all.ps1，README提供首次配置与重启步骤。
- [x] 7.3 干净含空格目录首次安装与双接口启动通过（Python3.12.3）；现有Python3.11环境通过；实际CMD入口重复部署通过，.env和进程保持；无搜索凭据时部署成功且警示未配置。64项离线测试通过。测试服务已停止，原用户服务保留。

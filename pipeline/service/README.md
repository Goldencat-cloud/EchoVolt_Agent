# AutoInsight 语义分析服务

本地 MVP 服务只读消费 06 的冻结分析数据，提供受限统计与精选观点查询，以及报告问答和对话分析 API；
不会重跑上游采集/标注模型链路，也不会伪造无证据的结论。配置模型后，报告问答与深度分析会调用服务端模型。基础查询/API 使用 Python 标准库；运行 DeepAgents 深度分析需要安装 `requirements.txt` 中的模型依赖。

报告只有两种形态：右侧**设计版报告**（auto-023 产出的离线预制文档，报告问答的唯一语料）
与**深度分析报告**（用户显式触发，Agent 实时生成）。
深度分析先提交结构化计划，逐项执行计划中的统计方法和证据检索；计划未完成时不能提交报告。
深度分析失败会显示为失败，不会自动切换成另一条分析链路。

## 当前边界

- 快照版本来自 `06_reporting/agent-kb/output/data-version.json`，目前明确是占位数据（临时样本）。
- 指标 `negativeShare` 定义为负面观点声明数 / 观点声明总数（声明级口径）；
  `negative_posts / posts` 是另一个单位下的帖子级计数，两者不可混用。
- 观点检索只覆盖 core/potential 精选集合；返回会标记为精选证据且显示截断信息。
- 未配置模型服务时，`/api/question` 与 `/api/ask` 均返回 503（显式失败，不伪造回答）；
  报告与统计页面不受影响。

## 模块职责

- `app.py`：HTTP 适配层、请求限制和用例入口；
- `research/catalog.py`、`research/service.py`、`research/analysis_methods.py`：唯一指标/维度目录、冻结快照查询和预定义分析；
- `semantic/`：声明式指标/维度/口径模型及其编译、执行与适配（唯一取数来源）；
- `kernel/`：运行姿态、运行状态、工具登记与 agent 装配的唯一入口；
- `integrations/mcp_server.py`：官方 MCP SDK 只读适配（`python -m integrations.mcp_server` 启动）；
- `agent_engine.py`、`agent_tools.py`、`agent_skills/`：深度分析计划、受限工具和 Agent 操作说明；
- `report_gate.py`、`report_publisher.py`、`report_source.py`：报告门禁、审核发布和报告问答知识源。

Python 模块按职责保持单向依赖：HTTP/API、Agent 和 MCP 适配器调用研究语义与报告用例；研究目录和查询不依赖传输协议。聚合方法目录只有 `semantic_aggregate`（旧的 `run_aggregate` 原语与 `routing/` 包已在 auto-042 删除）。`research-brief.json` 只引用目录版本及指标/维度 ID，不复制定义。skills 是 Agent 读取的工作说明，不是 MCP 工具或协议；MCP 通过 `integrations/mcp_server.py` 使用标准协议和只读工具注册。

## 干净环境运行

基础服务要求 Python ≥3.11；深度 Agent 和 MCP 需要 `pip install -r requirements.txt` 和对应模型环境变量。

```powershell
cd pipeline/service
python app.py                # 启动 Web 服务，浏览器打开 http://127.0.0.1:8000
# 全部单元/接口测试（本仓库用显式模块列表：discover -s tests 会报
# Start directory is not importable）
$mods = Get-ChildItem tests -Filter "test_*.py" | ForEach-Object { "tests." + $_.BaseName }
python -X utf8 -m unittest @mods
```

### MCP（只读）

MCP 使用官方 Python SDK，默认通过 stdio 供本地 MCP Host 启动：

```powershell
python -m integrations.mcp_server
```

工具包括健康检查、版本化业务指标/维度目录、统计查询、精选观点查询、分析方法目录和白名单方法执行。MCP 客户端应将本地解释器与 `integrations/mcp_server.py` 配置为 stdio 子进程；不要把它配置成公网 HTTP 服务。所有结果沿用同一快照、口径和验证逻辑；审核/发布、任意 SQL、文件访问及 Python 沙箱不暴露给 MCP。`mcp` SDK 未安装时，协议入口会明确报依赖错误；skills 文件不能替代 MCP server。完整客户端握手需在安装 `requirements.txt` 后用 MCP Inspector 或官方客户端验证。

### 容器运行

公网预览应通过 Docker Compose 运行。配置已启用非 root 用户、只读根文件系统、只读数据挂载、
临时目录、移除 capabilities、禁止提权，并限制内存、CPU 与进程数。报告目录需要允许容器 UID
10001 写入；模型服务需要允许容器对配置的 LLM 地址发起出站连接。容器约束仍需在目标平台实际部署并做安全评审后才能作为公网隔离验收。

```powershell
docker compose build
docker compose up -d
```

## claim_id 规则（任务 1.5）

`claim_id = sha256("{snapshot_hash}:{key}").hexdigest()[:20]`，其中 `key` 为观点记录的
`key` 或 `post_id:claim_id`，`snapshot_hash` 为快照来源清单的确定性 hash。同一快照重建
得到相同 ID；不承诺跨数据版本稳定。验证见
`tests/test_service.py::test_claim_ids_are_repeatable_and_scoped_to_snapshot`。

## API

- `GET  /api/health` — 只检查服务与快照可读性，不调用 LLM。
- `GET  /api/stats?aspect=空间与舒适性` — 版本化统计信封。
- `GET  /api/claims?aspect=…&sentiment=负面&limit=5&offset=0` — 精选观点分页。
- `GET  /report/full` — 设计版报告页（auto-023 产出的单文件 HTML，图表内嵌）。
  **Owner 决定（2026-10-25）**：产品报告页直接采用该设计版报告；其内容为上一版本
  临时样本，页面保留"临时样本"标识，新数据版本就位后由报告管线重新生成替换。
- `POST /api/question` `{question, session_id?}` — **统一提问入口**。每一轮都交给同一个
  上下文化 Agent，由它按需要选择工具；返回 `response_type=conversation` 与
  `{answer, stats[], evidence[], applied_filters, citations, warnings, request_id}`。
  服务端不再做意图分类，也不回传 `intent`。超出对话能力的深度分析诉求返回
  `warnings=["deep_analysis_guided"]` 并引导走 `/api/agent/report`；未配置模型时 503。
- `POST /api/analyze` — **已移除**（auto-042），请求返回 404；对话分析统一走
  `/api/question`，不存在第二条分析链路。
- `POST /api/ask` `{question}` — 报告问答，覆盖右侧设计版报告并校验锚点；
  未配置模型时返回 503。
- `GET /api/reports/published/latest` — 返回最新通过审核发布的深度报告；无已发布深度报告时返回 404。
- `GET /api/analysis/options` — 深度分析表单选项目录（auto-031）：分析对象（当前仅小米 SU7）、
  时间范围切片（近 1/3/6 月 + 全部，均落在快照覆盖区间内）与覆盖声明，与简报同源。
- `POST /api/agent/report` `{question, aspect?, brief?, session_id?}` — **深度分析入口**
  （带增强简报与多轮澄清；brief 字段非法时 400 并附允许值）。返回 202 与 `job_id`。
- `POST /api/agent/report/{job_id}/clarify` `{answers:{字段:值}}` — 澄清答复；字段名非法
  400 并附 `allowed_fields`。答复后进入数据探索。
- `GET /api/agent/report/{job_id}` — 任务状态机：`queued → clarifying → running →
  awaiting_review → running → done|failed`；待审时附 `outline`（子问题投影）、
  `plan_json`、`outline_history`，供审查卡片渲染。
- `POST /api/agent/report/{job_id}/outline` `{action, plan_json?, feedback?, focus?, audience?}`
  — 大纲审查三动作：`confirm`（批准执行）/ `edit`（编辑版 plan_json 重过同一校验器）/
  `regenerate`（打回重写，上限 3 次，超限 429）；可选 `focus`/`audience`（交付规格，
  注入执行上下文）。非待审状态 409。
- 错误语义：参数无效 400；请求体过大 413；限流/会话超轮数 429；
  模型未配置或调用失败 503；工具/快照错误 500，均附 `request_id`。
- 工具输入输出契约与错误码样例见 `tests/fixtures/tool-contract.json`
  （静态校验：`tests/test_tool_contract.py`）。

## 模型配置（服务端密钥）

- 对话分析（OpenAI-compatible）：`AI_BASE_URL`、`AI_API_KEY`、`AI_MODEL`；
  仅在 Owner 确认数据可传输后设置 `AI_DATA_APPROVED=1` 启用生成式解释。
- 报告问答复用 07 的客户端：`REPORT_KB_LLM_BASE_URL` / `REPORT_KB_LLM_API_KEY` /
  `REPORT_KB_LLM_MODEL`。
- 密钥只从服务端环境变量读取；仓库与前端资源不含密钥。访问日志只记录 request_id、
  方法、路径与状态码，不记录问题全文、提示词或引文正文。
- 限制：请求体 4KB；问题 500 字；每 IP 每分钟 10 次分析/问答请求；
  每会话最多 20 轮；最多同时运行 2 个深度 Agent 任务（会话/任务为服务端内存态，重启后请重新开始）。

## 深度报告审核与发布

Agent 提交的报告先进入 `reports/agent/<report_id>/` 的 `pending_review` 队列。
提交门禁检查必需章节、数据版本、观点 `claim_id` 是否来自本次证据工具、结构化计划是否逐项执行，以及分析步骤是否通过确定性校验。
门禁通过只允许进入人工审核，不代表内容正确。非作者队友检查结论、口径、证据代表性和表达边界后，在服务端工作区执行：

```powershell
python report_publisher.py <report_id> --reviewer "审核人" --reviewed-commit <commit-sha> --verdict approved --note "审核意见"
```

驳回时将 `--verdict` 设为 `rejected`。审核记录写入报告元数据；批准后报告才可由 `/report/full`、报告问答和 `/api/reports/published/latest` 读取。该命令不提供公网审核接口，公开数据授权仍需 Owner 确认。

## 07 集成说明

`/api/ask` 复用 `07_qa_agent/src/qa_agent/llm.py` 的 OpenAI-compatible 客户端与锚点校验
规则，但以**设计版报告**为知识源（即用户右栏看到的文档，引用可点击跳转），并把数据版本页脚
追加到每个回答。07 模块本身不被修改。

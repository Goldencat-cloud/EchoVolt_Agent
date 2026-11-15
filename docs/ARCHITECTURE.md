# EchoVolt_Agent 架构总览

> 本文是唯一的权威架构说明。旧文档（PR_DESCRIPTION / MIGRATION_CHECK 等）已归档到
> `pipeline/docs/archive/`，不再作为指南。若本文与代码不一致，以代码为准并更新本文。

## 1. 系统组成

仓库由三个包组成，职责单一、依赖单向：

```
EchoVolt_Agent/
├── pipeline/           离线数据处理（批处理管道）
│   ├── 01_ingestion    采集：网页 → ingestion.sqlite3
│   ├── 02_cleaning     清洗：噪声标注，写回清洗库
│   ├── 03_media        历史多模态理解产物 + 复分析
│   ├── 04_extraction   信息抽取：帖 → claim 结构化结果
│   ├── 05_normalization 实体归一：aspect/mention → taxonomy
│   ├── 06_reporting    agent-kb：唯一报告生成与发布实现
│   ├── 09_industry_kb  行业政策/术语语料整理
│   ├── service/        在线语义分析与 Agent 服务（唯一常驻进程）
│   ├── data/           数据区（stock / published / runtime / live-acceptance）
│   └── tools/          质量门禁
├── modules/            独立研究模块（external_events 等，不接主线）
├── docs/               本文件 + 架构文档
└── openspec/           需求/变更规范（spec-driven）
```

### 依赖方向

```
pipeline 各阶段（01→02→04→05 → service.build → 发布）
service（API → Engine → Semantic）
   └─ Semantic 不依赖 Agent；Agent 不直接操作数据库；API 不含分析业务
modules  ← 不 import 主线；主线不 import modules
```

## 2. 模块职责

| 模块 | 负责 | 不负责 |
|---|---|---|
| 01_ingestion | 采集入库、快照溯源、质量校验 | 清洗/抽取 |
| 02_cleaning | 噪声识别与标注（写 `cleaning_annotations`） | 语义抽取 |
| 03_media | 保存冻结的图片理解结果；复分析能力 | 不重跑已完成批次 |
| 04_extraction | 抽取 claim（冻结输入 + 工具） | 归一 |
| 05_normalization | aspect/mention 归一为 taxonomy | 语义查询 |
| 06_reporting/agent-kb | 唯一报告生成与发布 | 交互分析 |
| service/api（`routes.py`） | HTTP 路由、验证、限流、静态资源 | 业务逻辑 |
| service/engine（`kernel/`+`agent_engine.py`+`agent_tools.py`） | Agent 装配与执行、工具、技能、预算 | 直接写 SQL |
| service/semantic（`semantic/`） | 语义模型（model.yaml 单一真源）、SQL 编译执行、校验 | HTTP/Agent |
| service/orchestrator（`orchestrator.py`） | 报告任务/问答/对话编排（框架无关） | HTTP 协议 |

### service 内部分层（本轮重构固定）

- `routes.py`：HTTP 协议层。
- `orchestrator.py`：业务编排层（报告任务、问答、对话）。
- `app.py`：应用入口 + 依赖装配 + 兼容门面（re-export）。
- `kernel/`：Agent 运行时（不 import 宿主层）；宿主装配能力经 `agent_factory`
  由 `agent_engine.default_agent_factory` 注入（循环依赖已解除）。
- `agent_tools.py`：工具集；错误预算统一经 `record_tool_error(context)`。
- `llm.py`：统一 LLM 客户端创建入口（chat / embeddings）。

## 3. 数据存储约定

三个固定位置 + 各阶段自己的 `results/`（详见 `pipeline/data/layers.json`）：

| 路径 | 内容 | 规则 |
|---|---|---|
| `pipeline/data/stock/db/ingestion.sqlite3` | 唯一采集库 | 01 写业务表，02 写标注表，其余只读 |
| `pipeline/data/published/semantic.db` | 唯一发布库 | 仅由 `python -m semantic.build` 从 stock+04+05 确定性重建，服务只读 |
| `<阶段>/results/` | 阶段中间产物 | 留在阶段内，大文件不进 Git |
| `pipeline/03_media/source_metadata/` | 源 CSV（002/003/004） | 只读 |
| `pipeline/09_industry_kb/corpus/` | 政策/术语原文 | 只读 |
| `pipeline/data/runtime/` | 重跑产物落盘区 | 不进 Git |
| `pipeline/data/live-acceptance/` | live 验收库与响应证据块 | 只读 |

## 4. Pipeline 执行方式

各阶段独立运行（详见各目录 README / CLI `--help`）：

```bash
# 清洗（例）
python pipeline/02_cleaning/tools/run_cleaning.py \
  --db pipeline/data/stock/db/ingestion.sqlite3 [--dry-run]

# 重建发布库（读 model.yaml 声明，确定性）
cd pipeline/service && python -m semantic.build

# 数据新鲜度门禁
python pipeline/tools/quality_gate.py --check semantic-freshness
```

## 5. Service 启动方式

```bash
cd pipeline/service
python app.py            # 默认 127.0.0.1:8000（HOST/PORT 环境变量可覆盖）
```

配置由 `config.py` 从 `pipeline/local-config/`（或进程环境）装载；密钥只读环境变量，
`local-config/` 不入 Git。

## 6. 测试方式

```bash
cd pipeline/service && python -m pytest tests            # 服务（485 用例）
cd pipeline/01_ingestion && $env:PYTHONPATH='src'; python -m pytest tests   # 采集
cd pipeline/02_cleaning && python -m pytest tests         # 清洗
cd modules/external_events && python -m pytest tests      # 独立模块
```

质量门禁：`python pipeline/tools/quality_gate.py --check semantic-freshness`（exit 0=通过）。

## 7. Git 分支与协作规范

- 每个 Change 一个 `change/<id>` 分支，交付走 PR，不直接写 main、不自 merge。
- 数据（采集库/发布库/冻结产物）迁移时保留原始副本并核对完整性（SHA256 或重建比对）。
- 大文件与运行日志不入 Git（见 `.gitignore`）。

## 8. 新模块接入约定

1. 明确职责与输入输出；独立研究项目放 `modules/`，主业务链放 `pipeline/` 或 `service/`。
2. 不 import 主线内部实现；主线不 import `modules/`。
3. 关键业务逻辑配测试；接入后跑全量测试 + 门禁。
4. 有数据契约变更时，先改 `semantic/model.yaml` 或本文，再改代码。

## 9. 已知事项

- 02 清洗锚点按 9,994 帖（SU7）校准；竞品 32,993 帖导入后，`test_integration_stock.py`
  的 3 个基线断言因数据规模变化失败，属已知数据漂移，待锚点重校准任务处理。
- 竞品帖尚未做 claim 抽取（`fct_claim` 及以上仍为 SU7-only），这是有意保留的边界。

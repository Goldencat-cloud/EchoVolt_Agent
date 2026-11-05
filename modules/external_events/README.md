# 事件聚合工具（product-timeline-research）

> 从「汽车评论 → 产品改进决策」主项目中独立出来的**外部事件聚合工具**。它能把一个品牌 + 产品
> 在指定时间窗内的公开报道，聚合成**可溯源、可校验的事件时间线**，并与论坛评论做共鸣/影响力分析。

## 1. 这个工具做什么

给定 `品牌 + 产品 + 时间窗`（如 小米 / SU7 / 2022-10-28~2026-10-03），工具会：

1. **两轮检索**：综述种子查询（大事记/盘点/发展历程）+ 5 个主题切片（产品/竞品/政策/技术/舆情），
   按年份展开，全部走火山引擎 Web Search `SearchType=web`；
2. **漏斗过滤**：黑名单域名 → 离题判定 → 时间窗 → URL 去重；
3. **来源分级与置信度**：T1（政府/官方域名）/ T2（通用权威媒体）/ T3，UGC 自媒体重罚，
   事件权威分 = 最高来源置信度 + 独立域名印证加成，**低于门槛（`min_event_authority=50`）的事件直接丢弃**；
4. **确定性聚类**：日期邻近（±3 天）**且** 文本余弦 ≥ 阈值才合并，分组不交给 LLM，同输入必同输出；
5. **LLM 忠实改写**：逐条判定簇内成员去留（盘点/旧闻翻新/软文等被剔除），再仅依据保留成员的来源事实
   合成标题、摘要、事件类型；**LLM 不可用时自动降级**为取最优来源原句；
6. **落盘**：完整事件集写 `outputs/research/<品牌>_<产品>_timeline.json` + 同名 `.txt` 可读版，
   **工具返回值只有摘要**（status / event_count / output_path），避免上下文爆炸。

跨域泛用：品牌词、产品词均从入参派生，模板/分级/阈值不预设行业（已用「苹果 iPhone15」验证）。

## 2. 目录结构

```
event-timeline-research/
├── README.md                 本文件
├── requirements.txt          运行依赖
├── .env.example              环境变量模板（复制为 .env 后填写，.env 不入库）
├── src/
│   └── mcp_server/           事件聚合核心（MCP 工具包）
│       ├── server.py         FastMCP 入口，暴露 product_timeline_research
│       ├── core.py           编排主流程：检索→过滤→归一→聚类→改写→权威性过滤
│       ├── cluster.py        确定性事件聚类（日期邻域 + 余弦阈值）
│       ├── rules.py          来源分级 / 置信度 / 噪声规则
│       ├── source_rules.json 分级清单、置信度与聚类阈值配置
│       ├── volcengine.py     火山引擎 REST 客户端（缺 key / 401 快速失败）
│       ├── textvec.py        向量化：OpenAI 兼容 embeddings，失败回退本地 n-gram TF 余弦
│       ├── llm.py            LLM 忠实改写与条级去噪（temperature 0）
│       ├── storage.py        产物唯一出口（JSON + 可读 TXT）
│       └── __main__.py       启动入口：默认 stdio，--http HOST:PORT 切 HTTP
├── scripts/                  离线分析与评估脚本
│   ├── verify_research_tool.py    端到端验证：MCP stdio 实调 + 落盘结构校验
│   ├── analyze_resonance.py       事件-评论共鸣分析（前后窗口评论是否真在讨论该事件）
│   ├── eval_influence.py          价值层评估：伪事件对照 + 波峰对齐随机基线
│   └── make_judge_calibration.py  判定员（LLM）校准集构建与评分
├── tests/
│   ├── test_research.py      离线单测（检索/向量/聚类/改写/落盘全 mock）
│   └── conftest.py           把 src/ 加入 sys.path
├── docs/
│   ├── outputs.md            产出文件与评估口径说明
│   └── openspec/             设计工件：proposal / design / tasks / spec
├── data/                     输入语料（见 data/README.md）
└── outputs/                  随仓库发布的示例产出
    ├── research/             事件时间线（v1 工具原始产出 / v2 精修事件轴 / 共鸣分析）
    └── eval/                 金标集、工具质量、影响力、判定员校准
```

## 3. 安装

```bash
# 1) 推荐虚拟环境（Python 3.11+，实测 3.13 可跑）
python -m venv .venv
# Windows: .venv\Scripts\activate   |   macOS/Linux: source .venv/bin/activate

# 2) 安装依赖
python -X utf8 -m pip install -r requirements.txt

# 3) 配置密钥
cp .env.example .env      # Windows: copy .env.example .env
```

`.env` 至少填 **VOLCENGINE_SEARCH_API_KEY**（检索必需，也兼容已有 `ASK_ECHO_SEARCH_INFINITY_API_KEY`）；建议再填 LLM 三项 `OPENAI_API_KEY` /
`OPENAI_BASE_URL` / `AGENT_MODEL`（改写与去噪，缺失时工具自动降级但仍可用）。
`EMBEDDING_*` 可选，不配则用内置字符 n-gram 相似度（零依赖、确定性）。
`.env` 已被 `.gitignore` 排除，**请勿提交密钥**。

## 4. 使用

所有命令都在 `event-timeline-research/` 目录下执行（已激活 venv）。

### 4.1 作为 MCP 服务启动

```bash
# stdio（默认，供 Agent / langchain-mcp-adapters 拉起）
PYTHONPATH=src python -m mcp_server
# Windows PowerShell: $env:PYTHONPATH="src"; python -m mcp_server

# streamable-http
PYTHONPATH=src python -m mcp_server --http 127.0.0.1:8000
```

工具签名：

```python
product_timeline_research(
    brand, product,
    aspects=None,          # product/competitor/policy/tech/public，缺省全部
    time_from=None,        # YYYY-MM-DD
    time_to=None,          # YYYY-MM-DD
    domain_hint=None,      # 领域提示，如 "汽车"
    official_domains=None, # 品牌官方域名列表，自动定为 T1
) -> {"status": ..., "event_count": ..., "output_path": ..., "time_window": ...}
```

### 4.2 端到端验证（推荐首次运行）

```bash
python scripts/verify_research_tool.py
# 或手工指定时间窗，不依赖语料
python scripts/verify_research_tool.py --time-from 2024-03-01 --time-to 2026-10-03
```

脚本会：读语料 `created_at` 推断时间窗 → stdio 拉起 MCP → `tools/list` → 实调一次调研 →
校验「返回值不含完整事件列表」「落盘字段完整」「事件按日期升序」「全部事件权威分 ≥ 50 且在时间窗内」。

### 4.3 Python 直接调用

```python
import sys; sys.path.insert(0, "src")
from mcp_server import core, storage

timeline = core.run(brand="小米", product="SU7",
                    time_from="2024-03-01", time_to="2026-10-03", domain_hint="汽车")
path = storage.save_timeline(timeline)     # outputs/research/小米_SU7_timeline.json(+ .txt)
print(len(timeline["events"]), timeline["meta"]["filter_stats"])
```

### 4.4 分析与评估脚本

```bash
python scripts/analyze_resonance.py                    # 事件-评论共鸣（需 LLM + 语料）
python scripts/eval_influence.py                       # 价值层评估：伪事件对照 + 波峰对齐基线
python scripts/make_judge_calibration.py --build       # 构建判定员校准集
python scripts/make_judge_calibration.py --score       # 合并标注并出报告/复核清单
```

三者默认读 `outputs/research/小米_SU7_timeline.json` 与 `data/` 下的清洗语料，
均可用 `--events` / `--corpus` 换成自己的输入。

### 4.5 测试

```bash
python -m pytest tests -q     # 全部离线（httpx / 检索 / 向量 / LLM 均 mock）
```

## 5. 产出与评估口径

见 [`docs/outputs.md`](docs/outputs.md)。要点：

- `outputs/research/小米_SU7_timeline.json`：工具原始产出（schema v2，69 事件，时间窗 2022-10-28~2026-10-03）；
- `outputs/research/小米_SU7_timeline_v2.json`：人工精修事件轴（schema v4，83 事件，含 `tool_refs` 回指 v1）；
- `outputs/eval/tool_quality_eval.json`：对 41 个金标事件，**关键事件召回 11/15 = 73.3%**、
  事件精确率 56/69 = 81.2%、事实精确率 97.1%（**捏造 0**）；
- `outputs/eval/influence_eval.json`：放大倍数检验 p=0.303、波峰对齐命中率 66.7% vs 纪元随机基线 62.3%，
  结论为 `trivial_or_inconclusive` —— **事件对评论量的解释力目前未被证实**，这是诚实的负结论，勿当作正相关证据使用。

## 6. 数据说明

`data/` 下随仓库发布 1 份清洗语料（约 45 MB，汽车之家 小米SU7 论坛帖子），仅包含分析脚本所需的
`post_id / created_at / clean_text / text_content / title` 等列，详见 [`data/README.md`](data/README.md)。
语料仅用于学术研究与方法验证，不用于任何商业用途。

## 7. 设计文档

`docs/openspec/` 为该工具的完整设计工件（SDD 流程产物）：

- `proposal.md` — 为什么做、做什么、**不做什么**
- `design.md` — 技术选型与 ADR（含检索策略、聚类、LLM 降级、权威性等决策记录）
- `specs/product-timeline-research/spec.md` — 需求与验收场景（WHEN/THEN）
- `tasks.md` — 实施清单与验收标准

## 8. 常见问题

| 现象 | 原因与处理 |
|---|---|
| 返回 `config_error` | `.env` 缺 `VOLCENGINE_SEARCH_API_KEY`（或 key 无效/401）。检查 `.env` 位置是否在**本目录**下 |
| 事件很少 / `status=empty` | 时间窗过窄或查询被过滤。放宽时间窗，或用 `domain_hint`/`official_domains` 增强 |
| `llm_used=false` | LLM 三项配置缺失或服务不可用，工具已降级为原句摘要，属预期行为 |
| `ModuleNotFoundError: mcp_server` | 未设置 `PYTHONPATH=src`（测试由 `tests/conftest.py` 自动处理，MCP 启动需手工设置） |

## 火山引擎适配与本地部署（2026-10-11）

使用 [官方融合信息搜索 API](https://www.volcengine.com/docs/85508/1650263) 的 API Key 接入：POST https://open.feedcoopapi.com/search_api/web_search，Authorization: Bearer。不使用控制台网页地址作为 API，也不使用 AK/SK 签名接入。

Query/Count 对应搜索词与条数，时间窗映射到 TimeRange，域名限制映射到 Filter.Sites。Content 优先，缺失时使用 Snippet；模型生成的 Summary 不作为原文。PublishTime 保留原值并归一化为日精度。RankScore/AuthInfoLevel 仅保存供审计，不换算为现有 authority/confidence。

单客户端以0.65秒启动间隔限制请求，单查询失败记入 query_stats；全部失败为 search_error，部分失败为 partial。无结果的正常搜索才是 empty。该限速只覆盖单进程，多进程共享账号须另分配预算。时间窗过滤是发文时间过滤，不能证明它就是事件发生时间。

Windows 本地启动（在本目录）：

```powershell
.\scripts\start-local.ps1
# MCP HTTP 地址：http://127.0.0.1:8878/mcp
```

MCP 地址用于客户端连接，不是交互网页。适配不重跑或覆盖仓库旧版研究数据；旧 Tavily 评估结果不代表新搜索服务质量。

本地验证：`.\.venv\Scripts\python.exe -X utf8 scripts/smoke-local.py`（真实搜索，会消耗配额）。本地服务产物位于`.local/research`；停止服务时核对端口所属进程后结束本工具进程。重启用`start-local.ps1`，不重复启动已监听的端口。

## 本地网页工作台

执行 `.\scripts\start-all.ps1` 启动网页与MCP（已有本工具实例会复用，端口被其他程序占用则报错）。浏览器打开 http://127.0.0.1:8879/ 。仅启动网页可用 start-web.ps1，MCP入口仍在8878。

网页支持品牌/产品/起止日期/主题/官方域名输入、后台调研、搜索进度、历史任务、事件与来源查看、结果搜索及JSON/TXT下载。一次只运行一个网页任务，任务与结果逐次保存在.local/web-jobs/<任务ID>/，不覆盖旧研究数据。服务重启后未完成的记录显示中断，不会伪装完成或自动重跑。

搜索直接使用本机火山引擎搜索API凭据。摘要模型和embedding配置状态在页面顶部显示；未配置时分别使用原句回退和本地字符向量。未配置模型时也不执行LLM成员级去噪，需人工复核来源与聚类。此网页不执行评论共鸣/影响力评估脚本，这些是独立分析步骤，需要语料与模型，仍可按上文命令运行。

同一账号的MCP和网页共享供应商配额，但进程限速独立；避免同时启动两种入口的大调研。服务只监听127.0.0.1，任务输入使用同源保护，不公开到局域网。

## Windows 一键部署（推荐）

前提：已安装 Python 3.11+，首次安装依赖需联网。本轮实际验证环境为 Windows / Python 3.11及3.12；requirements-lock.txt 固定了验证过的依赖版本。

1. 从本仓库下载包含本功能的分支ZIP并解压，或克隆该分支。
2. 在 event-timeline-research 文件夹双击 deploy.cmd。
3. 等待独立虚拟环境与依赖安装，部署脚本会启动网页和MCP、完成协议健康检查，再自动打开网页。

已有服务会被复用；端口被其他程序占用时明确报错，不结束其他程序。重复部署保留.env、调研历史和结果。安装失败可再次运行，成功安装后按依赖文件hash跳过重复安装。deploy.cmd的执行策略只作用于启动它的PowerShell进程，不修改系统策略。

### 首次配置API

部署脚本自动创建.env模板，不填入或上传任何人的密钥。已有VOLCENGINE_SEARCH_API_KEY或ASK_ECHO_SEARCH_INFINITY_API_KEY环境变量可直接复用。没有凭据时网页仍能启动，并显示“搜索未配置”；编辑.env填入自己的搜索API Key，然后执行 `.\scripts\stop-all.ps1` 和 `.\deploy.cmd` 重启本工具服务。LLM和embedding继续可选，未配置时如实回退。

### 命令行与自定义端口

```powershell
# 在event-timeline-research目录执行；默认自动打开浏览器
.\deploy.cmd
# 自定义端口，不自动打开浏览器
.\deploy.cmd -McpPort 8888 -WebPort 8889 -NoBrowser
# 仅健康检查，不执行付费搜索
.\.venv\Scripts\python.exe -X utf8 scripts/check-local.py
```

安装与健康检查不运行真实调研、不调用LLM。部署是本机运行，不自动注册开机启动、不公开网络端口。当前功能在PR对应分支，main需合并后才含此入口。

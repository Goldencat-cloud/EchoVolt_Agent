# pipeline — 离线数据处理 + 在线服务

EchoVolt_Agent 的三大包之一。权威架构说明见 [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)。

```
pipeline/
├── 01_ingestion     采集
├── 02_cleaning      清洗
├── 03_media         历史多模态理解产物 + 复分析
├── 04_extraction    信息抽取
├── 05_normalization 实体归一
├── 06_reporting     agent-kb：唯一报告生成与发布
├── 09_industry_kb   行业政策/术语语料
├── service/         在线语义分析与 Agent 服务（唯一常驻进程）
├── data/            数据区（stock / published / runtime / live-acceptance）
└── tools/           质量门禁
```

## 数据位置（不能混淆）

- `data/stock/db/ingestion.sqlite3`：唯一采集库。含 SU7 9,994 帖（legacy-4）+ 竞品
  32,993 帖（legacy-3），共 42,987 帖、5,355 用户。不是在线新爬的帖子。
- `data/published/semantic.db`：唯一发布库，由 `service` 的 `semantic.build` 确定性重建，
  服务只读。当前 `fct_claim` 及以上仍为 SU7-only（竞品抽取待授权）。
- `data/live-acceptance/`：live 真实测试验收库与响应证据块（历史实验证据，只读）。
- `data/runtime/`：重跑产物落盘区，不进 Git。
- 各阶段 `results/`：中间产物，留在阶段内。

> 新增 127 帖已从 stock 标准 posts 表排除（用于溯源）；V2.3 分析输入是历史 9,701 帖
> 集合（9,529 通过 / 172 失败），与 stock 的 9,994 帖不是同一集合，禁止按数量直接拼接。

## 常用命令

```bash
# 清洗（例）
python 02_cleaning/tools/run_cleaning.py --db data/stock/db/ingestion.sqlite3 [--dry-run]

# 重建发布库
cd service && python -m semantic.build

# 数据新鲜度门禁
python tools/quality_gate.py --check semantic-freshness
```

## 测试

```bash
cd service && python -m pytest tests                        # 服务（485 用例）
cd 01_ingestion && $env:PYTHONPATH='src'; python -m pytest tests   # 采集（114）
cd 02_cleaning && python -m pytest tests                     # 清洗
```

## 数据与合规

仓库包含论坛原文和用户资料，**仅限受控私有仓库**；不要公开、发布为网站或转成公开
Release。密钥（settings/.env/API key/Cookie/学校凭证）不入库，模型抽取需独立授权。
图片原件与模型权重未纳入，无法只靠本包重跑完整图片链。

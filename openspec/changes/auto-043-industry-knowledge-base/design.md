# Design

## Context

动机见 `proposal.md` - Why。本节只记录影响实现方式的现状约束。

**已验证的现状（读代码与产物得到）：**

- `08_semantic_services` 没有外部证据层。工具清单 `kernel/registry.py:31-43` 共 8 项，能力标签 `read/compute/plan/submit` 四类；`kernel/profile.py:58` 的 `INTERACTIVE` 用 `tools_for({READ, COMPUTE, PLAN})`，`DELIVERABLE` 用 `tools_for(VALID_CAPABILITIES)`。**因此新增能力标签会自动扩大 `DELIVERABLE` 的权限**，这是接入必须处理的副作用。
- `report_source.py:94-113/140-149/162-175` 已有"按标题切片 → 带 id 注入 → 引用校验"三元组，`agent_tools.py:844-886` 已有中文 2-gram 打分，`research/embeddings.py` 已有批量向量、落盘缓存与失败降级。
- 08 依赖方向是单向的：HTTP/Agent/MCP → 研究语义 → 报告用例。09 若被 08 import，会打破该方向。
- 存储统一为 SQLite 只读连接（`semantic/adapters/records.py:45-60` 的 `mode=ro`），仓库内**没有任何 FTS5 虚拟表**。
- `report_gate.py` 的校验是文本级：`CORE_SECTIONS`、`INTERNAL_TERMS`、`_DECLARATION_MARKERS`、数字溯源匹配；没有引用来源校验的位置。
- 07 的设计结论是"全上下文优先，超 60K 字符才引入检索"（`pipeline.py:26,70-73`）。

**并行约束：** `auto-039` 正在改 `semantic/` 与 `research/`；`auto-042` 正在整合 `kernel/` 与 `report_gate.py` 周边。本变更新增文件为主，接线必须排在两者之后或与之协调单一写者。

## Goals / Non-Goals

**Goals:**

- 交付一个可离线构建、可审计、零新增运行时依赖的外部知识库模块，运行期只读。
- 让"知识库没有这条信息"成为可表达的确定结果，而不是模型的自由补全。
- 外部引用在报告中可机器校验，且与内部数字锚点不混淆。

**Non-Goals:**

- 不做运行期联网、不做自动增量采集、不做爬虫。
- 不做向量数据库、不引入 faiss/chroma/langchain-retriever。
- 不做外部知识与内部指标的口径融合；不产出竞品评分。
- 不在本变更内替换 `terminology.py`（术语来源切换留到独立变更）。

## Decisions

### D1 双层存储：文档表 + 事实表，事实不进检索语料

`document`/`chunk` 存术语与政策解读，走全文召回；`fact` 存参数与政策条款，字段级、带单位与批次，按结构化条件查询。

- 理由：检索片段一旦同时承载"数字"和"叙述"，模型极易把片段里的数字当统计来源引用；事实字段化后，数字必须经 `facts` 通道返回并自带单位与批次。
- 备选一：全部做成 Markdown 全文，靠模型抽取。放弃——无法保证单位、批次与去重。
- 备选二：全部结构化。放弃——术语定义与政策解释无法字段化，且会把解读权交给检索排序。

### D2 SQLite + FTS5 三元组召回，向量为可选增强

主召回用 SQLite `FTS5` 的 `trigram` 分词（对中文无需外部分词器），配置 `AI_EMBEDDING_MODEL` 时叠加 `research/embeddings.py` 的向量分，未配置或失败则退回关键词并在 `warnings` 标注。

- 理由：中文双字/三元切分已在 `search_published_report` 验证有效；引入分词器（jieba 等）会新增依赖。
- 备选：复用 07 的全上下文方案。放弃——数十条条目 × 数 K 字会直接撞上 60K 预算，且无法回答"哪条不成立"。
- 约束：FTS5 可用性依赖 Python 内置 SQLite 编译选项，需在构建期探测并在不可用时退化为 Python 端打分（与现有 `search_published_report` 同构）。

### D3 独立能力标签 `external`，并把 `DELIVERABLE` 改为显式集合

新增 `CAP_EXTERNAL`，`search_industry_kb` 只挂该标签；同时把 `DELIVERABLE.tools` 从 `VALID_CAPABILITIES` 展开改为显式列举的类别集合。

- 理由：现写法下任何新增类别都会静默进入交付链路；显式列举让"新能力需要 Owner 决定"变成构造期行为。
- 影响：`profile.py` 有一处结构性改动，与 `auto-042` 可能同文件冲突，须协调写者。

### D4 引用命名空间 `kb-`，门禁在 08 侧校验语法

引用形如 `[KB-<doc_id>#<chunk_idx>]`；`report_source` 的 `sections_from_markdown` 已支持 `prefix` 参数，09 侧直接传 `kb-` 即可，无需改 08 的切片代码。门禁只做前缀与存在性校验，不反向依赖 09。

- 理由：保持依赖单向——09 独立，08 只知道引用语法。
- 备选：让 09 import 08 的 `report_source`。放弃——会把外部知识模块绑到语义服务上，且 08 正在被多个变更修改。
- 切片实现：09 自带一份按标题切分与 id 生成，格式与 08 对齐并由契约测试锁定。

### D5 时效以 `as_of` + `status` 双轨判定

政策与参数记录 `effective_from`/`effective_to`/`status`；检索默认 `as_of=now` 且过滤失效项，显式 `as_of` 时按历史效力返回并标注替代关系。

- 理由：工信部目录已到第三十三批（2026-08），政策是批次化高频更新，缺时效会产生"过期但看似权威"的答案。
- 备选：只存最新版。放弃——无法解释"当时为什么这样"，也无法审计旧报告。

### D6 采集离线、语料入库即可评审

首批语料为人工整理的 Markdown/JSONL（源文件约 22 份，入库以条目计），来源 URL 与获取日期写在前置元数据中；构建只做解析、校验与索引，不做网络访问。

- 理由：`external_events` 的实测显示检索式采集的主要问题是来源污染（聚类纯度 68.6%、站点首页与 FAQ 页混入），人工种子把清洗前移到入库环节。
- 后续：半自动采集另立变更，复用 `modules/external_events` 的域名分级与黑名单，但仍须落盘人工复核。

### D7 冲突裁决在两处落地

检索响应并列呈现内外部来源并标注"不可直接比较"；报告门禁要求外部断言带引用、发布方与日期，冲突必须出现在「限制与不确定性」。

- 理由：只在 Prompt 里写规则无法验证；只有在响应结构与门禁两处同时约束，才能被测试覆盖。

## 接口契约

**检索工具（供 `@tool` 与 MCP 共用同一实现）**

```
search_industry_kb(question, categories=None, as_of=None, top_k=5)
→ {
    chunks: [{kb_id, doc_id, title, text, snippet, publisher, publish_date, source_tier, url}],
    facts:  [{kb_id, field, value, unit, vehicle_model, batch, effective_from, effective_to, publisher, url}],
    coverage: {categories, source_count, date_range, insufficient_scope?},
    warnings: [{code, detail}],      # keyword_only / embedding_failed / stale_excluded
    citations: [kb_id, ...],
    data_version: {version, built_at, counts}
  }
```

**知识库 schema（`kb.sqlite3`）**

- `document(doc_id, title, category, publisher, source_url, publish_date, retrieved_date, source_tier, license, effective_from, effective_to, status, content_hash)`
- `chunk(chunk_id, doc_id, ordinal, heading, text, token_count)`
- `chunk_fts`（FTS5 external content，trigram）
- `fact(fact_id, category, vehicle_model, field, value, unit, batch, effective_from, effective_to, status, source_id)`
- `meta(key, value)`（版本、构建时间、语料哈希）

**错误码**：`unknown_category` / `out_of_scope` / `invalid_as_of` / `kb_unavailable`。全部返回结构化错误，不抛裸异常给模型。

## 文件所有权与并行处理

| 范围 | 文件 | 写者 |
| --- | --- | --- |
| 新增（09） | `09_industry_kb/**`、`domains/automotive/**` | 本变更 |
| 接线（08） | `kernel/registry.py`、`kernel/profile.py` | 本变更，须与 `auto-042` 协调 |
| 接线（08） | `agent_tools.py`、`report_gate.py`、`integrations/mcp_server.py` | 本变更，须与 `auto-039`/`auto-042` 协调 |
| 只读 | `04/05/06` 产物、`semantic/model.yaml` | 不修改 |

冲突处理：接线任务在 tasks 中单列为最后阶段，并标注"待 `auto-039`、`auto-042` 交付后由 Owner 决定顺序"；同一物理文件同一时间只有一个写者。

## Risks / Trade-offs

- [只有官方来源导致覆盖面窄，用户会认为"知识库没用"] → 在 `coverage` 与 Agent 回答中显式声明可回答范围，并把常见不可答问题（价格、智驾配置、车型级销量）写入语料清单文档。
- [工信部附件为 `.doc`，解析稳定性差] → 首批只人工录入 5 组车型的可证字段并逐行核对；解析脚本先做"行数 + 字段完整性"断言，失败即拒绝构建。
- [FTS5 trigram 在部分 Windows Python 构建不可用] → 构建期探测，退化到 Python 端 2-gram 打分；两者的返回结构一致，测试用例覆盖两条路径。
- [新增能力类别改动 `profile.py` 与 `auto-042` 冲突] → 接线阶段前置，先合并 `auto-042`；若冲突，以能力显式化为准并重跑 profile 构造期校验。
- [外部参数被误读为内部统计] → 渲染层强制来源标注 + 门禁拒收无引用外部数值；回归用例专门覆盖"外部值与内部值同名不同口径"。
- [知识库内容过期无人维护] → `data-version.json` 暴露构建时间；报告中引用外部条目时必须带发布日，且超过有效期的条目默认不进入检索。

## Migration Plan

1. 冷启动：新增模块与语料，产出 `kb.sqlite3`；此时 08 完全不知道它存在，零影响。
2. 接线：`registry.py` 登记 + `profile.py` 显式化能力集合，工具随装配生效；未登记则不暴露。
3. 门禁：`report_gate.py` 增加 KB 引用校验；此时旧报告不含 KB 引用，校验不触发。
4. 回滚：移除 `registry.TOOLS` 登记即整体失效；知识库数据文件可独立删除，不影响内部数据与已有报告。

## Open Questions

- 中文分词是否需要额外增强（同义词、车型别名归一）待首批语料实测召回后再定，不改变接口。
- 术语条目与 `terminology.py` 的合并时点，取决于后续是否统一术语出口，可在独立变更中决定。

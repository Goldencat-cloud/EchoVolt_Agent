# SU7 论坛需求分析报告 · 离线初版

本版直接复用现有方面、情感、产品映射和证据。没有增加 Agent 算子、主题模型、embedding 或模型 API 请求。主题模型依赖准备曾启动，后中止；该路径不是报告依赖。没有改写 AUTO-016 抽取或 AUTO-018 V2 原始交付。

## 阅读入口

- 本地报告：http://127.0.0.1:8874/ 。页面支持原文展开、案例方面筛选、精确计数与来源查看。
- `SU7需求分析报告.md`：与页面同源的文本和精确表格伴随件。
- `app/src/data.json`：报告绑定的 7 组数据、来源、口径及 11 个案例。
- `analysis/aspect-sentiment.csv`：方面／情感计数。
- `analysis/scope.json`、`scoped-mentions.jsonl`：临时重点产品范围视图及逐提及范围状态；旧映射保留，不重造长尾节点。
- `analysis/summary.json`、`profiles.json`、`reviewed-cases.json`：筛选集合、完整方面分布与定向复核案例。
- `analysis/input-manifest.json`：原数据、映射、元数据及 9,529 份冻结原文的 SHA256。
- `analysis/verification.json`：12 项计算／来源检查，含从原始 Claims 独立重算 3,356 条／1,810 帖及 131 条舒适性负面表达。

## 解释边界

表达数不是人数；负面表达占比不是满意度。当前拥有是帖子级模型标签，不独立证明持有 SU7。比较 Claim 排除的是已经抽取出的 comparison；模型遗漏的比较仍可能存在。11 个案例是 Codex 定向阅读 10 帖后的分析，不是人类验收或随机语义准确率测量。案例中明确区分租车、试驾、作者声称与分析推导。历史数据不证明现行规格、服务网点或权益。

统计使用既有 aspect 方面分类。源 Claim 没有独立已规范化的细粒度 attribute 字段；案例细节来自原文，不冒充全量细粒度标签。

## 复现与文件边界

`analyze.py` 使用 Python 标准库运行，输出目录 `analysis/` 必须不存在；不要删除现有输出来覆盖复现。复现应复制脚本到独立版本目录并确认其 ROOT 与输入路径，或人工改用新的明确输出路径。`compose.py` 从分析结果组装快照；已生成 app 的 ID 必须保持不变，不要重新准备覆盖。`verify.py` 检查报告数据并从当前 authored prose 导出 Markdown。

```powershell
python collaboration/result/auto018-product-entity-normalization/report-v1/verify.py
python -m http.server 8874 --bind 127.0.0.1 --directory collaboration/result/auto018-product-entity-normalization/report-v1/app/dist
```

报告采用共享 Data app 的本地预编译运行时。构建与便携单文件导出使用已安装 Data 插件的 `scripts/data-app.mjs build --separate-data` 与 `export-offline`。不安装 npm 依赖、不调用外部 CDN、不公开发布数据。

本轮没有业务服务改动、Git 提交、PR、合并或正式人类交付验收。AUTO-019 算子 Change 只有中断前创建的骨架，未实施；它不是本报告运行依赖。

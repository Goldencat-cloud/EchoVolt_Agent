# 报告问答模块

基于 auto-023 双投影报告的离线问答。**全上下文模式**：报告 `report.md` 仅约 8K 字符（≈10K token），整份进入 LLM 上下文——不检索、召回 100%，拒答清单 [R] 与回答模板 [T] 天然在场。回答由流水线保证：引用锚点校验 + 数据版本声明追加；命中拒答清单的问题被明确拒绝。架构与消费的数据接缝由 auto-024 Change 治理。

## 运行

实测解释器 CPython 3.13（要求 ≥3.11）；仅依赖 Python 标准库。

```powershell
python run.py diag                                   # 知识库诊断（规模/锚点/版本）
python run.py ask "舒适性负面声量占比是多少" --no-llm  # 无 LLM：仅诊断，不调用外部服务
python run.py ask "舒适性负面声量占比是多少"           # LLM 模式（需配置）
python tests/test_pipeline.py                        # 确定性单元测试（9 项）
```

## LLM 配置

优先读环境变量 `REPORT_KB_LLM_BASE_URL` / `REPORT_KB_LLM_API_KEY` / `REPORT_KB_LLM_MODEL`；或复制 `configs/llm.example.json` 为 `configs/llm.json`（api_key_env 指向存放密钥的环境变量名，密钥本身不落仓库）。未配置时 ask 进入诊断模式，不调用外部服务。

## 行为保证

- 回答附锚点引用，锚点必须存在于报告（流水线校验，未知锚点告警）；
- 数据版本声明由流水线追加到每个回答（不依赖模型自觉）；
- 拒答清单 [R] 与回答模板 [T] 随全文在上下文中；
- LLM 调用失败返回错误码，不输出编造内容；
- 问答日志追加至 `output/qa-log.jsonl`。

## 何时引入检索

报告超过上下文预算（60K 字符）时 `ask` 显式报错 `context_budget_exceeded`。届时引入成熟方案（LLM 服务商 embeddings API 或标准检索框架），不恢复自建检索器——演进路径见 `docs/design-notes.md`。

## 边界

- 不修改 `06_reporting/agent-kb/` 的任何产物（只读消费 report.md / data-version.json）。
- 不做明细即时查询与联网采集分析（Owner 指示，见 auto-024 proposal）。

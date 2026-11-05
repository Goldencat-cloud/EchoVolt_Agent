# auto-024-report-qa-rag

## Why

第一阶段（Owner 2026-10-22 确认）：用户接入数据 → 平台自动产出报告 → **基于 LLM 的报告离线问答**。auto-023 已交付双投影报告（人类版 HTML + 机器可读 MD `report.md`，含 [K] 数字速查、[D] 口径、[R] 拒答清单、[T] 回答模板）。本 Change 在其上实现问答：整份报告进入 LLM 上下文 → 按行为约束生成带引用的回答。明细即时查询与联网采集分析明确不在范围。

## What Changes

- 新模块 `offline_analysis_pipeline/07_qa_agent/`（对齐 01/02 模块约定：src 包 + configs + docs + run.py + pyproject + tests）：
  - **全上下文问答**（Owner 2026-10-22 确认，不做自建检索）：report.md 仅约 8K 字符，整份报告直接进入 LLM 上下文——召回 100%、零检索代码、拒答清单 [R] 与模板 [T] 天然在场；超过上下文预算（60K 字符）时显式报错并提示引入成熟检索方案，不静默截断；
  - **生成**：可插拔 LLM 客户端（OpenAI 兼容 chat/completions，stdlib urllib；base_url/model/api_key 经环境变量或 configs/llm.json 配置）；未配置时提供诊断模式（报告规模/锚点/版本）；
  - **行为约束**：回答附锚点引用（流水线校验未知锚点）、数据版本声明由流水线追加、命中拒答清单（[R]）即拒绝；
  - **CLI**：`python run.py ask "问题" [--no-llm] | diag`；确定性单元测试 `tests/test_pipeline.py`。
- 纯文档/工具 Change，不改管线代码与数据；报告数据接缝（numbers.json）不做任何修改。

## Scope

**范围内**：上述问答模块与生成链路；回答的确定性保证（引用锚点必须存在于报告、版本声明必须由流水线在场）。

**范围外**：明细即时查询（Owner 指示移出）；联网采集分析；Web 服务界面与多轮对话；自动产出报告流水线（第二阶段）；自建检索器（报告超预算时引入成熟方案：LLM 服务商 embeddings 或标准检索框架）。

## Capabilities

### Added
- `report-qa`：基于报告的离线问答契约——全上下文优先、拒答与引用约束、可插拔 LLM、无 LLM 诊断模式。

### Modified
- 无。

## Impact

- 消费 auto-023 的 `output/report.md` 与 `data-version.json`（只读）；auto-023 未合并前，本 Change 分支基于其分支创建，交付时按 Owner 决定 PR 拆分方式。
- LLM 依赖为运行期外部服务：仓库内不落任何密钥，配置经环境变量；无密钥环境以诊断模式运行并通过确定性校验。
- reviewed_commit：null（工件新建，随实现一同提交）。

# Spec Delta

## Purpose

定义基于报告的离线问答契约：全上下文优先（整份报告进 LLM 上下文，不检索）、行为约束（引用/版本声明/拒答）、可插拔 LLM。检索仅作为知识库规模超出上下文预算时的未来升级点，当前 MUST NOT 引入自建检索。

## ADDED Requirements

### Requirement: 全上下文优先
报告当前规模（约 8K 字符）SHALL 以整份报告进入 LLM 上下文的方式问答（full-context），MUST NOT 引入自建检索器；[R]（拒答清单）与 [T]（回答模板）随全文天然在上下文中。仅当报告规模超过构建期设定的上下文字符预算（当前 60,000 字符）时，系统 SHALL 显式报错并提示引入成熟检索方案（如 LLM 服务商 embeddings + 标准向量检索），而非静默截断。

#### Scenario: 报告规模内问答
- **WHEN** 报告不超过上下文预算时提问
- **THEN** 整份报告作为上下文送入 LLM，拒答清单与回答模板天然在场

#### Scenario: 规模超限显式失败
- **WHEN** 报告超过上下文预算
- **THEN** 返回 context_budget_exceeded 错误并提示升级路径，不静默截断报告

### Requirement: 行为约束（引用、版本声明、拒答）
回答 SHALL 附引用锚点且锚点必须存在于报告（流水线校验，未知锚点须告警）；每个回答 SHALL 由流水线追加数据版本声明，不依赖模型自觉；命中拒答清单（[R]）的问题 SHALL 被拒绝并引用对应条目，MUST NOT 编造报告不支持的内容。

#### Scenario: 拒答
- **WHEN** 用户询问"SU7 车主满意率是多少"
- **THEN** 回答拒绝并引用 [R1] 的理由，不输出任何满意率数字

#### Scenario: 引用与版本声明
- **WHEN** 回答包含统计数字
- **THEN** 回答附锚点引用；回答末尾由流水线追加数据版本/截止时间声明

### Requirement: 可插拔 LLM 与无 LLM 退化
LLM 客户端 SHALL 可配置（OpenAI 兼容接口，base_url/model/api_key 经环境变量或 configs/llm.json 指定），MUST 不在仓库内存储密钥。未配置 LLM 时 SHALL 提供诊断模式（报告规模、锚点清单、版本声明）而非调用外部服务；LLM 调用失败 SHALL 返回明确错误码，MUST NOT 输出编造内容。

#### Scenario: 无密钥环境
- **WHEN** 未配置 LLM 环境变量时执行 ask --no-llm 或 diag
- **THEN** 返回诊断信息（报告规模/锚点/版本），不调用任何外部服务

#### Scenario: LLM 故障
- **WHEN** LLM 接口调用失败或超时
- **THEN** 返回明确错误码，MUST NOT 输出编造内容

# Spec Delta

## Purpose

定义 AutoInsight 对外暴露的 HTTP 端点集合与各端点职责边界，使调用方能够依据端点判断响应形态，也避免同一问题存在两条能力不同、口径不同的回答路径。

## ADDED Requirements

### Requirement: 端点集合是封闭且明确的

系统 SHALL 仅暴露以下业务端点：`/api/question`（对话问答）、`/api/ask`（已发布报告问答）、`/api/agent/report`（深度分析任务）、`/api/health`（健康检查），以及其已文档化的附属查询端点。

#### Scenario: 已移除端点返回 404

- **WHEN** 客户端向 `/api/analyze` 发起请求
- **THEN** 系统返回 HTTP 404，不落入其他处理器，也不返回任何统计结果

#### Scenario: 未知路径不匹配任何处理器

- **WHEN** 客户端请求未列出的路径
- **THEN** 系统返回 HTTP 404

### Requirement: 每个端点只有一个回答职责

系统 SHALL 保证同一类问题只由一个端点承担：一般性对话问答由 `/api/question` 承担；针对已发布报告的定向问答由 `/api/ask` 承担；需要产出新报告的请求由 `/api/agent/report` 承担。

#### Scenario: 对话请求走单一链路

- **WHEN** 用户在对话界面提交一个问题
- **THEN** 请求仅由 `/api/question` 处理，且该请求不得触发报告产出

#### Scenario: 报告问答不被对话端点分流

- **WHEN** 客户端在请求中显式引用某份已发布报告
- **THEN** 该请求由 `/api/ask` 处理，并返回带引用锚点的回答

### Requirement: 端点移除时给出明确失败

系统 SHALL 对被移除端点保留可诊断的失败语义，而非静默返回空结果。

#### Scenario: 已移除端点不降级为其他能力

- **WHEN** 旧调用方向 `/api/analyze` 发送问题
- **THEN** 系统既不执行统计查询，也不生成回答，只返回 404

### Requirement: 健康检查独立于业务状态

系统 SHALL 提供 `/api/health`，其可用性不得依赖模型服务或数据快照是否就绪。

#### Scenario: 模型不可用时健康检查仍可用

- **WHEN** 模型凭证未配置
- **THEN** `/api/health` 返回成功状态，业务端点按各自约定返回显式错误

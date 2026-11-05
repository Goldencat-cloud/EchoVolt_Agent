# Tasks

## 1. 语义层底座

- [x] 1.1 `db_mirror.py`：SQLite 镜像（原始表私有 + `semantic_*` 视图 + meta），可重建、不入库
- [x] 1.2 `analysis_methods.py`：白名单方法库（9 种预置分析）+ 参数校验 + 语义关系白名单强制
- [x] 1.3 `verifier.py`：口径声明 / negativeShare 复算 / 快照对账 / 精选计数 / 空值与薄样本

## 2. 深度分析 Agent

- [x] 2.1 `sandbox.py`：代码解释器沙箱（AST 拦截 + 子进程 + pandas I/O 封禁 + 超时/截断）
- [x] 2.2 `agent_tools.py`：五工具（探索/方法/代码/证据/提交），工具错误回传自愈
- [x] 2.3 `agent_engine.py`：DeepAgents + 提交契约 + 分析日志
- [x] 2.4 `POST /api/agent/report`（异步任务化：202 返回 job_id，进度经轮询查询）

## 2A. Owner 迭代（2026-10-25）：工作流外置、提速、进度、失败显性化

- [x] 2A.1 四阶段工作流从 prompt 下沉到 `agent_skills/deep-analysis/SKILL.md`，经 DeepAgents SkillsMiddleware 以渐进披露方式承载；prompt 只保留角色与红线
- [x] 2A.2 提速：工作流预注入 overview 与基准统计（省去探索轮次），recursion_limit 50，模型 max_retries=2——实测由 ~64s 降至 ~35s 量级
- [x] 2A.3 失败预算化：工具错误回传但设全局预算（6 次），同段代码失败 3 次即拒绝重试并要求换路（防"无限修正循环烧钱"事故）
- [x] 2A.4 进度与监控：`jobs.py` 异步任务 + 阶段事件（理解问题中→…→已完成/失败），前端轻量提示轮询，同一事件流即监控面
- [x] 2A.5 **失败显性化（Owner 指示）**：删除前端"深度失败自动回退确定性链路"逻辑；失败直接呈现错误与重试按钮；确定性端点保留但仅作显式调用
- [x] 2A.6 Docker 化交付：`Dockerfile` / `docker-compose.yml` / `requirements.txt` / `.dockerignore`（本机无 Docker，构建在具备 Docker 的环境执行）

## 3. 确定性回退

- [x] 3.1 `planner.py`：LLM 计划（JSON mode）+ 机械校验 + 规则回退
- [x] 3.2 `planned_report.py` + `POST /api/report/planned`；未过校验的步骤不进报告
- [x] 3.3 前端：深度 Agent 显示明确失败与重试；确定性管线仅由用户显式调用（按 Owner 2A.5 决策更新早期任务描述）

## 4. 验收

- [x] 4.1 57 项单元/接口测试 OK（`python -m unittest discover -s tests`）
- [x] 4.2 深度 Agent 实测：可靠性问题 → 64s、36 工具调用、报告含口径与代码聚合结论
- [ ] 4.3 Owner 浏览器验收：提问 → 深度报告渲染、分析日志展开、深度失败与显式确定性入口
- [ ] 4.4 沙箱容器化（Docker）与公网部署前安全评审（依赖 5.x）
- [ ] 4.5 统一对话 Agent：问候、含糊输入、感谢、数据问题、结果来源追问、报告检索、越界维度、证据不足及工具失败
- [ ] 4.6 在线分析 Agent：单维统计、多议题比较、跨用户阶段分析、代码解释器调用与沙箱拒绝场景；验证互动分析无需报告计划

# Tasks

## 1. 前置与基线

- [x] 1.1 由 Owner 停止 PID 54088（`0.0.0.0:8000`）与两个 `unittest discover` 进程，确认端口释放；验证：`Get-NetTCPConnection -LocalPort 8000` 无 `Listen` 记录
- [x] 1.2 确认 auto-041 已提交、当前工作区无跨范围改动后，从干净基线创建 `change/auto-042-architecture-consolidation`；验证：`git status --short` 无本 Change 范围外文件
- [x] 1.3 运行全量测试并记录基线（通过数、失败数、耗时）；验证：结果写入 `design.md` 的验证记录，作为后续对比基准
- [x] 1.4 修复 `tests.test_analysis_primitives` 的服务收尾缺陷（请求 `/api/analysis/options` 返回后进程不退出），使全量 `discover` 可结束；验证：该模块 4 秒内结束（`Ran 35 tests in 3.112s`）
- [x] 1.5 处置 `tests/test_analysis_primitives.py` 中针对已移除方法的过时测试（22 项失败，见 design 验证记录），使该模块全绿；验证：重写为语义聚合版本后 `Ran 32 tests ... OK`

## 2. 移除不可达的旧问答链

- [x] 2.1 删除 `app.py` 中的 `analyze_core` 与 `/api/analyze` 路由分支，使该路径返回 404；验证：`grep -n "analyze_core" app.py` 无结果，且新增用例断言 `POST /api/analyze` 返回 404
- [x] 2.2 处理依赖旧链辅助函数的用例（模型调用兜底、确定性回答）；验证：全量测试通过，无跳过或永久禁用
- [x] 2.3 从 `README.md`、`docs/` 与前端资源中移除 `/api/analyze` 引用；验证：`grep -rn "/api/analyze" README.md docs web` 无残留（变更记录除外）

## 3. 移除死代码与残留

- [x] 3.1 删除 `routing/intent.py`、其测试与根目录 `intent.py` shim；验证：`grep -rn "from routing import intent\|import intent"` 无结果，`tests/test_api.py` 中「不使用意图分类器」用例仍通过
- [x] 3.2 删除 `agent_engine.run_agent_report` 及全部调用点；验证：`grep -rn "run_agent_report"` 无结果
- [x] 3.3 移除 `live` 参数链（对话入口参数、`agent_tools` 中的空赋值与 `research.live_frames` 分支、相关提示词分支）；验证：`grep -rn "live_context\|live_frames"` 的剩余命中仅为 `RunContext` 兼容键说明，全量测试通过
- [x] 3.4 将 `CONVERSATION_EXCLUDED_TOOLS` 从生产代码迁为测试内对照常量；验证：`tests/test_kernel_wiring.py` 与 `tests/test_kernel_equivalence.py` 的等价性用例通过

## 4. 消除兼容 shim

- [x] 4.1 删除 `analysis_methods.py`、`service.py`、`research_catalog.py`、`mcp_server.py` 四个 shim，调用方改为显式包导入；验证：`grep -rn "sys.modules\[__name__\]" 08_semantic_services` 无结果
- [x] 4.2 同步修正测试与 `integrations/` 内的导入语句；验证：全量测试通过，`tests/test_mcp_server.py` 通过
- [x] 4.3 在 `README.md` 更新模块位置说明（`research/`、`semantic/`、`integrations/` 的真实路径）；验证：文档描述的路径在磁盘上存在

## 5. 装配收敛到唯一入口

- [x] 5.1 对话链改为经由 `kernel.builder.build_runner` 装配（无人工审批姿态）；验证：`grep -n "create_agent(" agent_engine.py` 无结果，`tests/test_kernel_wiring.py` 通过
- [x] 5.2 交付链改为经由同一装配器，`ReportSession` 持有 runner 以复用同一 checkpointer 实例；验证：`tests/test_outline_gate.py` 与 `tests/test_interrupt_gate_spike.py` 通过
- [x] 5.3 删除两处自建装配代码；验证：`grep -rn "create_deep_agent(\|create_agent(" --include=*.py` 仅命中 `kernel/builder.py`
- [x] 5.4 验证交付姿态下运行状态的 `interactive` 字段语义，给出保留或清除的结论；验证：结论写入 `design.md` 验证记录，并附对应用例

## 6. 容器构建一致性

- [x] 6.1 新增 `.dockerignore`（排除 `.venv`、`__pycache__`、`*.pyc`、`data/`、`reports/`、`*.log`、`_tmp_*`），`Dockerfile` 改为整体复制；验证：`docker build` 成功；若环境无 docker，则退化为脚本比对构建描述与磁盘文件的一致性并记录该限制
- [x] 6.2 启动镜像验证健康检查与服务可用；验证：`/api/health` 返回成功，`/api/analyze` 返回 404，`/api/question` 可返回回答
- [x] 6.3 确认最小权限运行设置未被削弱；验证：`docker-compose.yml` 的只读根、非特权用户、能力丢弃与提权禁止项保持存在

## 7. 约束机械可验证

- [x] 7.1 将装配唯一性断言的扫描范围扩至整个服务目录（排除 `builder.py`、`tests/`、`integrations/`）；验证：先在未清理代码上运行该断言应失败，清理后通过
- [x] 7.2 技能改为按姿态声明注入；验证：构造只声明入口技能的姿态，断言其 agent 无法发现其他技能；若框架不支持按名注入，记录限制并改为权限层限制
- [x] 7.3 为 `api-surface` 补齐端点集合用例（含已移除端点 404、未知路径 404）；验证：新增用例通过

## 8. 集成验证

- [x] 8.1 全量测试与四条端点端到端冒烟（对话、报告问答、深度分析至大纲暂停、健康检查）；验证：命令、环境与结果写入 `design.md` 验证记录
- [x] 8.2 补全验证记录并标明未覆盖项（仓库外调用方、容器内安全评审、`semantic/` 未改动带来的残留风险）；验证：验证记录无空项，未覆盖项逐条列明

## Workflow follow-up

- 由 Owner 指派、完成规格审查并记录审阅人、日期与结论（当前 pending）。
- 将 `proposal.md` 状态置为 `REVIEW_READY`，请求 GPT 与人类审查。
- 提交唯一交付 PR，说明 BREAKING 变更与迁移方式。
- 交付 PR 合并且 Owner 验收后，另立维护 Change 归档本变更并同步正式规格。

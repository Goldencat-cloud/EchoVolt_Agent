# Design

## Context

### 已验证事实（读码所得，2026-11-04）

| 事实 | 位置 |
|---|---|
| 前端唯一对话请求指向 `/api/question`，无 `/api/analyze` 调用 | `web/app.js:196` |
| 旧问答链 `analyze_core` 不经过 agent、工具或技能，为确定性统计 + 单次模型归纳 | `app.py:99-165` |
| `routing/intent.py` 在非测试代码中引用数为 0 | 全仓 grep |
| 测试已锁定「不使用意图分类器」 | `tests/test_api.py:145-155` |
| `kernel.build_runner` 与 `KernelRunner` 仅被测试引用，生产零调用 | `kernel/builder.py:46-54` |
| 对话链自建 agent | `agent_engine.py:254` |
| 交付链自建 agent（含 interrupt_on、checkpointer） | `report_session.py:85-96` |
| 交付链的装配与 `kernel/builder.py:87-95` 逐行近似 | 两处对比 |
| 五处 `sys.modules` shim | `analysis_methods.py`、`service.py`、`intent.py`、`research_catalog.py`、`mcp_server.py`（均为 3 行） |
| `CONVERSATION_EXCLUDED_TOOLS` 仅测试引用 | `agent_engine.py:43`；`tests/test_kernel_wiring.py:64`、`tests/test_kernel_equivalence.py:79` |
| `run_agent_report` 自注 `NOT for production`，循环自动批准大纲 | `agent_engine.py:190-211` |
| `live` 分支已硬编码为空，实时模块已由 auto-041 未提交改动删除 | `agent_tools.py:244-245`；git status 中 `research/live_*.py` 为 D |
| `db_mirror` 已迁移为 `semantic.adapters.compat_views` 的别名 | `sandbox.py:23`、`task_brief.py:25`、`research/analysis_methods.py:14` |
| 容器构建描述 COPY 了已不存在的 `db_mirror.py`、`intent.py`，且未包含 `kernel/`、`semantic/`、`research/`、`routing/`、`integrations/` | `Dockerfile:12-16` |
| 装配唯一性测试只扫描 `kernel/` 与 `routing/gates.py` | `tests/test_kernel_runner.py:112-122` |
| 运行中的服务监听 `0.0.0.0:8000`，PID 54088，2026-11-03 13:08 启动 | 进程与端口查询 |
| 两个 `unittest discover` 进程自 2026-11-04 12:54 起持续运行 | 进程查询 |

### 未验证事项（不得当作结论使用）

- 仓库外是否存在 `/api/analyze` 的调用方（脚本、文档示例、外部客户端）。
- `kernel.builder._deep_agent` 与 `report_session` 现有装配是否**逐项等价**：interrupt 配置、技能权限、checkpointer 初始化时机、`pinned_skills` 注入尚未逐行比对。
- 交付链当前以 `interactive=True` 构造运行状态（`report_session.py:82`）而姿态为 `deliverable`；该字段是否影响计划强制，未验证。
- PID 54088 的工作目录未直接取得，按端口与启动命令推断为本服务。

### 工作区状态（写入前必须知晓）

当前分支为 `change/auto-041-agent-report-kernel-wiring`，存在 23 项未提交改动（含 `db_mirror.py` 与 `research/live_*.py` 的删除）。本 Change 的新建分支必须基于 auto-041 完成或已提交的状态，否则会在同一批文件上产生冲突。

## Goals / Non-Goals

**Goals**

1. 每个行为只有一个实现：删除达到该目标的旧实现，而不是并存。
2. 装配、预算、工具集、技能集合只能由配置数据决定。
3. 容器构建描述与源码结构一致，可构建可启动。
4. 每条约束都有可机械验证的失败条件（源码断言或测试）。

**Non-Goals**

1. 不改 `semantic/` 包内部实现（Owner 裁定：先不管）。仅将其纳入镜像构建。
2. 不改工具的对外行为、提示词内容与报告门禁规则。
3. 不处置 `modules/experience_modeling`（其 MCP 服务正在运行）、`archive/legacy_pipeline`、`01`–`07` 流水线。
4. 不新增 agent 能力、不引入新依赖、不调整预算数值。
5. 不合并 `task_brief` 的任务简报与 `semantic_overview` 的数据目录（有意保留的前置注入与兜底关系）。

## Decisions

### D1 直接删除旧问答链，不保留转发层

**选择**：删除 `analyze_core` 与 `/api/analyze` 路由，`/api/analyze` 返回 404。

**理由**：仓库内无调用方；保留转发层会把「一条链两种回答形态」的问题从实现层挪到路由层，读者仍需理解两份语义。旧链的统计能力在 `/api/question` 的工具集中已完整覆盖。

**替代方案**：`/api/analyze` 307 重定向到 `/api/question`——被否。旧链只接受 `aspect` 维度并返回固定模板，与新链响应结构不同，重定向会造成静默的响应形状变化。

**兼容说明**：属破坏性变更，需在交付说明中明确；若 Owner 要求保留期间，可临时返回 410 并附迁移指引，由 tasks 中第 1 项决定。

### D2 装配收敛到 `kernel.builder.build_runner`

**选择**：`agent_engine` 与 `report_session` 均改为经由 `build_runner(profile, ctx)` 获得 agent；删除两处自建构造。`kernel.builder._deep_agent` 已具备 `interrupt_on` 与 `checkpointer` 能力，交付链直接复用。

**理由**：两处自建与 builder 逐行近似，差异只会随修改累积。`build_runner` 返回的 `Outcome` 三态（`done`/`awaiting_review`/`failed`）已覆盖等待审查的状态语义。

**风险**：交付链当前依赖 `pinned_skills`、`permissions`、`MemorySaver` 的实例复用（resume 必须复用同一 checkpointer 实例）。接线时必须保证 `ReportSession` 持有 runner 而非每次重建。

**替代方案**：保留两处自建、仅抽公共参数——被否。约束无法用源码断言守住。

### D3 删除 `sys.modules` shim，改显式包导入

**选择**：删除 5 个 shim；调用方改为 `from research import service`、`from semantic.adapters import compat_views` 等显式导入。

**理由**：shim 让静态分析、IDE 跳转、打包与容器构建都无法解析真实模块，这正是 `Dockerfile` 复制了「壳」却漏掉「芯」的直接原因。

**影响面**：所有 `import service` / `import analysis_methods` / `import research_catalog` / `import intent` / `import mcp_server` 的调用点与测试；需一次性机械替换。`intent` 的 shim 随 D4 一起删除。

**替代方案**：保留 shim 并在 Dockerfile 中补 COPY 真实包——被否，治标且继续遮蔽结构。

### D4 删除 `routing/intent.py` 与其 shim

**选择**：两者一并删除；`tests/test_intent.py` 同步删除，`tests/test_api.py` 中「不使用意图分类器」的用例保留。

**理由**：生产零引用，且该用例本身证明了设计上已放弃该组件——保留实现而保留「不使用它」的测试，是最容易误导后来者的组合。

### D5 `CONVERSATION_EXCLUDED_TOOLS` 降级为测试常量

**选择**：从 `agent_engine` 删除，迁移为测试内的对照常量，用于证明「白名单与历史黑名单等价」。

**理由**：生产已由 `INTERACTIVE.allows()` 决定；保留生产常量会让新增工具出现「以为被排除、实际被开放」的误判。等价性证据仍需保留，但应在测试中。

### D6 容器构建描述改为整体复制 + 忽略清单

**选择**：`Dockerfile` 使用 `COPY . .` 配合 `.dockerignore`（排除 `.venv`、`__pycache__`、`*.pyc`、`data/`、`reports/`、`*.log`、`_tmp_*`），删除逐文件枚举。

**理由**：枚举清单已经失效两次（引用已删文件、漏掉包目录）；整体复制使「代码结构 = 镜像内容」成为默认，且 `.dockerignore` 与 `.gitignore` 语义一致、更易维护。

**替代方案**：补齐枚举并加构建期断言——被否。仍需在每次新增包时维护。

### D7 技能按姿态注入

**选择**：装配时按姿态声明的技能名注入，而不是注入整个技能目录；声明缺失时构造期失败（已由 `assert_skills_exist` 提供）。

**理由**：现状是「声明了但没生效」——姿态声明 `deep-analysis`，实际注入整个目录。这使「每阶段至多读 1 个技能」在机制上无保障，只能靠提示词自律。

**待确认**：框架是否支持按名注入的等效能力（`skills=[dir]` 与按名传入的差异）需在实施首日验证；若不支持，退化为「注入目录但在权限层限制可见技能集合」，并在 design 记录限制。

### D8 装配唯一性断言扩至服务目录

**选择**：`tests/test_kernel_runner.py:112-122` 的扫描目标从 `kernel/` 扩到整个服务目录，排除 `kernel/builder.py`、`tests/` 与 `integrations/`。

**理由**：当前断言只证明「kernel 内部没有第二个构造点」，无法阻止业务文件自建——而问题恰好出在业务文件。

## Risks / Trade-offs

- **[破坏性移除端点]** → 在 proposal 与交付说明中标注 BREAKING；若 Owner 要求过渡期，按 D1 的替代返回 410 并保留一个版本。
- **[装配接线导致 HITL 行为变化]** → 先只接对话链（无 HITL），交付链单独一步；每步跑 `tests/test_interrupt_gate_spike.py` 与 `tests/test_outline_gate.py`。
- **[与 auto-041 未提交改动冲突]** → 本 Change 不得直接在当前工作区开工；先完成 auto-041 的提交与合并，或在新分支上继承同一基线的干净副本。
- **[生产服务在跑，改动会被热加载或干扰验证]** → 实施前停止 PID 54088 与两个测试进程；停服属于 Owner 授权动作，不由 AI 自行执行。
- **[`semantic/` 被排除在改动外，但其导入路径会随 shim 删除而变化]** → 本次只改调用方导入语句，不改 `semantic/` 内部；若发现 `semantic/` 内部反向依赖 shim，则停止并上报，不擅自扩大范围。
- **[Docker 无法在本机验证（未安装 docker）]** → 构建验证需在具备 docker 的环境执行，或退化为「静态比对 COPY 清单与磁盘文件」的确定性检查。

## 文件所有权与并行约束

| 文件/目录 | 所有者 | 说明 |
|---|---|---|
| `app.py`、`agent_engine.py`、`agent_tools.py`、`report_session.py` | 本 Change | 同时被 auto-041 修改，必须串行 |
| `kernel/builder.py`、`kernel/registry.py` | 本 Change | 仅在接线需要时修改 |
| `Dockerfile`、`.dockerignore` | 本 Change | 新增 `.dockerignore` |
| `tests/`（相关用例） | 本 Change | 删除与迁移测试 |
| `semantic/` | **不修改** | 仅纳入镜像构建 |
| `modules/`、`archive/`、`01`–`07` | **不修改** | 明确排除 |

同一物理文件同时只允许一名写入者；`app.py`、`agent_engine.py`、`report_session.py` 三个文件是并行工作的禁止区。

## Migration Plan

1. 停服（Owner 执行）→ 建立 `change/auto-042-architecture-consolidation` 分支（基于 auto-041 合并后的 main）。
2. 删死代码（D4、D5、D1、live 残留）→ 全量测试通过。
3. 删 shim（D3）→ 修正所有导入 → 全量测试通过。
4. 接线对话链（D2 第一步）→ 等价性测试通过。
5. 接线交付链（D2 第二步）→ 门禁与 interrupt 测试通过。
6. 修容器（D6）→ 可构建环境验证；否则静态比对。
7. 扩断言（D8）、技能注入（D7）→ 断言在旧代码上应失败，在新代码上通过。

**回滚**：每一步是独立提交，回滚以提交为单位；删端点那一步回滚需同时恢复路由分支与 `analyze_core`。

## 验证记录

### 基线（2026-11-04，提交 `356c7d0d`，分支 `change/auto-042-architecture-consolidation`）

- 环境：Windows，`08_semantic_services/.venv/Scripts/python.exe`，`-X utf8`
- 前置：已停止 PID 54088（8000 端口释放）与两个 `unittest discover` 进程
- 命令：逐模块 `python -X utf8 -m unittest tests.<module>`（内置 `discover` 会挂起，见下）
- 结果：**40 个测试模块，39 个以 OK 结束，1 个无法退出**
- 挂起详情：`tests.test_analysis_primitives` 停在该模块的 `FormOptionsCapabilityTests.test_options_endpoint_omits_undeclared_capability`；该测试构造了 HTTP server 却从未调用 `serve_forever`，请求无人受理而无限等待，`finally` 中的 `shutdown()` 又在等一个不存在的循环。这是测试基础设施缺陷，不是断言失败。

### 1.4 修复后暴露的既有失败（2026-11-04）

修复服务收尾后该模块 4 秒内结束，首次看到真实结果：**35 个测试，13 通过，9 失败 + 13 错误**。

失败根因单一且与本 Change 无关：该模块仍在测试 auto-039 已移除的旧分析方法（`run_aggregate`、`top_negative_claims`、`aspect_scope_compare`），系统当前只接受 `semantic_aggregate`。按测试类分布：

| 测试类 | 失败数 | 判断 |
|---|---|---|
| `PrimitiveExecutionTests` | 11 | 测试已移除的原语执行路径，过时 |
| `PrimitivePlanAndToolTests` | 8 | 测试已移除的方法名与参数校验，过时 |
| `ToolContractFixtureTests` | 2 | 契约夹具仍以旧方法为样本，过时 |
| `TaskBriefDynamicFactsTests` | 1 | 断言依赖旧错误文案，需单独确认 |
| `PrimitiveCapabilityTests`、`PrimitiveBindingTests`、`FormOptionsCapabilityTests` | 0 | 仍有效 |

因此基线应修正为：**39 个模块通过；`tests.test_analysis_primitives` 有 22 项既有失败，源自 auto-039 迁移未清理的过时测试**。后续任务的「全量测试通过」验收必须包含这批失败的处理。
- 未覆盖：容器构建与启动（本机未安装 docker）；仓库外 `/api/analyze` 调用方。

### 1.5 重写结果（2026-11-04）

- `tests/test_analysis_primitives.py` 重写为语义聚合版本：**`Ran 32 tests ... OK`（5.4s）**
- 全量 `discover`：**`Ran 520 tests in 75.402s ... OK`**，进程正常退出
- 保留并加强的断言：指标/维度绑定、`semantic_aspect_metric` 全量对照、`negativeShare` 复算、维度分组求和守恒、口径信封（`模型口径` / population / grain）、时间越界拒绝、非法指标与维度拒绝、SQL 只触碰语义关系、计划与工具参数一致性、fixture 契约闭环
- 移除的断言：`run_aggregate` / `top_negative_claims` / `aspect_scope_compare` 等已不可达方法的执行路径（auto-039 起系统只接受 `semantic_aggregate`）
- 已知残留：`ResourceWarning: unclosed socket`（多个测试未关闭临时连接），不影响退出与结论，未在本 Change 处理

### 5 装配收敛结果（2026-11-04）

- `agent_engine._run_agent_conversation` 与 `report_session.ReportSession` 均改为 `kernel.builder.build_runner`
- `KernelRunner` 新增三个可选注入点，避免为交付链复制第二套 runner：
  - `config_factory`：把 `configurable.thread_id` 合并进调用配置（checkpointer 归属）
  - `resume_builder`：交付链需要 LangGraph 的 `Command(resume={"decisions": [...]})`，且「驳回」是退回模型重写而非终止
  - `interrupt_reader`：把 `__interrupt__` 识别为 `awaiting_review`，不依赖 state 里的 `status` 键
- 全量：`Ran 490 tests ... OK`（107.8s）；装配相关子集 68 tests OK
- `grep "create_agent(|create_deep_agent("` 生产代码仅 `kernel/builder.py`，另有 `tests/test_interrupt_gate_spike.py` 的测试夹具
- **5.4 结论**：`interactive` 字段语义是「无计划时是否允许取数」，与链路是否面向人类会话无关，交付链传 `True` 是为保留「计划提交前的探索窗口」。字段名有歧义但行为正确，本次**保留**并加用例锁定（`test_exploration_allowed_before_plan_in_interactive_mode`、`test_exploration_denied_without_plan_when_not_interactive`）；重命名为 `pre_plan_exploration` 属独立重构，未在本变更执行。

### 6 容器与最小权限（2026-11-04）

- `Dockerfile` 改为 `COPY requirements.txt` + `COPY . .`，新增 `.dockerignore`（排除 `.venv`、`__pycache__`、`*.pyc`、`data/`、`reports/`、`*.log`、`_tmp_*`、`tests/`）
- 静态核对：`COPY` 仅 2 条；`app.py`、`requirements.txt`、`web`、`agent_skills`、`kernel`、`semantic`、`research`、`routing`、`integrations` 在磁盘均存在
- 本地冒烟（无 docker，直接 `python app.py`）：`/api/health` 200、`/api/analyze` **404**、`/api/question` 200、`/api/does-not-exist` 404
- `docker-compose.yml` 未改动，安全项在位：`read_only`、`cap_drop: ALL`、`no-new-privileges`、`pids_limit: 128`、`mem_limit: 2g`、`cpus: 2.0`
- **未验证**：`docker build` 与容器内启动（本机未安装 docker）

### 7 约束机械可验证（2026-11-04）

- 装配唯一性断言扫描范围从 `kernel/` 扩至整个服务目录（排除 `.venv`、`__pycache__`、`tests`，`kernel/builder.py` 除外）
- 技能注入改为 `builder.skill_paths(profile)`：只注入 `profile.skills` 声明的目录，未声明即构造期 `ValueError`
- `DELIVERABLE.skills` 显式声明 4 个阶段技能（`deep-analysis`、`plan-drafting`、`execute-plan`、`report-authoring`），与「按阶段读技能」的流程一一对应
- 新增用例：窄声明只解析出声明项、未声明技能构造期失败、未知路径 GET/POST 均 404

### 8 集成验证（2026-11-04）

- 环境：Windows，`08_semantic_services/.venv/Scripts/python.exe`，`-X utf8`
- 全量：`python -X utf8 -m unittest <全部 tests.test_* 模块>` → **`Ran 497 tests in 71.661s ... OK`**
  - 说明：`-m unittest discover -s tests -t .` 在本仓库报 `Start directory is not importable`，改用显式模块列表；结论等价
- 四条入口的替身端到端：`python -X utf8 -m unittest tests.test_api tests.test_auto030_contracts tests.test_outline_gate` → **`Ran 56 tests in 7.916s ... OK`**
  - 健康检查：`test_health_ok_without_model`
  - 对话：`test_greeting_uses_agent_without_route_classifier`、`test_all_turns_use_contextual_agent_and_agent_error_is_explicit`
  - 报告问答：`tests.test_auto030_contracts` 的 `/api/ask` 成功与拒绝路径
  - 深度分析至大纲暂停：`test_start_pauses_at_gate_with_outline_and_no_execution`
- 本地 HTTP 冒烟（`python app.py`，端口 8000）：`health=200 question=200 ask=200 report=202 analyze=404`
- 真实模型驱动的深度分析冒烟（临时脚本起 `ThreadingHTTPServer`，停在门禁不确认，脚本用后已删除）：
  - 首次运行**失败**：`TypeError: build_runner() got an unexpected keyword argument 'config_factory'`，15.1s 后 `failed`
  - 根因：`report_session._ensure_runner` 传了 `config_factory` / `resume_builder` / `interrupt_reader`，而 `kernel.builder.build_runner` 既未声明也未透传；替身用例绕过该构造路径，全量测试未暴露
  - 修复：`build_runner` 增加三个可选参数并透传给 `KernelRunner`；新增 `BuildRunnerInjectionTests`（注入点透传 + 未注入时保持默认）
  - 门禁暂停复跑：`status=awaiting_review`、`phase=待大纲审查`、`outline_steps=4`、`events=[澄清中, 收尾中, 待大纲审查]`、`execution_started=false`、`clarify_rounds=0`、`wall=36.2s`
  - 完整链路（确认大纲后继续执行，同脚本第二次运行，`wall=97.8s`）：
    - 时间线：`澄清中 → 待大纲审查 → 编写分析代码中 → 撰写报告中 → 已完成`；`confirm_http=202`、`final_status=done`
    - 成稿：`report_id=d53870c2e675`，3469 字符，4 条 key findings，7 个去重 claim_id，13 条 evidence，`publication_status=pending_review`，`data_version=semantic-2026-11-03.4`，无内部实现词（`semantic_` / SQL / CREATE TABLE）
    - 执行质量：工具调用 10 次，`tool_errors=0`、`code_failures=0`、`gate_rejections=1`（报告门禁先拒后过，两次运行均如此）
    - `charts=0`：图表由模型按内容自选，同问题首次运行产出 2 张，故不断言图表数量
    - 报告问答：以成稿作 `report_ref.kind=mine` 调 `/api/ask` → **200**，答案 1141 字、6 条章节引用；首页 `/` → 200（5833 字符）
- **未覆盖项**：
  - `docker build` 与容器内启动、只读根目录下的实际运行（本机无 docker）
  - 真实模型输出不具确定性：成稿长度、图表数量、claim 分布属单次样本，不是稳定性结论
  - 仓库外是否存在 `/api/analyze` 调用方
  - `semantic/` 包按 Owner 要求未改，其内部是否隐含依赖被删 shim 未逐文件核验（当前全量测试通过，未见导入错误）
  - `ResourceWarning: unclosed socket` 仍存在于多个测试，不阻断结论

### 9 架构残留清理（2026-11-04）

第 8 组验收后对「架构是否干净」做了一次静态核查，发现契约与文档层面的残留，按 Owner 授权清理：

- **`run_aggregate` 死路径**：`agent_tools` 的计划校验在 `method != semantic_aggregate` 时已 return，其后的 `is_primitive` 分支不可达；`research/analysis_methods.py` 仍保留 `PRIMITIVE_METHOD`、`PRIMITIVE_METRIC_LABELS`、`validate_primitive`、`build_primitive_sql`、`primitive_caliber`、`run_primitive`、`assert_semantic_only`（与 `verifier` 重复实现）与旧 SQL 执行分支。现全部删除，该模块只剩语义层方法；`run()` 保留未使用的 `con` 参数仅为兼容既有调用签名
- **目录契约收敛**：`research/catalog.py` 的 `DIMENSIONS[*].methods` 原列 `top_negative_claims`、`aspect_scope_compare`、`curated_sentiment_mix` 等已不存在的方法名，`METHOD_DIMENSIONS` 据此派生并被 MCP/表单读取；现统一为 `semantic_aggregate`。`PRIMITIVE_METRICS` / `PRIMITIVE_DIMENSION_COLUMNS` / `validate_primitive_bindings` 删除，`catalogue()` 的 `primitive` 段只留 `capabilities`
- **孤儿模块**：`routing/gates.py` 生产代码零引用（只有 `tests/test_kernel_gates.py` 调 `check_input`），文件头还在解释已删的 `routing/intent.py`。已删除该文件、`routing/__init__.py` 与 6 个对应用例，`routing/` 目录不再存在
- **文档**：README 删除 `/api/analyze` 的旧契约（改为「已移除，返回 404」），`/api/question` 改为现状（单一上下文化 Agent、返回 `response_type=conversation`、无 `intent`），模块职责段去掉「路由」，测试命令改为实测可用的显式模块列表（`unittest discover -s tests` 在本仓库报 `Start directory is not importable`）
- **测试**：删除恒真断言 `test_package_and_legacy_imports_share_the_same_service`（`research.service` 与自身比较）、`PrimitiveBindingTests`；新增 `MethodCatalogueTests` 锁定「目录只登记真实方法」；`test_semantic_method` 改用 `verifier.assert_semantic_only`
- 保留项（非残留）：`semantic/adapters/compat_views.py` 是当前取数视图层（生产 5 处引用）；`agent_engine._baseline_step` 用 `aspect_scope_compare` 仅作来源账本的展示名；`report_gate._plan_requires_evidence` 保留 `top_negative_claims` 只为读取历史计划，已在 docstring 说明

验证：
- 全量：**`Ran 489 tests in 61.019s ... OK`**（删 6 个 gates 用例、3 个绑定用例、1 个恒真用例，新增 2 个目录用例）
- 真实端到端复验：`澄清中 → 待大纲审查 → 编写分析代码中 → 撰写报告中 → 已完成`，4752 字符、5 条 key findings、6 个 claim_id；工具名只有 `run_semantic_aggregate` / `semantic_overview` / `get_negative_evidence` / `search_claims` 等语义侧工具，`used_run_aggregate=false`；`tool_errors=0`、`code_failures=0`；`wall=102.8s`
- 已知不稳定：`tests.test_analysis_options.ChartDataTests.test_invalid_chart_type_dropped_with_warning` 在一次 7 模块批量运行中失败（该批耗时 41s），单独与复跑均通过；判断为沙箱执行在负载下的超时/资源竞争，非本次改动引入，根因尚未定位

第二轮核查（同一标准，2026-11-04）：

- `research/evidence_match.py`（91 行）生产零引用，仅 `tests/test_evidence_match.py` 的 4 个用例调用；它实现 06 报告层的严格证据块规则，与当前 `verifier.verify_step` 不是同一链路，属 `routing/gates.py` 同类遗留。已删除模块与用例
- `kernel/__init__.py` 的「Phase 1：只建不接」已过时（auto-040/041 已接线），改为「装配、预算、闸门与失败语义」的现状描述
- 复验：**`Ran 485 tests in 57.146s ... OK`**；用 AST 扫描 61 个生产模块，未被任何模块 import 的只剩 CLI 入口（`integrations/mcp_server.py`、三个 `semantic/*/__main__.py`），符合预期

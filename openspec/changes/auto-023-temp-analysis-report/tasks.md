# Tasks

## 1. 数据核对与初稿

- [x] 1.1 核对 `06_reporting/analysis/` 冻结数据资产（summary/profiles/aspect-sentiment/scope/verification/reviewed-cases）与口径（2026-10-22，撰写时逐文件抄录核对）
- [x] 1.2 撰写临时报告初稿 `06_reporting/agent-kb/report.md`：执行摘要、数据画像、术语表、cohort 漏斗、方面×情感全景、深挖、11 案例库、竞品视图、方法论、拒答清单、Agent 回答模板（证据：全部数字来自冻结文件，派生值已标注）
- [x] 1.3 创建本 Change 分支与四份 OpenSpec 工件（proposal/design/spec/tasks）
- [x] 1.4 落实 Owner 指示"上一版本数据、只搭架子"：报告头部标注占位性质与数据版本；工件沉淀知识库数据契约（来源清单/版本声明/替换方式），spec 增加「数据版本声明与可替换性」Requirement
- [x] 1.5 双投影格式架子（Owner 2026-10-22 确认，取代原"单一源"设计）：构建链 `build_report.py → render_html.py → verify.py`（Python 3.11+，仅标准库）——
  - `numbers.json` 答案册：报告全部统计值的唯一数据接缝，含 16 方面表、cohort 漏斗、旅程对比、竞品、11 案例与元信息；
  - `assets/` 4 张数据生成的 SVG（漏斗/热度条形/负面占比条形/旅程对比，含悬停提示）；
  - `report.md`（Agent 版）：由脚本自动生成——元信息块 + [K]核心数字速查 + [D]口径 + [F]事实章节 + [C]案例库 + [R]拒答清单 + [T]回答模板（策略块来自 `agent-policy.md`）；
  - `report.html`（人类版）：单文件离线可打开（57KB）；
  - `verify.py` 一致性门禁：图表完整、无未填令牌、MD 覆盖全部关键数字、HTML/MD 抽样数字一致、案例数、章节注册表、来源哈希——当前全绿；
  - spec 更新为「双读者双投影结构」与「数据可替换与可扩展」两条 Requirement
- [x] 1.6 按 Owner 三点要求重构（2026-10-22）：①全文改用户研究语言，去除口语化标题与工程师词汇（Claim/cohort/答案册/verify 等退出 HTML 正文）；②`configs/template.html` 不再含任何固定章节标题——模板只定义版式解剖学（封面/结论框/图/表/tabs/折叠/建议卡的格式与交互），章节内容与顺序全部由 `configs/content.json` 章节注册表驱动，新增章节=加一个条目、模板零改动；③结论全部自包含无上下文依赖，术语双语首次出现即解释，复现说明保留于附录 A
- [x] 1.7 按 Owner 要求对齐 01/02 模块风格（2026-10-22）：`agent-kb/` 重排为 `src/report_kb/`（builder/render/verify/cli/paths 包）+ `configs/`（content/template/policy）+ `output/`（生成产物，与源码分离）+ `docs/data-contract.md`（数据契约）+ `evidence/verify-latest.json`（运行记录）+ `pyproject.toml` + `run.py`（01 式入口，`python run.py all|build|render|verify`）+ `README.md`（模块说明/运行/变更方式/边界）；构建链在新布局下全绿；06_reporting 根下旧版报告资产（analyze.py/compose.py/verify.py/app/analysis 等）保持只读不动
- [x] 1.8 按 Owner 反馈重构内容结构与可插拔层（2026-10-22）：①块类型注册表 `src/report_kb/blocks.py`（para/note/figure/tabs/table/details/cases/recommendations/conclusion），新增块类型=加一个方法+一行注册，模板与渲染核心不动——"可插拔"落在内容块层，agent 可调用工具层属后续问答 Change（分层边界经 Owner 确认讨论）；②内容按行业规范重组：研究方法与数据前置（一次说清口径/质量/局限，正文不再穿插）→ 核心发现 F1–F5（统一解剖：发现陈述→证据→研究含义）→ 建议与优先级 → 附录；③视觉主题重做（白卡分区、发现/含义双色标注、封面 kicker+统计卡、表格与交互细化），构建链全绿
- [x] 1.9 按 Owner 二轮反馈修订（2026-10-22）：①视觉改编辑部风格（纸感底色、serif 标题、书tab 式三线表、细线分隔，弃卡片阴影堆砌）；②术语对齐用户研究/社媒聆听行业语言（用户观点/声量/负面声量占比/竞品关联提及/车主身份标签/证据回溯校验/样本留存率），附录 B 术语表同步；③方法章新增"分析方法说明"折叠块，向读者透明说明统计=上游模型抽取（冻结）+固定口径聚合代码，解读为人工撰写并随数据更新单独复核
- [ ] 1.10 标准件替换（2026-10-25 Owner 确认，与 auto-025 M1 协同）：①图表渲染自写 SVG → ECharts 声明式注册表（configs/charts.json：类型/数据源/参数；ECharts JS 内嵌单文件 HTML，离线交互，弃手写坐标系）；②口径形式化 configs/metrics.json（指标名/公式/分母口径/适用群体/来源，builder 与 verify 共同消费，改口径一处生效）。（原 ③"本期变化"块依赖跨期 diff，已随 auto-025 决策移入其后续项 5.4）

## 2. 评审与核验（待 Owner 批准后推进）

- [ ] 2.1 Owner 规格审查：审阅 proposal/design/spec/tasks 并回复批准或修改意见（当前 PENDING_REVIEW）
- [ ] 2.2 报告人工评审：Owner 通读报告，重点核对 §1 摘要结论、§5 读表要点与 §10 拒答清单是否符合预期口径
- [ ] 2.3 数字独立抽查：由评审者从报告抽取 ≥10 个精确计数，对照冻结来源文件核验（对应 spec「数字可追溯」场景）
- [ ] 2.4 按评审意见修订报告与工件，更新 proposal 的批准记录（reviewer、日期、verdict、未决项）

## 3. 交付与后续（独立跟进，不计入本 Change 实施进度）

- [ ] 3.1 创建交付 PR（本 Change 唯一分支 → main），等待人工审查与合并；不自行合并
- [ ] 3.2 （第一阶段·后续 Change auto-024，已实现待审查）问答 Agent：报告全上下文离线问答（整份报告进 LLM 上下文，[R]/[T] 天然在场；引用锚点校验 + 数据版本声明由流水线追加；无 LLM 诊断模式）；端到端验证已通过（统计类/拒答类）；Owner 2026-10-22 指示：明细即时查询移出第一阶段，联网采集分析不做
- [ ] 3.3 （第二阶段·后续 Change auto-025）正式报告自动化：单 Agent + 多 Skills + 多 MCP 编排（语义层边界、Agent 不接触原始数据），替代本 Change 的脚本式临时产出；数据管道自动运行，人只处理结论翻转等异常
- [ ] 3.4 （随新数据）新版本数据就绪后重跑构建链，人审变化清单覆盖的结论，升级为正式知识库版

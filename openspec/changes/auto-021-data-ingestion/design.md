# Design

## Context

动机见proposal。Owner于2026-10-21批准8表方案，替代未交付的18表初版。分支change/auto-021-data-ingestion；工作区G:/AutoInsight-wt-auto021，基线501d12d。原工作区、ZIP和旧库不修改。旧版导入/联网证据不充当新版验收。

## Goals / Non-Goals

**Goals:** Python标准库HTTP服务、SQLite单写入、内容寻址快照；可追溯、重放、去重和迁移，日常直接读当前业务表。

**Non-Goals:** 不维护通用实体/历史业务观察层、多级任务平台、MCP、语义模型、图片本体下载、Agent、事件或分布式服务。

## Decisions

### 1. 八张表

posts以post_id唯一，含正文、作者ID、时间、质量和segments_json；users以user_id唯一，不生成作者空壳；product_specs以specid唯一并内含品牌/车系字段；product_parameters以specid+参数来源键唯一，分组响应合并，参数各有来源时间。

source_snapshots保存hash/相对路径、采集锚点、来源元数据、运行ID、解析配置/版本/问题摘要；相同字节共用原始文件。collection_runs合并HTTP任务与CLI运行，存幂等键、状态、配置、尝试统计JSON和结果，恢复沿用任务ID并增加执行次数。collection_failures记录失败页或对象及错误/次数/pending或resolved状态。collection_checkpoints按来源+论坛ID+排序契约保存成功上界、覆盖起点与成功运行。

业务行保留快照ID、定位和处理版本。历史通过原始快照重放，不再SQL查询全部观察版本。已知采集时间优先于未知；旧重放不回退新数据。同一来源同版本处理冲突拒绝；未知时间内容冲突先按字段出处/显式来源优先级判断，无法确定记录待复核，不用hash大小选择“最新”。车系库只存CSV快照，供车型填充名称时匹配，不另建表。

### 2. 一致性与兼容

先写内容寻址raw文件，再登记快照；业务更新和解析状态同事务。无引用文件verify报告但不删除。PRAGMA user_version管理版本、数据库元信息保存schema哈希；版本1拒绝直接打开。migrate-v1只读源库到全新目标，保留旧库/全部旧观察供回滚，不做原地drop。导出契约改为ingestion-2。

### 3. 轻量增量

2026-10-21 Owner进一步要求字段必须对齐、按清晰语义命名。兼容层显式映射旧帖子25列、用户14列、配置长表8列，并接收车型清单和车系目录；源有字段不得静默丢弃。旧帖子侧栏资料保存在posts.author_context_json（帖子采集当时上下文），不覆盖users当前资料；列表/详情作者与原始相对时间分开保留。是否匹配正文等旧工具状态保留为legacy_parse_status，非产品事实。新页面未能取得字段null并记field_availability，不伪造0或沿用旧数据冒充新抓取。完整字段说明交付docs/field-mapping.md。

sort=Lastest的最新发布语义采用Owner报告的实测结论，不冒充本轮验证。固定上界为开始时间与end较早者；首次必须start，之后下界=checkpoint-overlap_days，显式更早start可扩大但不能向后跳过缺口。按ID去重但不因存在停止。

只用明确非置顶项校验倒序/判断下界；完整检查本页再决定停止，缺时间/乱序partial不推进。日精度按时间区间相交处理。下界前空白有限重试且扣预算，失败记录页码URL；窗口内详情失败/取消/预算或页数耗尽均保留旧检查点。帖子覆盖成功后事务推进，再独立补用户；用户失败不撤销帖子检查点。恢复重扫首页而不复用旧列表，避免分页移动；快照可离线重放。

### 4. 接口与部署

四HTTP接口创建/状态/恢复/取消保持不变；localhost、幂等键、固定目标、网络双许可。不接受任意URL/路径，不存凭证。一个worker、进程锁和串行事务，无外部队列。重启标记interrupted，不自动联网。CLI提供导入/回放/检查/导出/备份恢复/只读迁移；新目录恢复检查hash与FK。Docker环境缺失时保留未完成；月更调度不自动配置。

### 5. 数据规则

五项作者字段采用楼主资料卡`/frontnc/user/getdetailusertpl/{uid}-{flag}`（flag=问答1/普通0）。依据交接包fetch_forum_data.py:704-794的明确结构，用name链接核验用户ID，再读取count-item/strong与profile-cars-item。计数规范为非负数，明确0保留；热门帖链接为栏目入口，不冒充具体帖子URL；多辆爱车完整保留为自述文本，不推断拥有。用户表存当前值，posts.author_context_json存采集当时值及卡片快照ID；旧CSV对应字段在相同纯转换函数中规范化。按uid+flag在一次运行内复用卡片，请求预算包含该请求。主页补充失败不能清除已经取得的卡片值；字段未展示、解析异常、请求失败有不同状态。冻结回放恢复卡片关联，禁止重放联网补抓。

保留原始/清洗文本、日或秒精度及时间依据，相对日期只用保存retrieved_at。性别明示/推断分开，缺数值不填0，不推断车主；仅楼主正文按顺序存文本/图/视频，未知结构不最长段兜底，旧纯文本顺序未知。产品必须显式车系，状态与猜想图保留，参数按来源键而非名称合并。

### 6. 文件所有权

Codex是offline_pipeline与本Change唯一写入者；不改主工作区和其他Owner文件，不安排并行作者。契约冲突停下协调；完工仍须人类审查，不自行推送、合并、同步正式spec或归档。

## Risks / Trade-offs

- [当前表没有全部历史业务版本] -> 原始快照和旧库保留，历史查询通过独立目录重放。
- [JSON不如片段多表适合复杂SQL] -> 日常直接读posts，必要时json_each。
- [未知置顶或模板变化] -> 乱序/缺时间fail-closed，不误报覆盖；不承诺平台完整召回。

## Migration Plan

版本2使用新目录，离线导入ZIP或只读迁移版本1快照；核对计数、raw hash、去重、备份恢复和确定性导出。旧材料不动；回滚读取旧库。

### 7. 登录态注入与重定向有界处理（2026-10-21追加，待Owner审查）

L2验收需要登录态。凭证文件为Playwright storageState格式（`cookies`数组+`origins`），Owner本机提供路径，不复制进仓库。注入契约：运行时读取凭证文件，按请求域名匹配Cookie（club.autohome.com.cn与.autohome.com.cn），仅在`allow_network`显式授权且任务配置显式声明`credential_file`时注入；凭证MUST不写入快照元数据、manifest、日志、数据库与导出（沿用safe_metadata剔除cookie/authorization/token）。未提供凭证时采集器保持匿名可用，任务标注credential_absent而非失败。文件中部分Cookie过期时间约为2026-10-07/08（sessionvid、_ac、pageid、papopclub等），sessionid有效期至2027年；注入时按expires字段过滤已过期Cookie，登录态是否有效以实测为准。

301处理：现采集器NoRedirect不跟随任何重定向。用户主页两次301的跳转目标尚未核对，MUST先以冻结的301响应离线核对目标域名与路径模式，再决定策略：仅当目标在HOSTS白名单内且预算允许时允许一次受控跟随并记录跳转链；白名单外或二次跳转记redirect_rejected，保留原响应，不把重定向页解析为内容。禁止以"试出"方式在线探测跳转。

### 8. L1/L2验收分层

L1（无需登录态）覆盖：帖子详情发布时间解析、正文有序片段、产品元数据落库、检查点推进、幂等、冻结回放确定性。L2（需登录态）覆盖：用户主页关注/粉丝/IP/爱车字段及301受控跳转。两层分别记录结论；任一层未通过整体为partial。冻结样本MUST标注凭证状态（anonymous/authenticated），回放确定性结论仅对其标注的凭证状态成立。

### 9. 验收缺陷修复规则（2026-10-21追加，Owner批准）

发布时间回退：详情页解析无时间且author_hint的post_id匹配时，采用列表published_raw解析结果，basis标注list_page_time，原始值与精度保留；列表时间无效或hint不匹配时保持unknown，不伪造。价格元数据：listSpec响应speclist的price/pricetips映射list_price_raw（厂商指导价原值），分组name映射model_group，iselectric/iswaitsell入condition_tags_json；listSpec无经销商价，dealer_price_raw留空；两响应同spec_id由product_json单条record合并产出，避免upsert覆盖。问答资料卡（flag=1）仅含回答/被采纳计数，无三计数为源站设计，处理方向待Owner决策，本轮失败如实记录。

### 10. 存储精简原则（2026-10-21追加，Owner授权按最佳实践执行）

原则：原文取证统一走source_snapshots原件，业务表不重复存可在原件完整找到的文本；高频聚合字段强类型（数字/数组）；JSON仅承载低频审计字段与时点快照。执行：posts.author_context_json移除profile_raw（占payload 44%，CSV原件完整可替代），field_contract映射改为source_snapshots取证；product_parameters.source_value_json经评估保留（总量300KB、含itemid映射、取证成本低于升schema版本，理由记录在案）。body_text与clean_text、author_context与users、时点昵称与当前昵称均为语义性双份（时点快照vs当前值），非冗余。移除后author_context平均体积542→约300字符。

## Verification Record

2026-10-21迁移交接：Owner明确暂停采集问题修复，要求完整下游与SQLite迁入GitHub独立文件夹。新增`offline_analysis_pipeline`按01采集、02清洗、03图片、04抽取、05归一、06报告划分；旧脚本所需相对布局通过本包manifest显式恢复。路径适配只改副本，不改原模块或数据。根仓库OpenSpec仍为唯一要求源，包内历史工件仅参考。新目录79项采集测试、21项归一测试通过，恢复两套SQLite及raw的FK/hash通过；不是旧下游到新SQL的集成验收。完整范围/检查/未迁入项见`offline_analysis_pipeline/docs/MIGRATION_CHECK.md`。当前未完成任务仍保持未完成，后续需人类代码审查；不宣称第二台电脑、Docker或模型重跑验证。

作者五字段子任务（2026-10-21）：79条离线测试通过，命令`offline_pipeline/.venv/Scripts/python.exe tests/run_suite.py --report evidence/unit-tests-author-fields.json`（在offline_pipeline运行时使用./.venv）。新增测试文件tests/test_author_fields.py覆盖资料卡解析与HTTP任务到SQL。实际调用smoke_live.py --author-card-only产生1次外部请求，HTTP200，三个计数及热门入口入库；该用户未展示爱车，保存not_displayed，不填造值。预算1次使额外主页停止，任务partial，不是完整资料发布验收。verify_frozen_http.py对该冻结响应0外部请求回放，结果一致且存储检查通过。详情见offline_pipeline/docs/author-fields.md。未将真实检查扩展为全量采集，未向9994篇业务库补入帖子。

治理门禁按每个批次而非合并库运行。预期可获取字段整列空值、源有值而标准层缺失、失败覆盖有效值、主键重复或断裂来源均阻止数据发布。正常空数组、平台未展示与采集失败分开。旧工具error不作为用户属性，转失败记录；是否匹配正文转快照审计。新版为唯一入口，旧18表不运行，不为兼容无限保留旧实现。

新版实施前未验收；旧52条测试和6次联网请求不能替代8表回归。实施后追加实际命令与边界。

真实采集验收执行（2026-10-21，任务8.1-8.6）：Owner确认30帖、预算120。工具`tools/live_acceptance.py`探针1次定位第30帖下界，posts任务111次+product 3次，共115/120。结果：30/30帖正文ordered；发布时间24/30（6帖详情无时间标记，列表时间保留list_time_raw）；作者卡22/26（4个flag=1问答卡counters_missing，新发现）；用户主页24/26取得粉丝/关注/IP（登录态生效，上次0）；301目标核对为`i.autohome.com.cn/{uid}`白名单内受控跟随；幂等同键同job 0请求；冻结回放0外部请求、105/105有效响应一致、10个失败响应按设计拒绝。检查点0条：末次主页请求预算耗尽fail-closed不推进，正确行为。整体验收partial：发布时间解析、问答卡、产品元数据落库为待修项，详见`offline_analysis_pipeline/01_ingestion/docs/evidence/live-acceptance-20261021.md`。Cookie值零持久化；数据在`01_ingestion/local-data/`（不提交）。实施位置为本仓库副本，改动未提交，待人类代码审查。

凭证注入与重定向实现（2026-10-21）：8.1结论——实测冻结库`data/live_test`中两次用户主页301快照provenance仅含http_status与url（`i.autohome.com.cn/252863377/home.html`），响应体为0字节，Location跳转目标未保存，离线核对目标不可行；该缺口由本轮实现补齐（provenance新增redirect_target，经safe_metadata脱敏，真实目标待8.4在线快照核对）。跳转策略落地：白名单内且深度0时一次受控跟随并消耗预算，白名单外、二次跳转或目标缺失记redirect_rejected并保留原响应；401/403/405/429与验证页停机语义不变。8.2完成——新增`collect/credentials.py`（storageState解析、域匹配、过期过滤，错误码credential_file_missing/credential_file_invalid）、`Transport.attach_credentials`与每请求Cookie头构造；runner/jobs/cli以服务级credential_path传递，任务请求与run config不含路径，仅记录credentials=provided/absent，无凭证路径匿名可用。测试90项全部通过（79项回归+11项新增`tests/test_credentials.py`），报告`evidence/unit-tests-credentials.json`；命令`PYTHONPATH=src`后`python -m unittest discover -s tests -q`（Python 3.11.9，本机新装）。全部为离线替身验证；真实登录态有效性、301真实跳转目标与L2字段验收待8.3/8.4在线执行，不据此宣称。实施位置为本仓库`offline_analysis_pipeline/01_ingestion`副本（原G盘worktree不在本机），改动未提交。

# 真实采集验收：2026-10-21（30帖窗口 + 登录态）

结论：L1、L2 分层执行完毕。正文有序片段、登录态主页、幂等、有效响应回放一致性通过；发布时间解析 80%、检查点未推进、产品元数据仍缺。**整体未通过完整采集验收**，不得作为全量采集或下游分析可用的证明。

## 范围与执行

- SU7 车系 6962。探针 1 次请求定位第 30 帖发布时间作为窗口下界，窗口 [下界, 执行时刻)。
- 请求预算 120，实际 115：探针 1 + posts 任务 111 + product 任务 3。HTTP 200×91、301×24。
- 登录态：Owner 本机 `club_auth.json`（Playwright storageState）运行时注入，过期 Cookie 自动过滤；114/115 快照 credentials=provided（探针 absent）。Cookie 值未出现在任何快照、日志或报告中。
- 本轮实现：运行时凭证注入、重定向有界跟随（白名单内一次、消耗预算、记录跳转目标）。
- 新工具：`tools/live_acceptance.py`（探针定窗、预算分层、统计报告、--stats-only 复算）。

## 分项结果

| 环节 | 实际结果 | 验收判断 |
| --- | --- | --- |
| 帖子 | 30/30 入库，正文有序片段 30/30 ordered | L1 片段链路通过 |
| 发布时间 | 24/30 详情页解析成功（explicit second）；6 帖详情无时间标记（time_basis=unknown），列表时间完整保留于 list_time_raw，标记 publication_time_unknown | 80%；待修项"详情发布时间"复现，未修 |
| 作者资料卡 | 22/26 成功；4 个失败全部为 flag=1（问答区）卡片 author_card_counters_missing | 新发现：问答资料卡模板缺计数结构 |
| 用户主页 | 24/26 取得粉丝/关注/IP（上次 0/1）；301 跳转目标核对完成：`i.autohome.com.cn/{uid}`（去除 /home.html 后缀），白名单内受控跟随一次 | L2 通过；任务8.1闭环 |
| 产品 | 9 配置、2619 参数，任务 succeeded；指导价等元数据仍未入标准表 | 参数链路通过；待修项"元数据落库"未修 |
| 检查点 | 0 条：最后一个用户主页请求耗尽预算（request_budget_exhausted），fail-closed 不推进 | 保守门禁正确；预算模型需按"作者数×(1卡+1主页+约1跟随)+余量"估算 |
| 幂等 | 同幂等键同请求返回原 job_id（9141b94d...），不创建新任务、0 网络请求 | 通过 |
| 冻结回放 | 0 外部请求；105/105 有效响应重放一致；重复回放不变；10 个失败响应（301/解析失败）按设计拒绝回放；备份恢复 FK/hash 通过 | 回放验收通过；失败响应不可回放为工具设计限制 |
| 存储 | verify 通过：posts 30、users 26、specs 9、parameters 2619、snapshots 115 | 通过 |

## 待修复（更新自实测报告 20261021）

1. 详情页发布时间解析（6/30 缺失）。可选方向：详情缺时回退列表时间并标注 basis=list_time，须 Owner 决策后立规范再改。
2. 问答资料卡（flag=1）计数缺失 4/4；普通卡（flag=0）无此问题。
3. 产品元数据（指导价、经销商价等）落库。
4. 预算估算模型（作者数×3 + 列表/互动 + 余量）写入运行说明，避免 partial。

## 证据与复现

- 验收库：`local-data/live-acceptance-20261021/data/db/ingestion.sqlite3`（不含凭证）。
- 报告：`local-data/live-acceptance-20261021/verification.json`、`idempotency-check.json`。
- 回放：`local-data/live-acceptance-replay-20261021/verification.json`。
- 命令：`PYTHONPATH=src` 后 `python tools/live_acceptance.py --allow-network --output local-data/live-acceptance-20261021 --credential-file <本机凭证路径> --target-count 30 --max-requests 120`；复算统计加 `--stats-only`；回放 `python tools/verify_frozen_http.py --input-data ... --output ...`。

环境：Windows、Python 3.11.9、stdlib-only。`verification.json` 中 credential_file=false 系 --stats-only 复算未带参数所致，实际采集时以 114 份快照 credentials=provided 为准。单窗口样本不代表源站所有页面或未来版本。

---

# 第二轮（修复后重跑）：2026-10-21

Owner确认修复方向后执行任务9.1/9.2并重跑（预算150，新目录`local-data/live-acceptance-2-20261021`）。

## 修复内容

1. **发布时间回退**（9.1）：详情页无时间时采用列表时间，basis=list_page_time，原始值与精度保留；详情优先语义不变。
2. **产品元数据落库**（9.2）：新增product_list解析listSpec，指导价（price→list_price_raw）、分组（model_group）、状态标签（iselectric/iswaitsell→condition_tags_json）写入product_specs既有列；listSpec未提供的经销商价留空。

## 第二轮结果（121/150请求）

| 指标 | 第一轮 | 第二轮 |
| --- | --- | --- |
| 发布时间 | 24/30（80%） | **30/30（100%）**：25 explicit + 4 list_page_time秒级 + 1 list_page_time日级 |
| 指导价落库 | 0/9 | **9/9**（21.59万/29.99万/24.59万等原值），model_group 9/9，dealer_price 0/9如实留空 |
| 检查点 | 未推进 | **推进**：covered_from=2026-10-15T13:43:52+08:00，checked_until=2026-10-21 |
| 帖子质量 | 6帖review_required | **30/30 ready** |
| 幂等 | 通过 | 通过（同键同job） |
| 回放 | 105/105一致 | 0外部请求，121份回放，重复回放不变，业务行不变 |
| 预算 | 115/120 | 121/150 |

posts任务仍partial：仅因4个问答卡counters_missing（任务9.3语义决策待Owner）与1次主页http_error（max_attempts=1无重试）。冻结回放整体门禁为False：27个失败响应按设计拒绝重放、4个问答卡解析失败、**6个unversioned_processing_change（第一轮2个，需定位回放工具与处理版本判定逻辑，列为待查）**。核心一致性指标（有效响应回放、重复回放不变、业务行不变、30帖ready）全部通过。

## 第二轮证据

- 验收库：`local-data/live-acceptance-2-20261021/data/db/ingestion.sqlite3`。
- 报告：`local-data/live-acceptance-2-20261021/verification.json`；回放：`local-data/live-acceptance-2-replay-20261021/verification.json`。
- 测试：tests/test_fixes.py 6项，全量96项通过（evidence/unit-tests-fixes.json）。

---

# 附：存量 226 条 review_required 抽查（2026-10-22）

Owner质疑226条来源后完成溯源与在线抽查（tools/spot_check_posts.py，3次请求；解析tools/parse_spot_check.py）。

- 溯源：226条全部来自`合并完整_20261016_162543.csv`（旧管线2026-10-16合并输出），正文列100%真空，当年审核列"是否匹配正文"全为"否"；构成：1图99条、2-9图106条、无媒体21条。
- 在线抽查3条（1单图/1多图/1无媒体）：1条存活确为纯图帖；**2条网页已不存在（发帖后被删）**——Owner浏览器实测确认。
- 结论修正：226条为"存活纯图帖"与"已删除帖"的混合，抽查显示已删帖占比可能过半（交易/违规帖被删是常态）。49条media_order_unknown为历史CSV顺序限制，与删除无关。
- 清洗阶段处置（供清洗Change立项）：对历史帖以抽样探测标记"当前可访问性"，不全量探测；已删帖默认排除出语义分析样本并保留库中标记（被删帖非社区现存内容代表）；存活纯图帖按"图片帖"规则放行（正文=标题+图片清单）；21条无媒体帖人工抽查后定级。

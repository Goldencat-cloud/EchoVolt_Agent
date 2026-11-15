# 采集真实测试：2026-10-21

结论：部分链路通，未通过完整采集验收。不得作为全量采集或下游分析可用的证明。

## 范围与结果

用户本轮明确要求真实测试。采用独立测试库，SU7车系6962，发现首个非置顶帖的发布时间后选取1秒窗口、最多一页，随后测试该作者资料与产品配置。无Cookie、无绕过验证，预算16次，实际11次；HTTP 200共9次，301共2次。

| 环节 | 实际结果 | 验收判断 |
| --- | --- | --- |
| 帖子 | 1篇入库，标题/正文、列表时间、阅读与回复数、作者侧栏计数等已取到；发布时间规范字段为空，问题为publication_time_unknown | partial，不可发布 |
| 用户 | 1条侧栏资料；三项平台计数和热门帖入口已入库，回复数0正确保留；源卡片未展示爱车，明确not_displayed | 主页两次均301，不跟随重定向，关注/粉丝/IP未取到，partial |
| 产品 | 9个配置，2,619条参数；任务返回succeeded | 仅当前参数任务成功；指导价、经销商价、厂商等未进入标准表，不能视作完整产品字段验收 |
| 存储 | 8表、11份原始快照，hash/FK/原始材料注册检查通过 | 测试库结构完整不代表业务字段完整 |
| 增量 | 检查点0条，没有推进 | 保守门禁有效；不证明月度覆盖或全量无遗漏 |
| API幂等 | 用户和产品的重复提交返回相同job_id，各只有1条任务记录 | 通过该范围；帖子重复响应未保存，不追认全链路幂等已验收 |
| 冻结回放 | 禁止外部socket，原业务数据未改变，重复回放数据未改变 | 2份有效响应报unversioned_processing_change，另2份301拒绝回放；回放验收未通过 |

## 测试脚本中断说明

首次执行在帖子任务完成后，测试脚本读取空result时报AttributeError。已仅修复测试工具空值处理，并在同一测试目录继续用户/产品分支，没有重抓帖子、没有修改生产解析/采集代码。总请求数包含中断前请求。初次unittest命令因缺少PYTHONPATH出现1个导入错误；补齐正确环境后79项全部通过，不把前一次失败隐去。

## 待修复，不能用补空或忽略错误替代

1. 定位真实帖详情的发布时间来源，明确与列表发布时间的优先关系，增加冻结样本回归。
2. 核对用户主页301目标，设计受白名单、次数与预算约束的跳转处理；不能任意跟随或宣称源站无资料。
3. 将产品索引中实际可得的元数据按统一字段契约落库，逐字段核验价格等；源站不提供的应逐项说明。
4. 定位两份有效响应的回放处理差异，修复后必须验证空库重建，不仅是在已有库上重复回放不变化。

未执行上述业务修复，未启动月度/全量任务，未进行人工语义验收。原9994篇存量库只读核对仍为9994，本次新帖不在该库。

## 证据与复现

- 实测库：`local-data/live-integration-20261021/data/db/ingestion.sqlite3`。
- 实测原始报告：`local-data/live-integration-20261021/verification.json`。
- 回放报告：`local-data/live-integration-replay-20261021/verification.json`，拒绝的响应和错误均保留。
- 工具：`../tools/smoke_live.py`、`../tools/verify_frozen_http.py`。
- 在线命令：`.venv/Scripts/python.exe tools/smoke_live.py --allow-network --integration --mcp-zip E:/Users/ASUS/Downloads/mcp.zip --output <新的输出目录>`。本轮中断后使用`--complete-existing`继续同一目录。
- 离线测试：PowerShell设置`$env:PYTHONPATH='src'`后执行`.venv/Scripts/python.exe -m unittest discover -s tests -q`，79 tests / OK。

环境：Windows、Python 3.11.9、stdlib-only；当前工作未提交，不虚构交付commit。微小窗口样本不代表源站所有页面或未来版本。

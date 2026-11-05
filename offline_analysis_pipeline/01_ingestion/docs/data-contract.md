# 接入契约：版本2八张表

api → jobs → collect / normalize → quality → storage，CLI复用同一核心。完整SQL以src/autoinsight_ingestion/storage/schema.sql为准，PRAGMA user_version=2。

| 表 | 键与用途 |
| --- | --- |
| posts | post_id；当前帖子、原文/清洗文、时间原值/精度/依据、有序片段JSON、帖子采集时作者资料JSON |
| users | user_id；当前资料，性别明示和推断分开，计数0有效，IP非居住地 |
| product_specs | spec_id；配置、车系与品牌元数据，不将猜想车型当量产事实 |
| product_parameters | spec_id+source_item_key；参数来源键、分组、名称与原值，不仅按名称合并 |
| source_snapshots | snapshot_id；raw相对路径、hash、采集时间、来源、解析配置与问题 |
| collection_runs | run_id；HTTP任务与CLI运行合一，幂等键/状态/配置/请求尝试JSON/结果 |
| collection_failures | failure_id；失败对象/页码/原因及pending/resolved状态 |
| collection_checkpoints | scope_key；成功检查上界与覆盖起点，不以存在ID或空白页推进 |

旧输入兼容映射在field_contract.py，统一标准投影在standard.py。未知字段拒绝，不静默吞列；记录保留快照、行/片段定位、处理版本及质量状态。作者五字段见author-fields.md。

原始材料先保存再解析；业务更新和解析状态同事务。原始文件内容寻址、不可变。较旧快照不回退已知较新值；未知时间冲突按显式来源优先级，不能用hash大小当时间。同源同版本处理发生差异拒绝，不静默更新。

相对日期只以保存的retrieved_at推算，缺锚点则未知；缺数值不填0。旧纯文本与独立图片列表不能证明原帖图文顺序。身份冲突拒绝，原材料仍保存。

每批质检不借用全库已填值掩盖新增批次空列；字段未展示与请求/解析失败分开。ready不代表人工语义接受，HTTP200不代表字段完整。

单数据根仅单进程写，操作系统锁自动释放，不手工删锁。恢复联网任务须显式请求，不自动月更。验证页/限流安全停止，不绕过。

当前迁移包保留实测失败：发布时间、用户主页301、产品元数据缺口、2份有效响应回放差异。不能将现有规则描述当全功能已经验收。

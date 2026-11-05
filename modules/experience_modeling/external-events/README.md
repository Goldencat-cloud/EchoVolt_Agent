# 外部事件抽取模块 v0.1.0

本目录是用于后续整合的独立外部事件模块，只输出 source_id 和 external_events，不修改或输出体验记录。参考既有体验 Schema 的原文证据、置信度和封闭字段风格。

## 文件

- external-event-record.schema.json：独立事件记录结构。
- extraction-output.schema.json：单来源的外部事件输出结构。
- system-prompt.txt：仅抽取外部事件的提示词。
- examples.json：六组虚构输入输出，覆盖降价、传闻、仅体验、条件假设、缺年日期及空结果。
- tests/test_external_events.py：离线结构验证。

## 字段与规则

必填 event_id、event_type、statement_type、description、evidence、verification_status、extraction_confidence；actor、product_ids、event_time 可选。

事件类型包括发布、价格调整、召回、软件更新、安全事故、政策法规、公司变化、生产交付、竞争市场、基础设施变化、天气灾害、other 和 unknown。statement_type 使用 reported、announced、planned、rumor、disputed、unclear，记录来源的表述性质。

verification_status 固定为 unverified。抽取置信度不是事实为真的概率，引用公告也不代表已经独立核实。个人维修不自动成为公共召回，日常冬季场景不自动成为天气灾害，个人条件假设不抽成已发生事件。

event_time 保留 raw_text、value 和 precision。精度为 year/month/day/datetime/unknown；缺年份或时区等必要信息时 value=null，不补午夜或用帖子发布时间代替事件时间。datetime 非空值需带时区偏移或 Z。

## 后续整合边界

体验抽取模块和本模块可以分别处理同一帖子，后续由整合方按 source_id 关联。此交付不改既有体验 Schema、输出结构或提示词，也不实现共同输出、跨帖事件去重、事件时间线适配及因果关系。

事件 ID 由流水线提供或生成；product_ids 只能引用输入给定且可靠消歧的实体。运行时还需检查来源 ID、原文连续引句及引用的实体，Schema 校验不能替代这些检查。

## 验证

安装依赖：python -m pip install "jsonschema[format]>=4,<5"

在本目录运行：python -B -m unittest discover -s tests -v

日期格式验证需显式启用 FormatChecker。离线检查验证结构和虚构案例，不调用模型、不处理真实语料、不证明事件真伪或抽取准确率。
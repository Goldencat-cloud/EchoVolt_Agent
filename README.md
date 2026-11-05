# AutoInsight

本仓库包含当前离线分析管道、独立研究模块及历史证据。数据仅限私有仓库受控使用。

| 目录 | 职责 |
| --- | --- |
| [offline_analysis_pipeline](offline_analysis_pipeline/README.md) | 当前迁移入口：采集、清洗、图片、V2.3抽取、归一、报告，包含SQLite与冻结数据 |
| [modules/external_events](modules/external_events/README.md) | 外部事件研究工具；独立模块，不接入当前采集/分析主线 |
| [modules/experience_modeling](modules/experience_modeling/README.md) | 体验建模Schema、Prompt与样例；独立参考模块 |
| [archive/legacy_pipeline](archive/legacy_pipeline/README.md) | 原collaboration内容，完整保留作历史证据，不作为当前迁移入口 |
| openspec | 当前需求、设计、任务与授权记录；不是通过率报告 |

新电脑从offline_analysis_pipeline/README.md开始。旧模块内部相对布局不变；历史文档里旧根目录名以此映射为准：collaboration → archive/legacy_pipeline，event-timeline-research → modules/external_events，experience-modeling → modules/experience_modeling。

本次没有删除历史内容，没有将研究模块接入主线，没有修复已知采集问题。旧文档中的版本结论及旧路径是历史记录，不代表当前运行配置；不要直接照历史绝对路径运行。当前采集仍未完整验收，详见迁移包实测报告。

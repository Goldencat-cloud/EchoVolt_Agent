# AutoInsight 离线分析管道迁移包

截至2026-10-21的开发交接快照。包含当前采集模块、SQLite及原始材料、后续历史处理模块和现有分析结果。不是已经贯通验收的新生产流水线。

只需迁移本文件夹；运行时不依赖原工作区、旧盘符、MCP或旧虚拟环境。**不等于零运行条件**：核心与迁移工具需Python 3.11；旧图片/模型/前端模块另有依赖，学校服务器的设备准入不能随代码迁移。

## 目录

| 目录 | 内容与状态 |
| --- | --- |
| 01_ingestion | 当前HTTP API、采集/解析/质量/SQLite存储、配置、79项离线测试；真实测试未完全通过 |
| 02_cleaning | 交接包中的清洗源代码；历史参考，尚未适配新版SQL作为输入 |
| 03_media | 图片下载/策展脚本、AUTO006图片抽取、AUTO007结果、AUTO008整合代码及冻结产物；原图本体未纳入 |
| 04_extraction | V2.3完整Prompt、契约、全量/repair脚本、冻结输入和最新结果；非自动重跑入口 |
| 05_normalization | 当前taxonomy V2/delivery-r3及必要V1辅助代码、锚点和配置；V1不是并列分析版本 |
| 06_reporting | 现有离线报告、分析代码、统计产物、前端源码及静态页面；不是新SQL库分析报告 |
| data | stock与live_test两套SQLite及关联raw快照；历史元数据和配置/用户参考文件 |
| docs | 质量证据、依赖边界、相关OpenSpec参考；根仓库OpenSpec仍为唯一需求源 |
| tools | 本包构建工具；日常迁移使用根目录manage.py |

压缩文件是明确登记的存档，不是假装可以直接读取的JSONL。`bundle-manifest.json`给出相对挂载、原始来源及哈希；`FILES.sha256.json`给出本包文件校验。历史报告中的原盘符仅为当时来源记录，不作为新运行入口。

## 新电脑先做这三步（不联网）

从私有GitHub仓库取得本次交接分支（不要只下载main里的旧材料）：

```powershell
git clone --branch change/auto-021-data-ingestion --single-branch https://github.com/Goldencat-cloud/comments_decisions.git AutoInsight
cd AutoInsight/offline_analysis_pipeline
```

在本文件夹打开终端，使用Python 3.11：

```powershell
python manage.py verify
python manage.py test-ingestion
python manage.py prepare
```

prepare只在**全新**`runtime/workspace`内解压/复制数据和组装旧模块所需的相对布局，不修改已保存产物，不采集、不调用Qwen。可用`--workspace "D:/AutoInsight Runtime"`改到任意新路径。目录已存在会拒绝，避免覆盖。目录准备后可执行`python manage.py check-data`检查两套库及raw哈希。

代码在GitHub中按阶段组织；旧脚本在运行目录内保留它们必要的相对布局。这是显式迁移兼容层，**不是两份可独立维护的源代码**；修改源模块后应重新构建到新运行目录。

## 数据不能混淆

- `data/stock/db/ingestion.sqlite3`：历史材料按新契约导入后的存量，9994帖、5355用户、9配置、2411参数。不是本轮在线新爬的9994帖。
- `data/live_test/db/ingestion.sqlite3`：最近真实测试，1帖、1用户、9配置、2619参数，任务partial问题保留，不能合并冒充通过数据。
- 新增127帖已从stock标准posts表排除；不可变原始CSV快照仍可能包含这些行，用于溯源，不是获准分析的记录。
- V2.3分析输入是历史9701帖集合，9529通过、172失败；不是stock的9994帖。数据集之间禁止按数量或标题直接拼接。

SQLite可直接用数据库工具查看。要用采集程序检查/回放，请使用prepare后的`runtime/workspace/data/stock`，它带有解压后的raw，而不是只复制一个数据库文件。

## 暂停点与真实依赖

最新真实测试尚有：详情发布时间未解析、用户主页301、产品价格等元数据未入库、两份有效响应回放不一致。见[实测报告](docs/evidence/live-integration-20261021.md)。本次只整理迁移，未修这些业务问题。

下游模块迁入不代表已适配新版SQL；默认继续消费冻结历史产物。模型抽取需要重新配置服务和设备授权，不复制Cookie、学校凭证、API密钥、个人settings或.env。图片原件/模型权重未纳入，无法只靠本包重跑完整图片链。Docker未构建，未验证第二台物理电脑。

仓库包含论坛原文和用户资料，**仅限受控私有仓库**；不要公开、发布为网站或转成公开Release。依赖及命令见[运行说明](docs/RUNNING.md)。

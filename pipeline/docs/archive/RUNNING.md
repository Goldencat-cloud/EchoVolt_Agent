# 运行条件与续接

## 核心模块

Python 3.11（已测3.11.9），零第三方依赖；不复制旧.venv，不需要MCP、Qwen或Docker。新环境可直接运行`python manage.py test-ingestion`。核心业务入口在01_ingestion/run.py。

prepare后，在本包根目录启动本机服务（默认不允许网络采集）：

```powershell
python 01_ingestion/run.py serve --data-root runtime/workspace/data/stock --port 8876
```

不建议在当前交接状态启用新的在线任务，应先修实测报告的四项问题。月度计划未启用。

## 历史下游

旧模块尚未统一为新SQL输入，因此通过prepare生成的workspace运行。它们保留现有算法和输出口径，不在迁移时重写算法或重新作结论。

- 清洗/CLIP/图片脚本：源代码在02_cleaning、03_media/handover；依赖可包含pandas、requests、Pillow、torch、transformers等，以实际脚本import为准。GPU/模型权重、原图未打包，依赖尚未锁定，不能声称全链无依赖可复现。
- AUTO006图片模型调用与V2.3抽取：依赖模型服务，部分脚本需jsonschema/Pillow。本包不发API请求、不安装依赖。配置文件在工作目录local-config（不入Git）；先在新设备验证学校准入，再单独明确任务、预算与调用授权。不要直接执行full/rerun/repair主函数来试迁移。
- 归一：prepare后可先运行`python runtime/workspace/collaboration/result/auto018-product-entity-normalization/v2/test_taxonomy.py`，21项纯离线边界测试。完整重算需要显式新output，不能覆盖delivery-r3。
- 报告：已有Markdown与静态构建目录可阅读；源码重建需Node/npm及package-lock.json对应依赖，不包含node_modules。分析脚本原设计拒绝覆盖已有analysis；如要重算，应先在全新工作目录调整输出位置，不删除冻结结果。

原始模型调用过程的每条HTTP记录并未全部打包；保留最新结果、冻结输入、Prompt/schema与关键上游状态。不能仅凭结果文件重新证明模型服务的当时行为。

## 规范

根仓库`openspec/changes/auto-021-data-ingestion/`为当前模块要求、设计与任务。docs/reference中的其他Change是历史上下文，不在此维护第二份需求。用户已授权迁移与GitHub上传，不等于人类代码验收或PR合并。

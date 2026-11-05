# AutoInsight 数据接入

一个本机 HTTP 服务，内部包含帖子、用户、产品采集及基础清洗、质量检查和存储。无 MCP、模型调用、消息队列、分布式调度、画像统计或配置对比工具。运行时仅依赖 Python 标准库。

当前为 AUTO-021 工程初版，不是已验收的全量采集服务。特别是帖子未知终页/未知正文模板会显式保留 partial/failed，不承诺无漏采。真实页面适配结果见 evidence/ 下验证记录。

## 快速运行

实测解释器：CPython 3.11.9；工程要求 Python 3.11。建议独立环境：

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install --no-index --require-hashes -r requirements.lock
./.venv/Scripts/python.exe tests/run_suite.py --report evidence/unit-tests.json
./.venv/Scripts/python.exe run.py serve --data-root ./var/service --port 8876
```

Linux 使用 `.venv/bin/python`。`run.py`只设置源码导入路径，其余入口都复用包内核心。导入Python模块不启动服务或请求网络。源码、数据和凭证分开；不需要学校Qwen访问资格。

## 四个 HTTP 接口

默认只绑定127.0.0.1，不允许浏览器Origin或任意Host，不提供公网使用。可设置运行环境变量 `INGESTION_API_TOKEN` 开启Bearer认证；不要把真实值放进仓库、源码或截图。

| 方法与路径 | 行为 |
|---|---|
| POST `/v1/ingestion/jobs` | 202登记任务并返回job_id；需要Idempotency-Key |
| GET `/v1/ingestion/jobs/{id}` | 状态、错误代码与汇总，不返回原文/凭证/内部文件路径 |
| POST `/v1/ingestion/jobs/{id}/resume` | 显式恢复失败、中断、取消或partial任务 |
| POST `/v1/ingestion/jobs/{id}/cancel` | 事务/请求安全边界取消，保留已提交结果和原始材料 |

相同幂等键/配置返回同一任务；同键不同配置409。未知任务404，非法输入400。服务重启不会自行恢复网络任务。单服务、单后台worker，SQLite写入串行；没有新增队列服务。

离线导入的来源必须由运维人员在server端注册，例如将以下内容保存为自己的sources.json；路径相对该配置文件，HTTP请求不能提交文件路径：

```json
{"posts-snapshot":{"path":"exports/posts.csv","kind":"posts"}}
```

启动时增加 `--sources sources.json`。提交体为 `{"source":"posts-snapshot","config":{"kind":"posts"}}`。产品参数来源还需注册并在配置显式给出series_id。

联网额外要求服务启动时 `--allow-network`，以及每个任务配置 `mode=collect`、`allow_network=true`、非零max_requests。两层许可任一缺失都拒绝。目标由程序固定URL模板生成，不接受任意URL：

```json
{"config":{"mode":"collect","kind":"posts","series_id":"6962","start":"2026-10-01","end":"2026-10-21","max_pages":2,"max_requests":5,"max_attempts":1,"allow_network":true}}
```

用户任务使用kind=users及顶层`user_ids:["源站ID"]`；产品使用kind=product_json及显式series_id。不支持按模糊名称自动选择车系。示例仅解释契约，不是全量采集授权。

## 离线导入、回放、备份

以下为命令形式，输入替换为实际文件；运行数据根应使用新目录，不能指向仓库根或其他非空目录。

```powershell
python run.py import-legacy --data-root ./var/import --input posts.csv --kind posts
python run.py import-legacy --data-root ./var/import --input package.zip --member path/in/archive.csv --kind users
python run.py replay --data-root ./var/import --response-id <导入返回的response_id>
python run.py verify --data-root ./var/import
python run.py export --data-root ./var/import --output ./posts-ingestion.jsonl
python run.py export --data-root ./var/import --output ./posts-ingestion.csv --format csv
python run.py backup --data-root ./var/import --output ./var-backup-01
python run.py restore --input ./var-backup-01 --data-root ./var-restored-01
```

replay支持历史CSV/产品JSON和已支持的HTTP帖子/用户/配置响应；论坛列表及车型索引只验证结构，不伪造业务记录。未识别HTTP类型明确拒绝。同任务resume重扫列表，不依赖旧列表缓存。

`--retrieved-at`只用于有证据的历史采集时间，不要填导入当天。原始字段“3天前”按该页面保存的采集时间推算，保留日精度；没有锚点则未知，重放时不读取当天日期。

数据根内只有db/、raw/sha256/和writer.lock；无Download或旧Excel隐式依赖。backup生成新目录，restore拒绝覆盖已有目录。数据库用一致备份；逻辑导出稳定，不要求SQLite文件逐字节相同。

## 三层结果

- 原始层：响应/历史文件字节及哈希，只读保留。ZIP成员直接读取，不执行包内脚本。
- 标准层：当前posts、users、product_specs、product_parameters，片段存JSON；来源与运行等另有4张表，总共8张，不维护实体/观察多层表。
- 质量层：ready/review_required/rejected及问题代码。ready仅为已实现基础规则通过，不是人工语义验收。

图片本体不在本模块下载；这里只保存资源引用与顺序。旧版纯文本全文标记media_order_unknown，不补造插图位置；来源疑似广告、表达重复等不自动删除。原始数据可能包含个人信息，本工程数据及备份仅限受控本地使用，不默认脱敏可公开。

## 当前边界

- 不自动月更、不推进未经证明的覆盖检查点、不声称完整召回；站点列表空响应按异常待审处理。
- 网络任务resume重扫列表，仍受本次请求预算控制；离线replay才使用冻结材料。标准层源ID去重与HTTP任务幂等各有独立含义。
- 网络采集尚无Cookie/认证注入实现；遇到认证/限流安全停止，不尝试绕过。网络失败不伪装空数据。
- 网络适配串行执行，workers字段暂为预留配置，首版请保持1；尚未交付并行采集承诺。
- Docker当前环境缺失，容器构建与跨电脑验证未完成，不提供一个未经验证的“可部署”镜像。

工程依据见 AUTO-021 OpenSpec；数据字典及规则见 [docs/data-contract.md](docs/data-contract.md)。

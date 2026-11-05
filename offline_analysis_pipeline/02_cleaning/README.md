# 02_cleaning 语料清洗模块（auto-022）

对 stock 库 9994 帖做确定性清洗标注，产出供 B 阶段（抽取/索引）直接 SQL 消费。
Python 3.11 **stdlib-only**（零第三方依赖）；只读业务表，写仅限标注表。

## 运行

```powershell
# 推荐：pip install 后用入口脚本
pip install -e offline_analysis_pipeline/02_cleaning
autoinsight-cleaning --db offline_analysis_pipeline/data/stock/db/ingestion.sqlite3

# 等价：直接跑（无需安装）
python offline_analysis_pipeline/02_cleaning/tools/run_cleaning.py \
    --db offline_analysis_pipeline/data/stock/db/ingestion.sqlite3

# 只算不写（校验/预览）
... --dry-run
```

输出为 JSON 统计（锚点复算、excluded 分布、水军计数、别名统计）。锚点漂移 >5 时
exit code = 2，可用于 CI 断言。测试：

```powershell
python -m unittest discover -s offline_analysis_pipeline/02_cleaning/tests -p "test_*.py"
```

## 产出（全部在 stock 库内，无 CSV）

| 对象 | 用途 |
| --- | --- |
| `cleaning_annotations` | 每帖一行标注：excluded / norm_key / dedup / polished_text / polished_multimodal / text_changed / spam_suspect / spam_reasons_json |
| `v_clean_subset` | 高置信子集视图（B 阶段主入口） |
| `product_aliases` | 产品别名 → 规范链（品牌/车系/配置），抽取提及回溯 |
| `v_alias_resolved` | 别名解析视图（人读） |

## 部署注意

- **单写者**：SQLite 单写者模型，勿并发运行多个清洗进程；业务只读，可与读共存。
- **幂等**：同 `cleaning_version` 同输入 → 同输出，可随时重跑；版本变更直接整表替换
  （`post_id` 主键，历史版本不留存，需要留存先备份标注表）。
- **人工决定保留**：`product_aliases` 中人工 confirm/reject 的行重跑不覆盖；
  official/variant 仅新增不删改。
- **基线**：输入基线为 legacy-4 重导后的 stock 库（9994 帖）；采集侧数据变更后重跑，
  锚点复算需重新解释（见 docs/evidence/）。
- 证据与实测报告：`docs/evidence/cleaning-run-20261022.md`；
  字段契约与规则明细：`docs/data-contract.md`；旧列映射：`docs/field-mapping.md`。

## 结构

```
src/corpus_cleaning/   contracts(规则常量) polish(净化/归一) annotate(剔除/去重)
                       spam(水军嫌疑) aliases(别名映射) store(建表/落库) pipeline(主管线) cli
tools/                 run_cleaning.py（CLI 包装）、inspect_*.py（人工抽查脚本）
tests/                 59 项：单元 + 真实库副本集成（锚点/只读边界/确定性重跑）
docs/                  data-contract / field-mapping / evidence
```

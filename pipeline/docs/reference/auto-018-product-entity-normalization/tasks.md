# Tasks

## 1. 数据整理

- [x] 1.1 冻结两个源文件哈希，验证帖子、局部产品键和配置表分组的一致性，保存 manifest/checks。见 v1/final/manifest.json 与 checks.json。
- [x] 1.2 生成独立 canonical-entities、mention-mapping、alias-mapping 与 claim-product-links；检查覆盖、外键、层级及原始字段不变，留存分析代码与 notebook。脚本已实际运行，notebook 留作未执行的同源伴随文件。
- [x] 1.3 按配置表关联可唯一证明的 specid，保留猜想图排除原因、未覆盖和不充分证据状态，验证无猜想图或未知年款的精确配置关联。165 个提及映射到 7 个 specid。

## 2. 歧义辅助与交付

- [x] 2.1 对最多 20 个高频歧义原名准备显式 Qwen 包，dry-run 后调用一次；核对 result.json 和 response，保存 Codex 逐项复核，不自动接受或重试。实际 16 项、5899 tokens；格式解码 FAILED，无映射被应用，保留 codex-review.json。
- [x] 2.2 生成 CSV/JSONL、HTML 复核页、报告和文件清单，验证可解析性、分页/搜索/标注导出及哈希；运行本 Change 严格校验与差异检查。见 design.md 验证记录及 v1/README.md；不代表人工语义验收。

## 3. V2 taxonomy 与语境归一

- [x] 3.1 构建品牌/车系/明确配置 taxonomy 和最深节点映射；保留版本、年款等属性，用测试验证 null 属性不新建实体、父节点与 specid 唯一。见 v2/normalize_taxonomy.py、test_taxonomy.py 与交付 checks.json。
- [x] 3.2 引入显式版本化别名和论坛/标题/同帖消歧，覆盖酥妻、速七、毛豆3、只说 SU7/Max 与明确金彭/尚界等反例；测试明确竞品不被默认语境覆盖，并全量生成独立 V2 结果。21 个边界测试通过；保留每条映射依据与原始字段。
- [x] 3.3 生成 taxonomy 浏览/提及复核页、CSV/JSONL、V1 对照和验证报告；检查全覆盖、原数据哈希、层级去重计数、搜索筛选与标注导出，再运行 OpenSpec 严格校验。当前交付 v2/delivery-r3，验证见 v2/verification.json 与 design.md；语义人工验收待做。
- [x] 3.4 调研实体归一后的分析路线，回查现有 Claim、人群、场景和比较字段，结合一手方法资料给出分阶段分析目标、产物与质量门；不自动启动新实验。见 v2/next-analysis-research.md 与 analysis-readiness.json，已核查 VoC 原刊摘要、主题分析作者网站正文和 BERTopic 官方资料。

## Workflow follow-up

- 人类复核映射语义、配置别名和规则；规格审阅记录、正式交付验收与未来业务接入仍待记录。
- 如需业务化，实现前按项目规则建立专用开发分支和交付 PR，不直接将本次离线材料视为已批准业务实现。

# Implementation tasks

本清单全部是未来工作，不表示已实施。前提是人类Owner批准proposal/spec/design，并记录审阅人、日期、审阅commit、verdict及未决项；在独立开发分支／隔离工作区执行，不移动当前dirty工作树，不修改AUTO-016/017/018源契约与产物。各任务完成须有实际文件、测试输出和局限记录，不能以checkbox替代证据。

## 1. 固定契约、范围与版本

- [ ] 1.1 在schemas/forum-evidence-model/1.0/实现六类实体及配套记录Schema，固定18方面编码、空值、原枚举与必填规则；以最小有效fixture和每类无效字段用例验证，并记录字段对照说明。
- [ ] 1.2 在configs/forum-evidence-model/落地批准后的产品scope、8个属性种子与证据规则；验证重复编码、无效父节点、环、错误allowed_value_types均被拒绝，文档标注配置版本和人类批准来源。
- [ ] 1.3 实现dataset/run/record ID及内容哈希规则；测试局部C1/P1跨帖不碰撞、同输入重跑ID一致、输入／配置变化生成新run、代码变化未升adapter版本被阻止，并给出可复算样例。

## 2. 无损源适配与证据定位

- [ ] 2.1 实现source_files/snapshots/source_records与V2.3根对象适配，保存原payload、JSON pointer和行定位；fixture逐字段重建九个根字段且源哈希前后一致，Schema漂移返回E_SCHEMA_DRIFT。
- [ ] 2.2 实现User/Post及post_contexts适配，保留平台账号边界、时间raw值与时区假设；测试缺用户键不合并为同一账号、主页规范化规则、未知采集时间不填导入时间，并补充隐私说明。
- [ ] 2.3 实现Claim/Event及局部引用，原类型与作者／模型断言不提升为事实；验证跨帖同名局部ID、原事件关系和产品角色可回溯，跨帖误连报E_CROSS_POST_REF，缺目标报E_FK。
- [ ] 2.4 实现Evidence及按owner拆分的连接表；以exact、normalized、segmented、mismatch、missing_source和Unicode定位fixture覆盖状态，测试有序省略片段不伪装连续引文，保留旧contract结果并说明新查询门的差异。

## 3. 产品目录、配置、比较与用户状态

- [ ] 3.1 适配AUTO-018映射与Product父链，保留source_node_id及scope/mapping两套状态；测试“酥妻”已有归一的复用、未知词、范围外已知车型、品牌级提及，不将范围外车型降成品牌冒充命中。
- [ ] 3.2 实现可选配置表导入与product_property_values，保留行号、raw值、冲突及pending_dictionary；测试猜想图specid排除、未明年款不匹配配置、类型化值最多一个、子配置值不无条件继承到车系，并核对输入行去向。
- [ ] 3.3 实现comparison_records，保持每条原relation的主体／客体／方向／证据及comparison_id；反例测试多个参与产品不生成笛卡尔积，逆向重复只标记、跨帖异议不判结构错误，文档提供配对样例。
- [ ] 3.4 实现user_product_contexts及证据绑定，未知对象留空；用“拥有A3但试驾SU7”、租借、已售、意向购入反例测试，不由论坛或主要讨论对象补所有权，严格人群无法通过未接受记录进入。

## 4. 属性标注与实际人类复核接口

- [ ] 4.1 实现property_annotations及annotation_gaps，支持显式源信息／分析推导区分；测试一条标注只绑定一个Claim、目标、属性及同帖证据，混合评价不复制情感，不从粗aspect自动填细属性，空标注输出明确缺标计数。
- [ ] 4.2 实现review_decisions导入和review_state派生；测试真实reviewer、target_record_hash、时间及适用项校验，内容改动使旧accept失效，Codex／规则输出不能自动成为人类接受，并提供复核文件模板。
- [ ] 4.3 生成固定seed的最多200条定向复核包及已知反例集，按design G5输出候选／不足／重叠／unique claim-post计数；同输入抽样可复现，不足不补造，不调用模型补量，输出待人类填写而非伪造接受结果。

## 5. 存储、图投影与CLI

- [ ] 5.1 实现SQLite表、同run主外键、事务及统一issues接口；用每种error码fixture验证发布被阻止，警告记录保留，构造多目标／多证据样例验证连接不放大Claim计数，并文档列出实体与物理表区别。
- [ ] 5.2 实现JSONL与nodes/edges投影，保持comparison_id、提及角色、事件关系限定及证据回链；逐键对账测试无悬空边、无全局BETTER_THAN/CAUSES/OWNS、不生成Aspect节点，公开投影不含昵称主页或raw payload。
- [ ] 5.3 实现build/validate/query入口和只读dry-run；测试dry-run零写入／零网络、输出存在拒绝覆盖、源变更拒绝、失败暂存保留、验证后原子rename，并提供CLI复现与切回旧run说明。

## 6. 六个离线验收查询

- [ ] 6.1 实现raw/exploratory/strict三种查询门和排除原因统计；测试segmented的默认处理、部分证据披露、strict缺人类接受合法返回空，不悄悄降级口径；README明确探索结果不等于核实事实。
- [ ] 6.2 实现Q1方面情感及Q2属性线索，输出distinct Claim/Post、固定分母、缺标率和证据引用；以手算fixture独立核对，测试一帖多Claim、多属性及中性／混合／不明确对分母的影响。
- [ ] 6.3 实现Q3对象限定人群及Q4定向比较，输出上下文／接受状态与有效比较对；用他车车主试驾反例、未知对象、反向比较及空strict集核对结果，并保留源引文。
- [ ] 6.4 实现Q5同配置参数与评价对照、Q6事件提及时间线；测试车系与配置不混算、配置冲突并列、事件时间未知不取帖时间补齐、不输出因果关系，六种输出均带run/scope/dictionary与排除计数。

## 7. 全量集成与工程交接

- [ ] 7.1 在冻结输入上执行只读dry-run，再构建独立离线包；以manifest逐键检查G1–G3，报告帖子／Claim／提及／配置行的保留及隔离去向、源哈希与第二次ID一致性，不将历史报告数字当作本轮测量。
- [ ] 7.2 执行Q1–Q6与反例回归，保存命令、实际输出、独立计数对账和G4–G6状态；尚无人类复核则明确strict未完成，属性不足如实报告，不声称总体语义准确率或人群身份已核实。
- [ ] 7.3 整理受限数据包manifest、Schema/字段说明、测试日志、复现命令、查询样例、限制与回滚指南；核对只有本Change允许文件被改动，按Branch/Commit/检查结果/剩余项交接为REVIEW_READY而非人类已验收。

## Workflow follow-up

- 人类Owner审批本提案并记录审阅commit；批准前不能开始以上实施。
- 人类填写定向复核包及数据语义接受意见；这是外部接受流程，不把它勾为Codex已完成实施任务。
- GPT建议审查、人类代码审查、唯一交付PR、合并与Owner接受分别记录，不自行批准或合并。
- 交付PR合并且Owner接受后，另以维护Change执行正式spec同步／归档；本轮不执行。

## 8. Authorized pilot（2026-10-19用户确认，仅此组可先实施）

以下是独立探索验证，不代表上文24项完整实施获批或完成。提案修订已获用户确认；资料快照正式适配也须在后续正式模型中按5.1a落实。

- [x] P1 在隔离工作区实现只读全量试建与user_profile_snapshots，保留范围外提及、原比较和局部事件，不新增细属性或车主认证；导出nodes/edges/support JSONL及manifest，并以源hash、逐键计数、重复/悬空/跨帖检查和边界单元测试验证。
- [x] P2 实现本地交互预览，按帖子/产品筛选，最多80节点逐次展开，点击可查看观点情感、映射、证据与资料快照；测试筛选、详情和截断提示，默认不显示昵称主页及数字原账号ID，无外部上传或依赖。
- [x] P3 两次独立构建校验稳定节点/边和输入hash，保存实际测试、浏览器验证、数量和限制，记录试建交接；不把未实现的正式Schema/SQLite/Q1–Q6/strict门标为完成。

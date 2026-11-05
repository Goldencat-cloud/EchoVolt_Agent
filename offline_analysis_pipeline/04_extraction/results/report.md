# AUTO-016 V2.3 全量契约失败修复与定向重跑报告

## 结论

原全量运行共 9701 帖，其中 9147 条通过本地 V2.3 契约、554 条失败。本轮没有改写原始运行目录，也没有重跑原通过记录。

- 188 条失败记录经确定性白名单修复后通过：仅涉及 Unicode 空白/标点格式差异、唯一证据 block 错挂或可由冻结身份链证明的 post_id 抄写错误。
- 其余 366 条各显式重跑一次；194 条通过，172 条仍失败，没有自动二次请求。
- 最终 9529/9701 条通过程序契约，172 条保留失败；通过率为 98.23%。这不是语义准确率，也不表示人工验收完成。
- 9701 个 post_id 覆盖完整且唯一；原 9147 条通过记录在合并文件中逐字节不变；原始关键文件和 554 个失败调用文件的快照哈希复核一致。

## 剩余失败

172 条剩余失败按记录计数如下；类别可重叠：

| 类别 | 记录数 | 说明 |
|---|---:|---|
| evidence_quote | 153 | quote 仍为改写、字符缺失、跨句拼接或无法唯一回挂的证据 |
| comparison | 13 | 比较对象不存在或比较关系自指等 |
| unknown_reference | 4 | claim/event 引用了未生成的产品对象 |
| incomplete_response | 4 | 再次达到输出长度上限，`finish_reason=length` |

本轮没有 API 传输失败。历史 25 条传输/JSON失败在重跑后均获得响应，但其中部分随后因内容契约失败而继续保留失败。

## 成本与边界

- 重跑请求：366 次。
- prompt tokens：4,160,788，其中服务端报告 cached prompt tokens 为 3,460,672。
- completion tokens：946,525。
- total tokens：5,107,313。
- 模型、Prompt、Schema、temperature、thinking 和 max_tokens 均沿用冻结配置；并发为 3。
- 没有拆帖、压缩 Prompt、删除语义字段、替换样本或放宽未知引用/比较关系契约。

## 主要证据

- `manifest.json`：554 条失败记录的原错误、处理决策、输入和原始文件哈希。
- `original-snapshot.json`：原运行关键文件及失败调用文件哈希。
- `repaired/`：188 条确定性修复 payload。
- `calls/`：366 条单次重跑的 raw response、result 和 local review。
- `resolutions.json`：逐帖修复规则或重跑后的最终状态。
- `merged-all-results.jsonl`：9701 条最终状态清单。
- `contract-passed.jsonl`：9529 条通过程序契约的 payload。
- `progress.json`：最终汇总。

## 未验证项

程序契约只证明 Schema、引用回挂、ID/枚举及关系约束通过；尚未测量人工语义准确率、实体归一化准确率、观点归属准确率或下游分析结论可靠性。172 条失败不得进入契约通过集合。

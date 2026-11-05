# kernel 等价性 fixture 格式

每条 fixture 记录"输入 + 账本 + 旧实现的响应"，用于 `test_kernel_equivalence.py`
的回放比对。录制器在 `tests/kernel_fixture.py`，生成脚本是
`tests/make_kernel_fixtures.py`。

## 字段

| 字段 | 类型 | 含义 |
|---|---|---|
| `id` | string | 用例标识，等于文件名（`case-01.json` → `case-01`） |
| `source` | `synthetic` \| `live` | 账本来源（见下方"来源分级"） |
| `note` | string | 该用例覆盖的形态，`synthetic` 必填 |
| `input.question` | string | 用户问题 |
| `input.history` | array | 多轮历史（当前均为空） |
| `input.session` | object | 会话上下文（筛选、上一轮结果等） |
| `steps` | array | 该轮进入 `verified_steps` 的条目 |
| `final_text` | string | 模型最终文本 |
| `expected` | object | **旧实现**在同一账本下产出的响应字典 |

`steps[]` 的结构与生产一致：`kind`（`method`/`overview`/`evidence`）、可选
`aspect`/`method`、`result`（映射或 `null`，`null` 用于验证容错分支）。

## 来源分级（重要）

- **`synthetic`**：账本条目为构造数据，模型调用被替身替换。它只能证明
  **胶水与派生等价**（上下文装配、工具白名单、字段映射、去重、限流），
  **不能**证明统计正确性。
- **`live`**：真实模型 + 真实冻结快照。当前仓库缺少快照数据
  （`06_reporting/agent-kb/output/data-version.json` 不存在），因此**尚无此类条目**。
  补齐方式：数据就位后用同一录制器跑真实问题，把 `source` 标为 `live`。

## 约定

1. **不得内联真实凭据**：`expected` / `steps` 里只允许出现示例域名
   （`example.invalid`）与脱敏 ID。
2. **不得手工编辑 `expected`**：它必须由录制器产出。手改等于让基准服从实现，
   等价性验证随即失效。
3. **新增用例**：在 `make_kernel_fixtures.py` 的 `CASES` 里追加元组并重跑脚本；
   不要直接写 JSON。
4. **覆盖要求**：新增能力时必须同时补"有工具"与"无工具"两类用例，以及对应的
   失败/异常形态（例如 `result: null`）。

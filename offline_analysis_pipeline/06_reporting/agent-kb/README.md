# Agent 知识库构建模块

将 `../analysis/` 冻结分析数据转换为双投影报告：人类阅读版 `output/report.html`（单文件、离线可打开）与机器可读版 `output/report.md`（Agent 问答接地语料）。两份成品由同一答案册 `output/numbers.json` 填数，数字一致性由门禁脚本强制。当前为 auto-023 第一阶段临时版，数据为上一版本产物，未经评审验收。

## 目录

```
configs/    人工维护：content.json（章节注册表）、template.html（版式解剖学）、agent-policy.md（Agent 策略块）
src/report_kb/  构建代码：builder（答案册+图+Agent版）、render（人类版渲染）、verify（一致性门禁）
output/     生成产物：report.html / report.md / numbers.json / data-version.json / assets/
docs/       数据契约与口径
evidence/   构建与校验运行记录
```

## 运行

实测解释器 CPython 3.13（要求 ≥3.11）；仅依赖 Python 标准库。

```powershell
python run.py all      # build → render → verify，任一失败即中止
python run.py verify   # 只跑一致性门禁（退出码 0=通过）
```

输入为 `../analysis/` 冻结文件（只读）；输出全部落在 `output/` 与 `evidence/`，不回写上游。

## 变更方式

- **换数据**：上游新数据落位 `../analysis/` → 重跑 `python run.py all` → 人按构建差异复核叙述结论。
- **改章节**：编辑 `configs/content.json`（增删章节、调整块序），模板与渲染器核心不动。
- **改版式**：编辑 `configs/template.html`（版式解剖学），不写入任何章节标题或数字。

## 边界

- 不修改 `../analysis/` 冻结数据与 06_reporting 下旧版报告资产（只读）。
- 数字唯一来源是构建期计算的答案册；两份成品不允许手写数字。
- Agent 策略（口径/拒答/回答模板）在 `configs/agent-policy.md`，随构建注入 `output/report.md`。
- 联网采集分析不在本模块范围；问答 Agent 与自动产出流水线属后续 Change。

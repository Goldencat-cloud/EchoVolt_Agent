# Contributing to AutoInsight

## 共享事实与职责

需求与变更仅使用 OpenSpec `spec-driven`。正式要求在 `openspec/specs/`；提案和实施中的要求在 `openspec/changes/<change-id>/` 的 `proposal.md`、`specs/`、`design.md`、`tasks.md`。GitHub Issue 只关联 Change、背景和审查讨论，不复制需求正文或另设任务清单。

每项 Change 指定**一名人类 Owner、一个开发分支、一个交付 PR**。多人或多个 AI 可贡献同一 Change，Owner 负责范围、接口和整合；人类成员也可独立维护各自 Change。ChatGPT 提供规划和审查建议，Codex 负责实现、集成、测试与 Qwen 调度，Qwen 在明确边界内执行，最终批准与合并由授权人类负责。

## 获取项目

需要 Git、Node.js >=20.19.0 和 OpenSpec 1.14.1。Qwen Code 仅对使用 Qwen 的成员需要，本机已验证版本为 0.22.3；本次没有配置其模型凭证或验证模型调用。

GitHub URL 提供后，成员从共享远端获取仓库和 Change 分支：

```powershell
git clone <repository-url> AutoInsight
cd AutoInsight
git fetch origin
git switch --track origin/change/<change-id>
npm install -g @fission-ai/openspec@1.14.1
openspec --version
openspec list
openspec show <change-id> --type change
openspec validate <change-id> --strict --no-interactive
```

模板中的 `<...>` 要替换为实际值。生成的 Codex/Qwen 技能与命令已经提交，clone 后无需重新 `openspec init`；CLI 安装是每名成员的本机步骤。若工具暂未识别新增技能/命令，应重新加载或重开工具会话，并读取生成文件；实际工具 UI 加载状态需要在各自环境确认。

## 从提案到 PR

1. **确定 Owner 与范围。** 先读取现有正式 specs、相关 Change 和实现，避免重复提案。从最新 `origin/main` 建立 `change/<change-id>`；本地尚无 main 的初始化状态不代替后续远端分支策略。
2. **创建原生 Change。** 终端运行 `openspec new change <change-id>`，然后按依赖顺序分别运行 `openspec instructions <artifact-id> --change <change-id>`，将 `<artifact-id>` 替换为 `proposal`、`specs`、`design`、`tasks`，起草四类 artifacts；或在相应 AI 工具使用下表中的 propose 技能/命令。
3. **完成规格审查。** proposal.md 写明 Owner、Change ID、分支、关联 Issue/PR；记录规格审阅人、日期、审阅 commit、结论与未决项。GPT 先辅助检查方案，人类 Owner 与受影响成员批准必要规格、接口和验收条件后才开始业务开发。CLI 校验通过不等同规格批准。
4. **实施与持续更新。** Codex/成员按 tasks.md 工作；Qwen 只接收指定任务和文件。需求或重大设计发生变化时同步更新 OpenSpec，再审查受影响部分。tasks.md 只有在工作完成且验证可定位后才勾选。
5. **验证并交接。** 执行规格检查及与业务改动相关的测试，记录命令、环境、结果和未验证项；写回 Change 的 design.md 验证记录。将 proposal.md 状态设为 `REVIEW_READY`，等待 GPT 和人类审查。
6. **提交唯一交付 PR。** PR 关联 Change 和 Issue，说明需求摘要、测试结果与风险。人类审查 AI 生成代码；所有必需 CI 通过且未决问题关闭后，由授权维护者合并。main 不接受未经审查的直接修改，AI 不自行合并。

| Action | Codex | Qwen Code |
|---|---|---|
| 探索 | `$openspec-explore` | `/opsx-explore` |
| 提案 | `$openspec-propose` | `/opsx-propose` |
| 修订 artifacts | `$openspec-update-change` | `/opsx-update` |
| 实施 | `$openspec-apply-change` | `/opsx-apply` |
| 已交付要求同步 | `$openspec-sync-specs` | `/opsx-sync` |
| 已交付 Change 归档 | `$openspec-archive-change` | `/opsx-archive` |

上表是 AI 工具里的调用形式，不是 PowerShell 命令。以 `openspec init` 生成文件及安装输出为准；不得套用其他工具的 `/opsx:propose` 或旧版命令。

## 多人并行与接口契约

在相关 Change 的 design.md 中记录：接口负责人；请求/响应字段及类型；错误、空值和超时语义；兼容性与版本策略；输入输出样例；依赖 Change；允许修改的文件/目录；协作者及集成顺序。可观察的行为要求进入 delta specs，实施清单仍只在 tasks.md。

各人类 Owner 使用自己的 clone/分支/PR；跨 Change 的共享接口需由双方 Owner 和受影响成员在开发前确认。Qwen 并行工作使用独立 worktree 或不重叠文件，同一物理文件同时只允许一名写入者。公共配置、依赖清单和接口定义应由明确负责人串行整合。

Codex 分派 Qwen 时，必须提供 Change ID、tasks.md 条目号、基线 commit、工作区路径、允许文件、交付物和验证要求；Qwen 返回实际改动及验证证据，Codex 回读并整合。人类 Owner 不因 AI 参与而转移责任。

发现冲突时暂停受影响工作，双方 Owner 对照规格决定兼容方案；更新 design/specs/tasks 和必要测试后，由指定成员在开发分支解决 Git 冲突。复核冲突文件及受影响测试，再请求人工审查。不得通过覆盖用户修改、自动丢弃一侧、强推共享分支或直接改 main 处理冲突。

## 合并后的归档

包含需求的 Change 仅在**交付 PR 已合并并经 Owner 验收**后才归档；在此之前禁止 `sync` 正式规格。推荐由原 Owner 发起独立的**归档维护 Change**，使用自己的 `change/<maintenance-change-id>` 分支和唯一维护 PR，引用原 Change 与已合并 PR。这样原开发 Change 仍只有一个交付 PR，归档也不会绕过 main 审查。

维护 Change 使用 CLI 原生 proposal/design/tasks；纯归档元数据工作不引入新需求时，将其 `.openspec.yaml` 设为 `skip_specs: true`，不虚构 delta specs。先核验原交付 PR 合并状态、原任务完成与验收记录，再在维护分支运行：

```powershell
openspec archive <delivered-change-id>
openspec validate --all --strict --no-interactive
openspec validate --archived --strict --no-interactive
git diff --check
```

回读 `openspec/specs/` 的实际合入内容和归档目录，更新 README/入口中指向原 Change 的链接，再提交维护 PR。只移动或同步已交付的原 Change，维护 PR 不继续原功能开发。无 delta 的维护 Change 自身只有审计记录，可在维护 PR 中一并归档，作为不引入未交付需求的元数据例外；无需递归创建新的维护 Change。包含任何新需求的维护 Change 不适用此例外。

正式 specs 在维护 PR 合并后更新；此前通过仍活跃的原 Change 和原交付 PR 查阅已经交付的要求。不要为消除这段短暂滞后而直接写 main。

## 必要检查与 GitHub 门禁

每次 PR 至少执行：

```powershell
openspec validate --all --strict --no-interactive
openspec validate --archived --strict --no-interactive
git diff --check
```

业务改动增加与变更相符的单元、集成或回归测试；AI 生成代码必须经过测试和人工代码审查。无业务代码的初始化 PR 明确写“业务测试不适用”，规格/配置检查不代替业务验证。PR 中披露无法执行的检查及其原因。

现有仓库没有 CI，因此 AUTO-001 只新增一个 `OpenSpec / validate` 检查 workflow，不引入业务框架。远端提供后由维护者检查其是否实际运行，并配置 main 保护：必须经 PR、至少一名有权限的人类批准、必需检查通过、解决审查意见；限制直推、删除和强推，并确认管理员绕过策略。文档约定和 workflow 文件本身不等于远端保护已生效。

## 工具升级

升级 CLI 或生成技能必须通过审查的维护 Change，更新 README 与 CI 中的固定版本，再运行 `openspec update` 并审查生成文件差异。不要修改全局 profile 或手工改写生成技能来绕过项目门禁。

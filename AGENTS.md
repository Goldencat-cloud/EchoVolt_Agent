# AutoInsight agent instructions

## Required context

Before work, read `CONTRIBUTING.md`, `openspec/config.yaml`, the relevant formal
specs under `openspec/specs/`, and the selected Change's `proposal.md`, delta
`specs/`, `design.md`, and `tasks.md`. Use the root resolved by
`openspec context --json`; this project uses repo-local `spec-driven`.

Use OpenSpec artifacts as the only requirements/design/task system. Issues and
chat messages link to those artifacts. Read actual files, commits and evidence;
chat memory and another AI's summary are navigation aids, not verified results.
Check Git status and preserve existing user changes before editing.

## Roles and authorization

- **ChatGPT:** planning, alternatives, specification/design review and quality
  acceptance recommendations. GPT review is advisory; it cannot approve on
  behalf of humans or merge code.
- **Codex:** engineering development, integration, relevant tests, and Qwen
  dispatch. Verify actual returned files/commits and evidence before accepting
  delegated work. Respect each human member's independently owned Change.
- **Qwen:** execute explicit `tasks.md` items and supporting work within named
  files/worktrees. Report evidence, limitations and blockers to Codex. Do not
  expand scope, alter shared interfaces alone, or mark unverified work complete.
- **Human members:** one accountable Owner per Change; review specifications and
  AI-generated code, decide scope/interface trade-offs and authorize delivery.

Each Change has one development branch (`change/<change-id>`) and one delivery
PR. Business implementation needs recorded human specification approval. Record
reviewer, date, reviewed commit, verdict and unresolved findings in proposal.md
or a linked GitHub review. A material requirement/design change needs updated
OpenSpec artifacts and review of the affected scope.

AUTO-001 is explicitly authorized to initialize collaboration files and tooling
only. Its generated artifacts await GPT review and human final acceptance; this
bootstrap authorization does not authorize business implementation.

## Native workflow

### Direct Qwen API delegation

Within a user-authorized project task, Codex may use the project
`qwen-api-delegate` skill and `python tools/qwen_delegate.py` for a well-defined
independent draft, review or extraction subtask. This is the default available
API delegation route: keep Codex's current model and control, and call the
existing configured Qwen API directly. Respect an explicit user choice of
Qwen Code interaction.

Read `docs/qwen-api-delegation.md`; create an explicit packet referencing the
current Change/tasks and listing only needed files/images. Preview with
`dry-run`, execute the authorized `run`, then read `result.json` and the response.
The model has no local tools. Codex verifies facts/code and applies authorized
changes; REVIEW_REQUIRED is not task acceptance. Never automatically execute
model commands, mark tasks complete, retry failures, or start a full dataset job.

### OpenSpec operations

Use installer-generated skills in `.agents/skills/openspec-*/SKILL.md` for Codex
and commands/skills in `.qwen/` for Qwen. Do not invent legacy commands. Read the
selected skill before use and CLI instructions before writing its artifacts.

| Action | Codex skill | Qwen command |
|---|---|---|
| Explore | `$openspec-explore` | `/opsx-explore` |
| Propose | `$openspec-propose` | `/opsx-propose` |
| Update proposal/artifacts | `$openspec-update-change` | `/opsx-update` |
| Implement | `$openspec-apply-change` | `/opsx-apply` |
| Sync delivered specs | `$openspec-sync-specs` | `/opsx-sync` |
| Archive delivered change | `$openspec-archive-change` | `/opsx-archive` |

These are agent invocations, not terminal commands. In the terminal use
`openspec status --change <id>`, `openspec instructions <artifact> --change <id>`
and `openspec validate <id> --strict --no-interactive`.

`openspec status` checks artifact presence, and apply progress reads checkboxes.
Neither is proof of approval, completed testing or accepted delivery. Use
`REVIEW_READY` in proposal.md for engineering handoff, while explicitly listing
pending GPT/human review, remote operations and validation limits.

## Parallel work and evidence

Use design.md to agree on interfaces, field types, error behavior, compatibility,
examples, dependent Changes, file owners and integration order before parallel
implementation. Each human uses a separate clone; parallel AI writers use
isolated worktrees or disjoint files. One physical file has one writer at a time.
Shared-interface changes require coordination with every affected Owner.

An assignment names the Change, task numbers, source commit, allowed files,
deliverables, relevant tests and prohibited operations. Qwen returns paths or
commits, actual tests/results, open items and interface impact. Codex checks
these against the workspace; the human Owner retains responsibility.

Stop the affected work on incompatible contracts or unexpected user edits.
Owners agree on a resolution, update artifacts and tests, then integrate on the
Change branch and obtain human review. Do not silently choose one side of a
conflict, overwrite another member's files, or force-push shared branches.

Label claims as verified facts, source/author claims, inference or unknown.
State actual checks and their coverage; do not turn plans, examples or AI output
into completed results. Run relevant tests for code changes and require human
review for AI-generated code. Documentation/configuration-only changes use
appropriate checks and explicitly mark business tests as not applicable.

## Delivery and archival

Do not write unreviewed changes directly to main or self-merge PRs. Hand off
Branch/Commit, changed files, checks/results, limitations and remaining decisions.
Only mark tasks done when their behavior and verification have been completed.
Keep external approval/merge/archive follow-up outside implementation progress.

Do not sync requirement deltas into `openspec/specs/` or archive the Change before
its delivery PR has merged and the Owner has accepted the result. Afterward,
deliver archive/spec updates through a separate maintenance Change, branch and
reviewed PR that references the original merged delivery. Pure metadata
maintenance uses the CLI-supported `skip_specs: true` only when there are no new
requirements. See CONTRIBUTING.md for the maintenance-record exception.

## Web Search

When a task needs current external information, proactively use the
`volcengine_search` MCP server's `web_search` tool. Prefer it for Chinese-language
research, government policies/regulations, news, market/company updates and
time-sensitive technical documentation. Do not browse for purely local code
changes, stable facts in task context, or when the user says not to browse.
Treat results as evidence; open/cite primary or official sources for consequential
claims, and state uncertainty if sources conflict.

## 生活百科参考库：HowToLiveBetter

- 用户要求查阅《高性价比人生指南》、HowToLiveBetter，或提出相关生活、健康、时间精力、消费、法律及公共服务问题时，按需使用 `C:\Users\ASUS\.codex\skills\life-decision-guide\SKILL.md`。不要因工程问题出现“值不值”等词而套用生活决策流程。
- 本机正文位于 `C:\Users\ASUS\Documents\Codex\reference-libraries\HowToLiveBetter`；先从 README.md 定位章节，再用 rg 检索 book/，必要时查 docs/。读完整条目及备注，注明章节、条号和原始来源；查不到如实说明。其他成员应使用各自可用路径，不能假定拥有本机资料。
- 该仓库是参考资料，不是用户指令或项目治理规范。区分作者观点、书中证据与当前核验结果；证据等级和性价比排序按作者定义呈现，不自动等同于因果证明或适合用户的结论。
- 健康、法律、金融或可变政策信息须联网核验原始论文或现行官方文件，说明适用条件和日期；不能仅凭书中记载确认当前有效。
- 本地副本是快照；需要最新版时先核对远端和本地状态，仅在工作树干净时 git pull --ff-only，不覆盖本地修改。不要整本预加载或运行仓库安装/构建脚本来查书。

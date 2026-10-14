# 抽取依据与边界

本模板的流程结构参考了用户指定的文章与 Magpie 仓库项目说明。它复用了“短入口路由 → 唯一事实文档 → 与变更同 PR 更新 → 有证据的复盘 → 稳定规则晋升”这一维护机制，不搬运 Magpie 的业务实现、模型规则、供应商信息、测试清单或产品决策。

## 来源

- X Article：<https://x.com/wquguru/article/2109650264601117141>（本任务按用户要求阅读原文；本文件不复制原文段落）。它作为整个维护机制的交叉参考，不逐项对应到每个仓库文件。
- Magpie 项目入口文档：[`AGENTS.md`][magpie-agents]、[`CLAUDE.md`][magpie-claude]、[`LESSONS.md`][magpie-lessons]、[`docs/code-standards.md`][magpie-standards]、[`docs/contributors.md`][magpie-contributors]、[`docs/subsystems/README.md`][magpie-subsystems]。
- 完整阅读的 Magpie 子系统参考（均固定到本轮对照提交）：[`provider-plugins.md`][magpie-provider-plugins]、[`plugin-runtime.md`][magpie-plugin-runtime]、[`gateway-middleware.md`][magpie-gateway-middleware]、[`claude-subscription-bridge.md`][magpie-claude-bridge]、[`gateway-routing.md`][magpie-gateway-routing]、[`gateway-sessions.md`][magpie-gateway-sessions]、[`agent-wiring.md`][magpie-agent-wiring]、[`providers-accounts.md`][magpie-providers-accounts]、[`library.md`][magpie-library]、[`gui-shell.md`][magpie-gui-shell]、[`sync-backup.md`][magpie-sync-backup]。
- 最初阅读的 Magpie `main` 快照：`a75de4c21ac28be98af8334643077d8b0bf47df7`。逐文件对照使用的精确提交：[`f074996d93b87b17ea682c4b5951d52794bb28cb`][magpie-comparison-commit]；更新来源或模板基线后须重新核对，不把旧结论当作永久有效。

## 本轮逐文件对照记录（2026-10-14）

- 对照对象：模板基线 `b37450378c85b0b27ed0e18c3b9df888511bd44e` 上的全部 17 个已跟踪 Markdown 文件。
- PR #2 原始范围修改其中 15 个文件；`AGENTS.md` 与 `CLAUDE.md` 未改，表中仍列出以完整记录模板文件的来源关系。
- 下表的 Magpie 链接均固定到精确对照提交 `f074996d93b87b17ea682c4b5951d52794bb28cb`。若标为“无一对一来源”，代表该模板文件由本仓库按目标场景编写，而非声称在 Magpie 中存在对应机制。

| 模板文件 | 对照来源（Magpie） | 核查结论与本 PR 范围 |
| --- | --- | --- |
| `.github/PULL_REQUEST_TEMPLATE.md` | [`docs/subsystems/README.md`][magpie-subsystems]、[`docs/contributors.md`][magpie-contributors] | 把语义变化的触发条件、前后行为、受影响范围与验证证据整理为填写项；Magpie 没有被照搬的同名 PR 模板，也未引入其合并流程。PR #2 修改。 |
| `AGENTS.md` | [`AGENTS.md`][magpie-agents]、[`CLAUDE.md`][magpie-claude]、[`docs/subsystems/README.md`][magpie-subsystems] | 仅对应“入口负责路由、事实放在专门文档”的通用结构；本文件未由 PR #2 修改，未纳入本次 diff，也未复制 Magpie 的产品指令。 |
| `CLAUDE.md` | [`CLAUDE.md`][magpie-claude]、[`AGENTS.md`][magpie-agents] | 仅对应共享入口的简短导入模式；本文件未由 PR #2 修改，未复制 Magpie 的工具或产品要求。 |
| `LESSONS.md` | [`LESSONS.md`][magpie-lessons]、[`docs/code-standards.md`][magpie-standards] | 抽象证据链接、按不同复盘日期计数和稳定规则晋升；没有复制 Magpie 的事件、具体 Lessons 或项目阈值之外的技术规则。PR #2 修改。 |
| `README.md` | [`README.md`][magpie-readme]；X Article（仅作整体机制参考） | 模板用途、文件地图与初始化路径是本仓库面向复制使用者编写的说明；Magpie 的产品功能、支持平台、命令和宣传内容均排除。PR #2 修改。 |
| `docs/automation/runner-contract.md` | 无一对一的 Magpie runner 文档；仅以 [`docs/code-standards.md`][magpie-standards] 和治理文档核对边界 | provider-neutral 的输入、写权限和恢复合约是本模板新增设计，不声称 Magpie 使用该 scheduler 或存储机制；未照搬实现。PR #2 修改。 |
| `docs/code-standards.md` | [`docs/code-standards.md`][magpie-standards]、[`LESSONS.md`][magpie-lessons]、[`docs/subsystems/README.md`][magpie-subsystems] | 抽象完整路径、失败处理、真实输入、回归测试与报告诚实等一般审查原则；排除 Magpie 专属命令、平台矩阵、发布门槛和产品策略。PR #2 修改。 |
| `docs/contributors.md` | [`docs/contributors.md`][magpie-contributors]、[`docs/code-standards.md`][magpie-standards] | 抽象不可信代码的审查、权限边界及需维护者决定的事项；不采用 Magpie 的作者名单、封禁条件、未审即关闭规则或产品决定。PR #2 修改。 |
| `docs/maintenance-loop.md` | [`AGENTS.md`][magpie-agents]、[`LESSONS.md`][magpie-lessons]、[`docs/code-standards.md`][magpie-standards]、[`docs/contributors.md`][magpie-contributors]、[`docs/subsystems/README.md`][magpie-subsystems] | 将入口、开发、PR 审查、复盘和校准综合成模板维护闭环；无单一来源文件，不含 Magpie 专属发布或合并流程。PR #2 修改。 |
| `docs/project-profile.md` | 无一对一的 Magpie 档案文件 | 字段是目标仓库 bootstrap 后应查证的事实槽位；初始值保留 `UNKNOWN`，没有填入 Magpie 的架构、命令、权限或运行配置。PR #2 修改。 |
| `docs/source-and-extraction.md` | 无直接 Magpie 对应文件；引用上述固定版本来源 | 本文件记录本次来源、映射方法和排除项，不把自身内容冒充为来源结论。PR #2 修改。 |
| `docs/subsystems/README.md` | [`docs/subsystems/README.md`][magpie-subsystems] 及下列 11 篇子系统参考 | 抽象责任边界、权威来源、同 PR 更新和验证证据；未复制 Magpie 子系统名或其项目事实。PR #2 修改。 |
| `docs/subsystems/TEMPLATE.md` | [`docs/subsystems/README.md`][magpie-subsystems]、[`provider-plugins.md`][magpie-provider-plugins]、[`plugin-runtime.md`][magpie-plugin-runtime]、[`gateway-routing.md`][magpie-gateway-routing]、[`gateway-sessions.md`][magpie-gateway-sessions]、[`agent-wiring.md`][magpie-agent-wiring]、[`providers-accounts.md`][magpie-providers-accounts]、[`gateway-middleware.md`][magpie-gateway-middleware]、[`claude-subscription-bridge.md`][magpie-claude-bridge]、[`library.md`][magpie-library]、[`gui-shell.md`][magpie-gui-shell]、[`sync-backup.md`][magpie-sync-backup] | 只抽象文档结构：职责、来源、运行路径、状态、失败/兼容和验证；多实现部分注明仅在实际存在时使用。所有 Magpie 子系统事实均排除。PR #2 修改。 |
| `prompts/bootstrap-project.md` | [`AGENTS.md`][magpie-agents]、[`CLAUDE.md`][magpie-claude]、[`LESSONS.md`][magpie-lessons]、[`docs/code-standards.md`][magpie-standards]、[`docs/contributors.md`][magpie-contributors]、[`docs/subsystems/README.md`][magpie-subsystems] | 将审查资料的方法转成“从目标仓库自身证据初始化”的通用步骤；不导入 Magpie 项目事实。PR #2 修改。 |
| `prompts/daily-review.md` | [`LESSONS.md`][magpie-lessons]、[`docs/code-standards.md`][magpie-standards]、[`docs/subsystems/README.md`][magpie-subsystems] | 抽象有证据的复盘、返工与验证缺口归类、可复核结论；每日调度和具体处置规则属于模板约定，不宣称来自 Magpie。PR #2 修改。 |
| `prompts/review-pr.md` | [`docs/subsystems/README.md`][magpie-subsystems]、[`docs/contributors.md`][magpie-contributors]、[`docs/code-standards.md`][magpie-standards] | 抽象完整 diff、可观察前后行为、相关入口与测试证据审查；不照搬作者名单或合并权限政策。PR #2 修改。 |
| `prompts/task-work.md` | [`docs/code-standards.md`][magpie-standards]、[`LESSONS.md`][magpie-lessons]、[`docs/subsystems/README.md`][magpie-subsystems] | 抽象按报告输入复现、追踪完整路径、回归验证及如实交付；不搬运 Magpie 的代码、命令或环境要求。PR #2 修改。 |

### 明确排除项

- Magpie 的业务实现、供应商/模型规则、项目命令、固定测试清单、支持平台、阈值、发布/合并流程和贡献者信任/封禁政策均不作为通用规则。
- 11 篇子系统文档只用于核对通用文档结构；其中 provider、gateway、GUI、sync 等具体职责、状态名、路径、配置及失败处置不进入模板。
- `AGENTS.md` 和 `CLAUDE.md` 虽列入完整文件清单，但不在 PR #2 修改范围内；表中映射不表示把它们用作本次任务的执行流程。

## 抽象出来的通用机制

`AGENTS.md` 是任务路由而不是重复一套规则；职责清单让 agent 按任务读取对应参考。子系统页以责任边界、权威来源、运行路径、状态/约束、失败与兼容、验证证据为中心，并在改变被描述的行为时同步更新。代码规范同时覆盖实现质量、失败处理、测试隔离与报告诚实；社区贡献审查独立处理不可信代码、权限与维护者决策；Lessons 保存每个项目自身的返工/验证教训，保留日期和证据，在重复验证后才晋升为稳定标准。

Magpie 文档的细节极多且强烈依赖该产品。把逐项规则抽象成任何项目的硬性规则会造成错误。因此，本仓库只把维护协议作为基线；项目的命令、子系统边界、风险模型、兼容要求和教训必须通过 [`prompts/bootstrap-project.md`](../prompts/bootstrap-project.md) 从目标仓库实际发现，并由后续 agent 持续维护。

[magpie-comparison-commit]: https://github.com/yetone/magpie/commit/f074996d93b87b17ea682c4b5951d52794bb28cb
[magpie-agents]: https://github.com/yetone/magpie/blob/f074996d93b87b17ea682c4b5951d52794bb28cb/AGENTS.md
[magpie-claude]: https://github.com/yetone/magpie/blob/f074996d93b87b17ea682c4b5951d52794bb28cb/CLAUDE.md
[magpie-lessons]: https://github.com/yetone/magpie/blob/f074996d93b87b17ea682c4b5951d52794bb28cb/LESSONS.md
[magpie-readme]: https://github.com/yetone/magpie/blob/f074996d93b87b17ea682c4b5951d52794bb28cb/README.md
[magpie-standards]: https://github.com/yetone/magpie/blob/f074996d93b87b17ea682c4b5951d52794bb28cb/docs/code-standards.md
[magpie-contributors]: https://github.com/yetone/magpie/blob/f074996d93b87b17ea682c4b5951d52794bb28cb/docs/contributors.md
[magpie-subsystems]: https://github.com/yetone/magpie/blob/f074996d93b87b17ea682c4b5951d52794bb28cb/docs/subsystems/README.md
[magpie-provider-plugins]: https://github.com/yetone/magpie/blob/f074996d93b87b17ea682c4b5951d52794bb28cb/docs/subsystems/provider-plugins.md
[magpie-plugin-runtime]: https://github.com/yetone/magpie/blob/f074996d93b87b17ea682c4b5951d52794bb28cb/docs/subsystems/plugin-runtime.md
[magpie-gateway-middleware]: https://github.com/yetone/magpie/blob/f074996d93b87b17ea682c4b5951d52794bb28cb/docs/subsystems/gateway-middleware.md
[magpie-claude-bridge]: https://github.com/yetone/magpie/blob/f074996d93b87b17ea682c4b5951d52794bb28cb/docs/subsystems/claude-subscription-bridge.md
[magpie-gateway-routing]: https://github.com/yetone/magpie/blob/f074996d93b87b17ea682c4b5951d52794bb28cb/docs/subsystems/gateway-routing.md
[magpie-gateway-sessions]: https://github.com/yetone/magpie/blob/f074996d93b87b17ea682c4b5951d52794bb28cb/docs/subsystems/gateway-sessions.md
[magpie-agent-wiring]: https://github.com/yetone/magpie/blob/f074996d93b87b17ea682c4b5951d52794bb28cb/docs/subsystems/agent-wiring.md
[magpie-providers-accounts]: https://github.com/yetone/magpie/blob/f074996d93b87b17ea682c4b5951d52794bb28cb/docs/subsystems/providers-accounts.md
[magpie-library]: https://github.com/yetone/magpie/blob/f074996d93b87b17ea682c4b5951d52794bb28cb/docs/subsystems/library.md
[magpie-gui-shell]: https://github.com/yetone/magpie/blob/f074996d93b87b17ea682c4b5951d52794bb28cb/docs/subsystems/gui-shell.md
[magpie-sync-backup]: https://github.com/yetone/magpie/blob/f074996d93b87b17ea682c4b5951d52794bb28cb/docs/subsystems/sync-backup.md

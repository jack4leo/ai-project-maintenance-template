# 抽取依据与边界

本模板的流程结构参考了用户指定的文章与 Magpie 仓库项目说明。它复用了“短入口路由 → 唯一事实文档 → 与变更同 PR 更新 → 有证据的复盘 → 稳定规则晋升”这一维护机制，不搬运 Magpie 的业务实现、模型规则、供应商信息、测试清单或产品决策。

## 来源

- X Article：<https://x.com/wquguru/article/2109650264601117141>（本任务按用户要求阅读原文；本文件不复制原文段落）。
- Magpie `AGENTS.md`：<https://github.com/yetone/magpie/blob/main/AGENTS.md>。
- 本次克隆的 `main` 快照：`a75de4c21ac28be98af8334643077d8b0bf47df7`。
- 本任务完整阅读的 Magpie 项目入口与治理文档：`CLAUDE.md`、`LESSONS.md`、`docs/code-standards.md`、`docs/contributors.md`、`docs/subsystems/README.md`。
- 完整阅读的子系统参考：`provider-plugins.md`、`plugin-runtime.md`、`gateway-middleware.md`、`claude-subscription-bridge.md`、`gateway-routing.md`、`gateway-sessions.md`、`agent-wiring.md`、`providers-accounts.md`、`library.md`、`gui-shell.md`、`sync-backup.md`。

## 本轮逐文件对照记录（2026-10-14）

- 对照对象：本模板 17 个 Markdown 文件；模板基线为 `b37450378c85b0b27ed0e18c3b9df888511bd44e`（PR #1 合并提交）。
- Magpie 来源：本轮核对的精确提交为 `f074996d`；后续更新来源或模板基线时，应重新检查逐文件差异，不把旧结论当作永久有效。
- 结论范围：直接抽象的是可观察行为描述、测试真实性/反向验证、清理、证据与完整 diff 核对等一般验证原则；多实现 parity、调度并发/重试/恢复、测试隔离和平台矩阵仅作为按项目实际机制选用并由 bootstrap 查证的条件性示例。
- 不抽取 Magpie 的业务政策、命令、状态名称、阈值、支持平台清单、贡献者策略或特定失败处置。对照结论不声称这些机制存在于所有模板副本。

## 抽象出来的通用机制

`AGENTS.md` 是任务路由而不是重复一套规则；职责清单让 agent 按任务读取对应参考。子系统页以责任边界、权威来源、运行路径、状态/约束、失败与兼容、验证证据为中心，并在改变被描述的行为时同步更新。代码规范同时覆盖实现质量、失败处理、测试隔离与报告诚实；社区贡献审查独立处理不可信代码、权限与维护者决策；Lessons 保存每个项目自身的返工/验证教训，保留日期和证据，在重复验证后才晋升为稳定标准。

Magpie 文档的细节极多且强烈依赖该产品。把逐项规则抽象成任何项目的硬性规则会造成错误。因此，本仓库只把维护协议作为基线；项目的命令、子系统边界、风险模型、兼容要求和教训必须通过 [`prompts/bootstrap-project.md`](../prompts/bootstrap-project.md) 从目标仓库实际发现，并由后续 agent 持续维护。

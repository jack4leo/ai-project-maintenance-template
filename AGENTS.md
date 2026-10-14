# Agent 工作入口

这是路由表，不是项目百科。规则与事实放在唯一权威文档里，修改文档时保持本文件简短。

## 开始任务前

1. 读取 [`docs/project-profile.md`](docs/project-profile.md)，了解本项目已确认的技术栈、运行方式、验收命令和权限边界；`UNKNOWN` 不得自行当成已知。
2. 读取 [`LESSONS.md`](LESSONS.md)，避免重复近期已发生的问题。
3. 修改或审查代码时遵循 [`docs/code-standards.md`](docs/code-standards.md)。项目专属章节必须依据该仓库源码、测试、CI 和复盘证据维护。
4. 影响一个已记录子系统时，先读 [`docs/subsystems/README.md`](docs/subsystems/README.md) 和对应子系统页；如果实际行为、接口、状态、兼容性或失败方式变化，在同一变更中更新该页。
5. 审查社区/外部贡献时，先读 [`docs/contributors.md`](docs/contributors.md)，尤其是运行不可信代码前的风险检查和需要维护者决定的情形。

## 执行与交付

- 先确认需求和可观察的目标，再追踪完整调用路径及受影响的同类入口；保持变更聚焦。
- 为 bug 修复添加能表达用户行为的回归验证；在可行时证明测试在旧实现/被破坏的实现上会失败。不要把编译失败或跳过测试说成测试已验证行为。
- 按项目 profile 中的真实命令验证。报告明确列出已运行、结果、提交/工作树版本，以及未运行项目和原因。
- 不得伪称执行过真实服务、平台或设备测试；无法验证时标明限制，并避免把未经验证的行为承诺为可用。
- 收尾检查相关文档、相邻实现、配置迁移和测试；PR/提交说明引用被审查的精确 HEAD。

## 持续维护

- 用 [`prompts/daily-review.md`](prompts/daily-review.md) 复盘每日提交；有证据的返工、错误合并或验证不足记入 `LESSONS.md`，做得好的验证也可记为 `Done right`。
- Agent 负责维护 Lessons 和 `docs/code-standards.md` 的项目专属部分：遵循 `LESSONS.md` 的日期/证据格式与晋升门槛，不把一次性事件或猜测写成硬规则。
- 产品方向、明确的维护者决定、安全例外、贡献者封禁、合并/发布权限等超出已授权范围的事项必须提交建议并停在决策点；不得自行逆转明确决定。
- 若 `.agent-maintenance/bootstrap-complete` 不存在，先完整执行 [`prompts/bootstrap-project.md`](prompts/bootstrap-project.md)；不允许照抄其他项目的技术规范。只有完成文档核查与验证后才创建该标记。

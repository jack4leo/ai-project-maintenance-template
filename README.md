# Self-Evolution Flywheel

这是一个可复制到任意软件仓库的 **agent 工作流程骨架**。它抽取的是维护机制，不是 Magpie 的业务规则：入口路由、项目事实文档、证据化代码规范、社区贡献审查、子系统地图，以及由 agent 持续维护的错题本和每日复盘。

> 模板中的通用底线可以直接使用；项目专属的架构、命令、风险边界、验收规则和 Lessons 必须由 agent 在目标仓库中查证后生成，不能从模板或其他项目臆造。

## 在新项目中使用

1. 在 GitHub 选择 **Use this template** 创建项目副本，或将本仓库克隆到本地。模板副本已包含文档、提示词和 Codex/Claude Code 项目级启动钩子。
2. 为已有项目安装时，在目标项目根目录运行 `./install.sh`。如果模板单独克隆在别处，运行 `/path/to/self-evolution-flywheel/install.sh --target /path/to/your-project`。安装器只补充缺失文件；遇到不同的 `AGENTS.md` 时会先显示差异并征求确认，默认在首行插入可幂等更新的受管路由区，其他冲突文件仍会保留；启动钩子以幂等方式合并。细节见 [`docs/installation.md`](docs/installation.md)。
3. 想立即执行初始化时，运行 `./install.sh --bootstrap codex` 或 `./install.sh --bootstrap claude`。若只运行 `./install.sh`，钩子会在项目后续启动时向 agent 注入初始化指令；交互会话要等首个模型回合，钩子本身不会启动模型。
4. 让项目 agent 完整执行 [`prompts/bootstrap-project.md`](prompts/bootstrap-project.md)。它会检查真实源码、包管理清单、CI 和现有文档，再填写 `docs/project-profile.md`、项目专属 `docs/code-standards.md`、`docs/contributors.md` 与 `docs/subsystems/`。
5. 由维护者核验自动整理出的事实、测试命令、权限边界和任何需要人作出的产品/安全决定；未知项必须留为 `UNKNOWN`，不得猜测。完成后 agent 写入 `.agent-maintenance/bootstrap-complete`，后续启动钩子即不再重复提醒。
6. 把 [`prompts/daily-review.md`](prompts/daily-review.md) 接到项目实际可用的 agent/scheduler，每天复盘自上次水位以来的提交。调度器、模型、凭证和权限由各项目自行选择；本模板不假装存在可直接运行的 AI 服务。
7. 每次开发按 `AGENTS.md` 路由；每次复盘维护 `LESSONS.md`。同一教训默认在 **三个不同复盘日期**出现后，才提升为 `docs/code-standards.md` 的稳定规则。

> 项目级钩子有代码执行权限，Codex/Claude Code 可能要求用户检查并信任项目设置；安装器不会绕过这些确认。首次启用前请查看 `.agent-maintenance/session-start.sh` 和生成的设置。钩子只检查 bootstrap 完成标记并注入提示，不会自行启动模型或写入文档。

## 文件地图

- [`install.sh`](install.sh)：安全安装模板文件、合并启动钩子，并可显式启动一次 bootstrap。
- [`docs/installation.md`](docs/installation.md)：安装范围、覆盖策略、启动触发边界与官方工具文档链接。
- [`AGENTS.md`](AGENTS.md)：短路由表；告诉 agent 开始工作前要读哪里以及收尾要做什么。
- [`CLAUDE.md`](CLAUDE.md)：Claude Code 入口，导入共享路由表和 Lessons，不复制规则。
- [`LESSONS.md`](LESSONS.md)：目标项目的动态错题本，由 agent 根据真实提交、返工和验证证据维护。
- [`docs/project-profile.md`](docs/project-profile.md)：项目差异、验证命令、风险门槛、自治边界、复盘归档位置和水位。
- [`docs/code-standards.md`](docs/code-standards.md)：跨项目通用基线 + agent 根据项目证据维护的专属规则。
- [`docs/contributors.md`](docs/contributors.md)：社区 PR 的安全筛查框架；项目政策、名单和决定不可由 agent 擅自编造。
- [`docs/subsystems/README.md`](docs/subsystems/README.md)：子系统文档索引和维护协议；具体页面从目标项目源码生成。
- [`docs/maintenance-loop.md`](docs/maintenance-loop.md)：初始化、日常开发、PR 审查、每日复盘和规则晋升闭环。
- [`docs/automation/runner-contract.md`](docs/automation/runner-contract.md)：把复盘接到任意定时 agent 的输入/输出和权限契约。
- [`prompts/`](prompts/)：项目初始化、开发、PR 审查、每日复盘可直接复用的任务提示。
- [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md)：要求记录目标、影响面、验证结果和未运行项目。

## 设计原则

1. **入口只路由。** 根部说明保持短小，规则放在唯一权威文档中。
2. **通用规则与项目事实分层。** 不把 Magpie 的技术细节、特定测试命令或某个项目的产品取舍当作通用标准。
3. **基于源码、测试和证据。** 文档描述当前行为；提案与未证实假设单独标明。
4. **错误先成为可读教训，再成为硬规则。** Lessons 保留日期和证据；达到晋升门槛才把去项目化的规则写入标准。
5. **人管方向和权限。** Agent 可以提出或维护规则，但不能把未经授权的产品决定、安全例外、贡献者封禁或发布权限当成自己的决定。
6. **验证诚实。** 已运行和未运行的检查都要明确写出；编译、测试、真实集成验证按项目实际风险选择，不能声称没做过。

## 模板不是即插即用的项目规范

新项目尚未初始化前，`docs/project-profile.md` 和项目专属章节是空白占位。请先跑 bootstrap；不要把占位符当作已验证的事实。本模板仓库为公开的 GitHub Template；模板副本的可见性和权限由仓库所有者在创建时决定，不应假定默认私有。

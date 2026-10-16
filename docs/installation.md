# 安装与首次 Bootstrap

本模板仓库名为 **self-evolution-flywheel**。安装器把维护机制文件复制到目标仓库，并为 Codex CLI 与 Claude Code 注册项目级 `SessionStart` 钩子。

## 用法

GitHub **Use this template** 创建的副本已包含文档、提示词和项目级钩子配置。对已有仓库安装，或希望幂等检查/补齐配置时，在目标仓库根目录运行：

```bash
./install.sh
```

### 在目标项目中直接运行一行命令

如果目标项目没有模板副本，也不想另外克隆模板仓库，可在**目标 Git 仓库根目录**运行：

```bash
curl -fsSL https://raw.githubusercontent.com/jack4leo/self-evolution-flywheel/main/install.sh | bash
```

管道模式会在临时目录对 `main` 做 Git 浅克隆；管道脚本只负责克隆和委派，实际安装器与模板文件来自同一 checkout，不再另行下载并执行一个可能不同步的源码归档。Git 会校验对象哈希，但不会验证提交者签名。模板文件会安装到当前目录，默认注册 Codex 与 Claude Code 启动钩子。需要 Bash、Git、Python 3 和 curl。此命令应在支持管道安装的改动合并到 `main` 后使用。`curl | bash` 会立即执行远程脚本，首次使用前请先检查 [install.sh](../install.sh)；Codex/Claude Code 仍可能要求用户信任项目设置。管道模式按克隆时的 `main` 获取最新提交；如需固定版本或验证提交签名，请检出并审阅所需提交后运行该检出中的本地 `./install.sh`，不要只固定 raw 脚本 URL。

若希望安装后立即启动 Codex Bootstrap（而不是只安装文件和钩子），运行：

```bash
curl -fsSL https://raw.githubusercontent.com/jack4leo/self-evolution-flywheel/main/install.sh | bash -s -- --bootstrap codex
```

不带 `--bootstrap` 时不会自动启动 agent 或修改项目源码；初始化会由后续启动钩子提示，或按下文使用本地安装器显式启动。目标目录须已存在，且启用钩子时必须是 Git 仓库根目录。

如果模板仓库单独克隆在另一个目录：

```bash
/path/to/self-evolution-flywheel/install.sh --target /path/to/your-project
```

需要现在立即启动初始化，而不是等到目标项目下一次打开 Codex/Claude Code 后的首个模型回合：

```bash
./install.sh --bootstrap codex
# 或
./install.sh --bootstrap claude
```

`--bootstrap codex` 使用 `codex exec --sandbox workspace-write -` 读取并执行 `prompts/bootstrap-project.md`；`--bootstrap claude` 以该文件作为 Claude Code 交互会话的首条提示词。CLI 必须已安装、登录并可从 `PATH` 调用。Codex 的写入范围由 `workspace-write` 沙箱限制在工作区，其他权限仍遵循 CLI 自身配置。

安装脚本需要 Bash、Git 和 Python 3（用于安全合并 JSON 设置）；GitHub Template 项目本身已带文件与 hook 配置。Windows 用户请在 WSL 或提供 Bash/Git/Python 的类 Unix 环境运行脚本。

可用 `--target DIR` 指定目标目录，或用 `--no-hooks` 只复制文件、不更改 agent 设置。目标目录必须已存在；默认启用钩子时，目标必须是 Git 仓库根目录。非 Git 目录会被拒绝；若只想安装文件，请显式使用 `--no-hooks`。

## 安装内容与覆盖规则

安装器复制根目录的 `AGENTS.md`、`CLAUDE.md`、`LESSONS.md`、安装器本身、`.agent-maintenance/session-start.sh`、`.agent-maintenance/installer-transaction.py`、`.github/PULL_REQUEST_TEMPLATE.md`，以及 `docs/`（不含仅描述模板来源的 `docs/source-and-extraction.md`）和 `prompts/` 下的文件。不会用模板版 `README.md` 替换目标项目自己的 README。

已存在且内容不同的目标文件默认保留，并在输出中列为冲突；脚本不会静默覆盖。`AGENTS.md` 会先显示精简路由区的 unified diff，并通过控制终端询问维护者；但即使输入 `y`，安装器也不会自动替换已有文件：POSIX/Linux/macOS 没有可移植的、可对非协作写者实现“仅当目标仍是刚检查版本才替换”的原子 compare-and-replace。安装器因此保留原文件，以退出码 `4` 报告未完成，要求人工合并所审阅的区块。没有控制终端时则不询问、不写入，同样保留原文件并报告未完成；其他无冲突模板可能已经安装。缺失的 `AGENTS.md` 可通过不覆盖式新建安全安装；与模板字节相同的文件保持不变。

插入区由 `<!-- BEGIN SELF-EVOLUTION-FLYWHEEL MANAGED ROUTING -->` 与 `<!-- END SELF-EVOLUTION-FLYWHEEL MANAGED ROUTING -->` 标记。由于上述并发限制，已有区块的插入/更新都必须人工合并；区外说明、属主、权限、时间戳、扩展属性、ACL 和硬链接关系因此保持原样。差异中的终端控制字符会以可见转义形式显示。符号链接、非普通文件或标记异常的文件不会被自动修改。

若启用钩子时 `.agent-maintenance/session-start.sh` 已存在且内容不同，安装器会在复制或修改设置前报错退出，不注册任何启动钩子；解决冲突后可重试，或使用 `--no-hooks` 仅安装其他文件。预检会检查目标父目录、Codex/Claude 设置结构和可预见的写权限问题；设置文件自身若是符号链接、硬链接、非普通文件或 JSON 无效/结构冲突，安装会在复制模板文件前报错。若现有 `.codex/hooks.json` 或 `.claude/settings.json` 已包含对应钩子，安装器识别后不改动文件；若需要向已有 JSON 追加钩子，预检会在任何模板复制前拒绝，并保留文件及其元数据，要求人工合并。只有设置文件原先不存在时，安装器才会以不覆盖式创建注册钩子。重复运行会识别已有钩子，不重复添加。

安装写入按事务日志记录。模板文件和新建设置在发布前使用目标目录句柄；写入前后会从项目根路径重新解析父目录，并拒绝 symlink。目录句柄固定的是目录 inode，不保证该目录仍位于项目树中；非协作进程可以在最后一次路径复核与发布系统调用之间 rename 目录。若发布后复核发现迁移，安装器会报错并尝试回滚；如果目标父目录已移出项目树或无法安全访问，它会保留该目录中的文件、报告回滚不完整并保留日志，而不是声称 dirfd 阻止了越界。该窄竞态无法在这里跨 POSIX/Linux/macOS 原子封锁，外部目录移动造成的文件位置需人工检查。

回滚会先按 inode/内容身份检查本次新建文件，再用不覆盖式 rename 隔离；隔离后的 inode 可能仍被其他进程持有可写 FD，POSIX 无法据此判断该 FD 是否会在稍后写入。因此安装器不 unlink 隔离文件，而保留 `.name.rollback-*` 恢复项，并将回滚标记为不完整；事务日志目录也会保留并打印路径。并发替换/写入、目标目录迁移、隔离 rename 不可用或回滚本身失败都会显式报告，未知数据优先保留而不自动清理。若并发进程已删除新建文件，回滚不会重建该文件。安装失败后，检查错误输出中的日志路径和目标目录内恢复项，确认没有进程仍持有相关文件后再由维护者手工处理；不要盲目重跑。

这不是多文件崩溃一致性事务：强制杀进程或断电仍可能留下部分安装。事务日志初始化失败会在目标文件写入前终止；中途日志更新失败会触发回滚，并在无法完整恢复时保留恢复项与日志、明确报告不完整。若只是在准备已有 `AGENTS.md` 的基线快照时失败，该文件会保持原样、输出冲突，其他独立模板仍可能安装；应根据冲突输出检查后续是否需人工合并。即使使用目录句柄和身份检查，也不能对非协作写者或并发目录 rename 作绝对防护。

## 启动钩子会做什么

- Codex 项目钩子写入 `.codex/hooks.json`；Claude Code 项目钩子写入 `.claude/settings.json`。
- 每次 session start/resume/clear/compact/fork 时，钩子只检查 `.agent-maintenance/bootstrap-complete`。标记不存在时，它向 agent 上下文提供一条指令，要求先读取并执行 `prompts/bootstrap-project.md`；标记存在时保持安静。
- 钩子脚本不启动子 agent、不执行 bootstrap 提示词、不检查源码、不写项目文档，也不联网。启动钩子可以注入上下文，但不会单独触发模型回合；交互式会话通常需要用户先发出第一条消息。因此希望现在就运行完整初始化时，请显式使用 `--bootstrap codex|claude`。
- Codex 可能要求在 `/hooks` 中审查并信任项目钩子；Claude Code 可能要求用户信任项目设置。信任/确认由各 CLI 管理，安装器不会尝试绕过。

钩子应当被视为项目代码的一部分：首次启用前检查 `.agent-maintenance/session-start.sh` 与生成的设置。它只读取完成标记并输出固定文本；真正的文件检查和写入由 agent 按 bootstrap 提示词与 CLI 权限执行。

## 完成标记

Bootstrap 提示词要求 agent 只在完成文档核查、验证并报告遗留未知项后写入 `.agent-maintenance/bootstrap-complete`。这个仓库内的标记代表初始化流程已执行完成，不代表所有事实都已知，也不代表维护者已接受待决策项。若初始化受阻或检查未完成，标记应保持缺失，钩子会在后续启动继续提示。

## 安装器回归测试

仓库的 `.github/workflows/installer-tests.yml` 会在 push、pull request 和手动触发时运行 `bash tests/test-install.sh`。测试使用隔离临时目录，覆盖只读 Claude 配置预检、模板复制与 provider 写入中途失败、并发外部改写保留、AGENTS/设置拒绝替换、日志初始化与中途更新失败、AGENTS 基线快照失败、回滚二次失败、父目录 symlink 拒绝，以及固定 PR 原 head 与当前实现之间的确定性系统调用边界对照（替换覆盖、目录移出项目树、回滚时持有 FD 写入）。旧 head 在相同注入下应暴露丢失/未检测问题；新实现应保留不确定数据或明确报不完整。运行命令：`bash tests/test-install.sh`。

## 官方行为说明

- [Codex 项目级 `AGENTS.md` 指令](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Codex hooks](https://learn.chatgpt.com/docs/hooks)
- [Codex `exec` 非交互模式与沙箱](https://learn.chatgpt.com/docs/non-interactive-mode)
- [Claude Code hooks](https://code.claude.com/docs/en/hooks)
- [Claude Code hooks guide](https://code.claude.com/docs/en/hooks-guide)
- [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference)

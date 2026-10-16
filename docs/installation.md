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

已存在且内容不同的目标文件默认保留，并在输出中列为冲突；脚本不会静默覆盖。`AGENTS.md` 是唯一例外：安装器会先显示把精简路由区插入后的 unified diff，再通过控制终端询问维护者。明确输入 `y` 才会应用；默认位置是文件首行，按 Enter 或输入其他内容都会保留原文件。没有可用控制终端时也会保留原文件，并以退出码 `4` 报告安装未完成，不会输出成功完成标记；其他无冲突文件可能已安装。

插入区由 `<!-- BEGIN SELF-EVOLUTION-FLYWHEEL MANAGED ROUTING -->` 与 `<!-- END SELF-EVOLUTION-FLYWHEEL MANAGED ROUTING -->` 标记。后续运行若模板路由有更新，只会在再次显示差异并获得确认后替换标记之间的内容；区外的维护者说明保持不变。更新时会保留原文件的属主、属组、权限、时间戳和扩展属性（包括可读取/写入的 ACL）；若无法安全保留这些属性，或文件有硬链接，安装器会拒绝替换。差异中的终端控制字符会以可见转义形式显示。缺失的 `AGENTS.md` 仍会直接复制完整模板文件；符号链接、非普通文件或标记异常的文件不会被自动修改。

若启用钩子时 `.agent-maintenance/session-start.sh` 已存在且内容不同，安装器会在复制或修改设置前报错退出，不注册任何启动钩子；解决文件冲突后可重试，或使用 `--no-hooks` 仅安装其他文件。预检会检查目标父目录、Codex/Claude 设置结构和可预见的写权限问题；设置文件自身若是符号链接、硬链接、非普通文件，或 JSON 无效/结构冲突，安装会在复制模板文件前报错。预检之后，每次实际写入仍会从目标根目录逐级打开真实目录并拒绝符号链接，不依赖一次性预检结果来授权后续路径写入。Codex/Claude 的现有 JSON 设置会被保留，安装器仅向 `SessionStart` 数组追加一项。原子替换会保留设置文件的属主、属组、权限、时间戳和扩展属性（包括可读取/写入的 ACL）；无法安全保留时不会替换。重复运行会识别已有的钩子，不重复添加。

安装写入按事务日志记录。若模板复制或后续 provider 设置写入在运行中失败，安装器会按相反顺序尝试撤销本次已完成的写入，并恢复原设置；回滚只在目标仍是本次安装生成的版本时执行。若发现文件已被并发修改、替换或删除，安装器会保留该外部变更，不用旧快照覆盖，并报告回滚不完整；此时会保留事务日志和快照目录供恢复，路径会打印在错误输出中。预检可拦截静态错误，写时目录句柄检查可拦截预检后出现的 symlink 替换，事务回滚处理运行中的可恢复写入错误。多文件安装不是文件系统崩溃一致性事务：强制杀进程、断电或回滚路径本身也不可写时，仍可能需要按错误日志和保留的快照人工恢复；重跑安装前应先检查这些提示。

## 启动钩子会做什么

- Codex 项目钩子写入 `.codex/hooks.json`；Claude Code 项目钩子写入 `.claude/settings.json`。
- 每次 session start/resume/clear/compact/fork 时，钩子只检查 `.agent-maintenance/bootstrap-complete`。标记不存在时，它向 agent 上下文提供一条指令，要求先读取并执行 `prompts/bootstrap-project.md`；标记存在时保持安静。
- 钩子脚本不启动子 agent、不执行 bootstrap 提示词、不检查源码、不写项目文档，也不联网。启动钩子可以注入上下文，但不会单独触发模型回合；交互式会话通常需要用户先发出第一条消息。因此希望现在就运行完整初始化时，请显式使用 `--bootstrap codex|claude`。
- Codex 可能要求在 `/hooks` 中审查并信任项目钩子；Claude Code 可能要求用户信任项目设置。信任/确认由各 CLI 管理，安装器不会尝试绕过。

钩子应当被视为项目代码的一部分：首次启用前检查 `.agent-maintenance/session-start.sh` 与生成的设置。它只读取完成标记并输出固定文本；真正的文件检查和写入由 agent 按 bootstrap 提示词与 CLI 权限执行。

## 完成标记

Bootstrap 提示词要求 agent 只在完成文档核查、验证并报告遗留未知项后写入 `.agent-maintenance/bootstrap-complete`。这个仓库内的标记代表初始化流程已执行完成，不代表所有事实都已知，也不代表维护者已接受待决策项。若初始化受阻或检查未完成，标记应保持缺失，钩子会在后续启动继续提示。

## 安装器回归测试

仓库的 `.github/workflows/installer-tests.yml` 会在 push、pull request 和手动触发时运行 `bash tests/test-install.sh`。测试使用隔离临时目录，并覆盖预检拒绝、运行时故障回滚、并发改写既有/新建文件时保留并报告、预检后父目录变成 symlink 时拒绝越界写入，以及 hook 配置与文件元数据兼容；本地也可运行相同命令。

## 官方行为说明

- [Codex 项目级 `AGENTS.md` 指令](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Codex hooks](https://learn.chatgpt.com/docs/hooks)
- [Codex `exec` 非交互模式与沙箱](https://learn.chatgpt.com/docs/non-interactive-mode)
- [Claude Code hooks](https://code.claude.com/docs/en/hooks)
- [Claude Code hooks guide](https://code.claude.com/docs/en/hooks-guide)
- [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference)

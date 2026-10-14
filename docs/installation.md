# 安装与首次 Bootstrap

本模板仓库名为 **self-evolution-flywheel**。安装器把维护机制文件复制到目标仓库，并为 Codex CLI 与 Claude Code 注册项目级 `SessionStart` 钩子。

## 用法

GitHub **Use this template** 创建的副本已包含文档、提示词和项目级钩子配置。对已有仓库安装，或希望幂等检查/补齐配置时，在目标仓库根目录运行：

```bash
./install.sh
```

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

可用 `--target DIR` 指定目标根目录，或用 `--no-hooks` 只复制文件、不更改 agent 设置。目标目录必须已存在；启用钩子时，如果目标是 Git 仓库，必须是仓库根目录。

## 安装内容与覆盖规则

安装器复制根目录的 `AGENTS.md`、`CLAUDE.md`、`LESSONS.md`、安装器本身、`.agent-maintenance/session-start.sh`、`.github/PULL_REQUEST_TEMPLATE.md`，以及 `docs/`（不含仅描述模板来源的 `docs/source-and-extraction.md`）和 `prompts/` 下的文件。不会用模板版 `README.md` 替换目标项目自己的 README。

已存在且内容不同的目标文件一律保留，并在输出中列为冲突；脚本不会提供静默覆盖模式。Codex/Claude 的现有 JSON 设置会被保留，安装器仅向 `SessionStart` 数组追加一项。遇到无效 JSON 或结构冲突时，脚本停止修改该设置并报错，不会用空设置覆盖它。重复运行会识别已有的钩子，不重复添加。

## 启动钩子会做什么

- Codex 项目钩子写入 `.codex/hooks.json`；Claude Code 项目钩子写入 `.claude/settings.json`。
- 每次 session start/resume/clear/compact/fork 时，钩子只检查 `.agent-maintenance/bootstrap-complete`。标记不存在时，它向 agent 上下文提供一条指令，要求先读取并执行 `prompts/bootstrap-project.md`；标记存在时保持安静。
- 钩子脚本不启动子 agent、不执行 bootstrap 提示词、不检查源码、不写项目文档，也不联网。启动钩子可以注入上下文，但不会单独触发模型回合；交互式会话通常需要用户先发出第一条消息。因此希望现在就运行完整初始化时，请显式使用 `--bootstrap codex|claude`。
- Codex 可能要求在 `/hooks` 中审查并信任项目钩子；Claude Code 可能要求用户信任项目设置。信任/确认由各 CLI 管理，安装器不会尝试绕过。

钩子应当被视为项目代码的一部分：首次启用前检查 `.agent-maintenance/session-start.sh` 与生成的设置。它只读取完成标记并输出固定文本；真正的文件检查和写入由 agent 按 bootstrap 提示词与 CLI 权限执行。

## 完成标记

Bootstrap 提示词要求 agent 只在完成文档核查、验证并报告遗留未知项后写入 `.agent-maintenance/bootstrap-complete`。这个仓库内的标记代表初始化流程已执行完成，不代表所有事实都已知，也不代表维护者已接受待决策项。若初始化受阻或检查未完成，标记应保持缺失，钩子会在后续启动继续提示。

## 官方行为说明

- [Codex 项目级 `AGENTS.md` 指令](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Codex hooks](https://learn.chatgpt.com/docs/hooks)
- [Codex `exec` 非交互模式与沙箱](https://learn.chatgpt.com/docs/non-interactive-mode)
- [Claude Code hooks](https://code.claude.com/docs/en/hooks)
- [Claude Code hooks guide](https://code.claude.com/docs/en/hooks-guide)
- [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference)

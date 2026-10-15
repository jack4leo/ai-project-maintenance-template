# Installation and Initial Bootstrap

This template repository is named **self-evolution-flywheel**. The installer copies maintenance-mechanism files into the target repository and registers project-level `SessionStart` hooks for Codex CLI and Claude Code.

## Usage

A copy created with GitHub **Use this template** already contains the documentation, prompts, and project-level hook configuration. To install into an existing repository, or to perform an idempotent configuration check/repair, run this from the target repository root:

```bash
./install.sh
```

### Run a one-line command directly in the target project

If the target project does not contain a template copy and you do not want to clone the template repository separately, run this in the **root of the target Git repository**:

```bash
curl -fsSL https://raw.githubusercontent.com/jack4leo/self-evolution-flywheel/main/install.sh | bash
```

Pipeline mode first downloads a complete source archive of the `main` branch into a temporary directory and then invokes the same installer; template files are installed into the current directory, and Codex and Claude Code startup hooks are registered by default. Bash, Git, Python 3, curl, and tar are required. Use this command only after pipeline installation support has been merged into `main`. `curl | bash` executes a remote script immediately; inspect [install.sh](../install.sh) before first use. Codex/Claude Code may still require the user to trust the project settings. Pipeline mode always fetches the `main` archive; to pin a version, check out a reviewed commit SHA and run the local `./install.sh` from that checkout instead of pinning only the raw script URL.

To start Codex Bootstrap immediately after installation (rather than only installing files and hooks), run:

```bash
curl -fsSL https://raw.githubusercontent.com/jack4leo/self-evolution-flywheel/main/install.sh | bash -s -- --bootstrap codex
```

Without `--bootstrap`, no agent is started and no project source is modified automatically; initialization is prompted by a subsequent startup hook, or can be started explicitly with the local installer as described below. The target directory must already exist, and when hooks are enabled it must be the root of a Git repository.

If the template repository is cloned separately into another directory:

```bash
/path/to/self-evolution-flywheel/install.sh --target /path/to/your-project
```

To start initialization now instead of waiting for the first model turn after the next time the target project opens in Codex/Claude Code:

```bash
./install.sh --bootstrap codex
# or
./install.sh --bootstrap claude
```

`--bootstrap codex` uses `codex exec --sandbox workspace-write -` to read and execute `prompts/bootstrap-project.md`; `--bootstrap claude` uses that file as the first prompt in a Claude Code interactive session. The CLI must be installed, logged in, and callable from `PATH`. Codex's write scope is restricted to the workspace by the `workspace-write` sandbox; other permissions continue to follow the CLI's own configuration.

The installation script requires Bash, Git, and Python 3 (for safely merging JSON settings); a GitHub Template project already includes the files and hook configuration. Windows users should run the script in WSL or a Unix-like environment that provides Bash/Git/Python.

Use `--target DIR` to specify the target directory, or `--no-hooks` to copy files only without changing agent settings. The target directory must already exist; when hooks are enabled by default, the target must be the root of a Git repository. Non-Git directories are rejected; to install files only, explicitly use `--no-hooks`.

## Installation Contents and Overwrite Rules

The installer copies the root-level `AGENTS.md`, `CLAUDE.md`, `LESSONS.md`, the installer itself, `.agent-maintenance/session-start.sh`, `.github/PULL_REQUEST_TEMPLATE.md`, and the files under `docs/` (excluding `docs/source-and-extraction.md`, which only describes the template's sources) and `prompts/`. It does not replace the target project's own `README.md` with the template version.

Existing target files whose content differs are preserved by default and listed as conflicts in the output; the script does not silently overwrite them. `AGENTS.md` is the sole exception: the installer first displays a unified diff with the compact routing block inserted, then asks the maintainer through the controlling terminal. Only an explicit `y` applies it; pressing Enter or entering anything else preserves the original file. Without an available controlling terminal, the original file is also preserved and exit code `4` reports that installation did not complete; no successful-completion marker is printed. Other conflict-free files may already have been installed.

The inserted block is delimited by `<!-- BEGIN SELF-EVOLUTION-FLYWHEEL MANAGED ROUTING -->` and `<!-- END SELF-EVOLUTION-FLYWHEEL MANAGED ROUTING -->`. On later runs, if the template routing has changed, the installer replaces only the content between the markers after displaying the diff again and obtaining confirmation; maintainer notes outside the block remain unchanged. During an update, the original file's owner, group, permissions, timestamps, and extended attributes (including readable/writable ACLs) are preserved; if these attributes cannot be retained safely, or if the file has hard links, the installer refuses to replace it. Terminal control characters in the diff are displayed using visible escape forms. A missing `AGENTS.md` is still copied as the complete template file; symlinks, non-regular files, or files with anomalous markers are not modified automatically.

If `.agent-maintenance/session-start.sh` already exists and differs when hooks are enabled, the installer exits with an error before copying files or modifying settings and registers no startup hooks; resolve the file conflict and retry, or use `--no-hooks` to install other files only. Existing Codex/Claude JSON settings are preserved; the installer only appends one item to the `SessionStart` array. If the JSON is invalid or has a structural conflict, the script stops modifying that setting and reports an error rather than overwriting it with empty settings. Repeated runs recognize existing hooks and do not add duplicates.

## What the Startup Hooks Do

- The Codex project hook is written to `.codex/hooks.json`; the Claude Code project hook is written to `.claude/settings.json`.
- On every session start/resume/clear/compact/fork, the hook first checks whether `.agent-maintenance/bootstrap-complete` is non-empty; if so, it exits quietly. Otherwise, it requires `prompts/bootstrap-project.md` to exist. If the prompt file is missing, the script prints an error to stderr and exits with status 0 without injecting the bootstrap instruction. The host CLI may or may not display stderr from a hook that exits successfully, so do not rely on this diagnostic being shown. If the prompt file exists, the hook injects an instruction for the agent to read and execute it first.
- The hook script does not start a sub-agent, execute the bootstrap prompt, inspect source code, write project documentation, or access the network. A startup hook can inject context but does not trigger a model turn by itself; interactive sessions usually require the user to send the first message. Therefore, to run the complete initialization now, explicitly use `--bootstrap codex|claude`.
- Codex may require reviewing and trusting project hooks in `/hooks`; Claude Code may require the user to trust the project settings. Trust and confirmation are managed by each CLI, and the installer does not attempt to bypass them.

Treat hooks as part of the project code: inspect `.agent-maintenance/session-start.sh` and the generated settings before enabling them for the first time. The hook checks both the completion marker and whether the bootstrap prompt exists; it does not inspect the prompt's contents. When the prompt exists, it prints fixed text; the agent performs the actual file inspection and writing according to the bootstrap prompt and CLI permissions.

## Completion Marker

The bootstrap prompt requires the agent to write `.agent-maintenance/bootstrap-complete` only after completing the documentation review, verification, and report of remaining unknowns. In this repository, the marker means that the initialization process has run; it does not mean that all facts are known or that the maintainer has accepted pending decisions. If initialization is blocked or incomplete, the marker should remain absent so the hook continues prompting at later startups.

## Official Behavior Documentation

- [Codex project-level `AGENTS.md` instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Codex hooks](https://learn.chatgpt.com/docs/hooks)
- [Codex `exec` non-interactive mode and sandbox](https://learn.chatgpt.com/docs/non-interactive-mode)
- [Claude Code hooks](https://code.claude.com/docs/en/hooks)
- [Claude Code hooks guide](https://code.claude.com/docs/en/hooks-guide)
- [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference)

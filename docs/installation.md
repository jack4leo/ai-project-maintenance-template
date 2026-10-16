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

Pipeline mode shallow-clones `main` into a temporary directory; the piped script only performs the clone and delegates, so the installer and template files come from the same checkout instead of a separately downloaded source archive that could be out of sync. Git verifies object hashes, but not commit signatures. The template files are installed into the current directory, and Codex and Claude Code startup hooks are registered by default. Bash, Git, Python 3, and curl are required. Use this command only after pipeline-install support has been merged into `main`. `curl | bash` immediately executes a remote script; inspect [install.sh](../install.sh) before first use. Codex/Claude Code may still require the user to trust the project settings. Pipeline mode obtains the latest `main` commit available at clone time; to pin a version or verify a commit signature, check out and review the desired commit and run that checkout's local `./install.sh`, rather than pinning only the raw script URL.

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

The installer copies the root-level `AGENTS.md`, `CLAUDE.md`, `LESSONS.md`, the installer itself, `.agent-maintenance/session-start.sh`, `.agent-maintenance/installer-transaction.py`, `.github/PULL_REQUEST_TEMPLATE.md`, and the files under `docs/` (excluding `docs/source-and-extraction.md`, which only describes the template's sources) and `prompts/`. It does not replace the target project's own `README.md` with the template version.

Existing target files whose content differs are preserved by default and listed as conflicts in the output; the installer does not silently overwrite them. `AGENTS.md` is handled specially: the installer displays a unified diff with the compact routing block inserted and asks for confirmation through the controlling terminal, but it does not automatically replace an existing file even if the user enters `y`. POSIX/Linux/macOS do not provide a portable atomic compare-and-replace that is safe against non-cooperative writers. The installer therefore preserves the original file and exits with code `4`, requiring a maintainer to merge the reviewed block manually. Without a controlling terminal, it does not prompt or write and likewise preserves the file and reports incomplete installation; other conflict-free templates may already have been installed. A missing `AGENTS.md` can be safely created without overwriting an existing path; a file whose bytes already match the template is left unchanged.

The inserted block is delimited by `<!-- BEGIN SELF-EVOLUTION-FLYWHEEL MANAGED ROUTING -->` and `<!-- END SELF-EVOLUTION-FLYWHEEL MANAGED ROUTING -->`. Because of the concurrency limitation above, inserting or updating an existing block always requires a manual merge; notes outside the block, ownership, permissions, timestamps, extended attributes, ACLs, and hard-link relationships therefore remain unchanged. Terminal control characters in the diff are displayed using visible escape forms. Symlinks, non-regular files, or files with anomalous markers are not modified automatically.

If `.agent-maintenance/session-start.sh` already exists and differs while hooks are enabled, the installer exits with an error before copying files or modifying settings and registers no startup hooks; resolve the conflict and retry, or use `--no-hooks` to install other files only. Preflight checks target parent directories, Codex/Claude settings structure, and predictable write-permission failures. A settings file that is itself a symlink, an unexplained hard link, or a non-regular file, or contains invalid or structurally conflicting JSON, is rejected before template files are copied. Before this check, a rerun may remove one precisely recognized installer staging hard link left by a killed provider-settings publish; it does not remove unknown names or links whose inode, owner, content, or exact link count cannot be verified. If an existing `.codex/hooks.json` or `.claude/settings.json` already contains the corresponding hook, the installer recognizes it and leaves the file unchanged. If a hook must be appended to existing JSON, preflight rejects the operation before any template files are copied, preserves the settings file and its metadata, and requires a manual merge. The installer creates a hook settings file with no-overwrite semantics only when that file did not previously exist. Repeated runs recognize existing hooks and do not add duplicates.

Installation writes are recorded in a transaction journal. Before publishing template files and newly created settings, the helper uses target-directory file descriptors; before and after writes, it re-resolves parent paths from the project root and rejects symlinks. A directory descriptor pins the directory inode but does not guarantee that the directory remains inside the project tree. A non-cooperative process can rename the directory between the final path check and the publish syscall. If the post-publication check detects that move, the installer reports an error and attempts rollback. If the target parent has moved outside the project tree or cannot be accessed safely, it preserves the files in that directory, reports incomplete rollback, and retains the journal rather than claiming that a directory descriptor prevents the race. This narrow race cannot be atomically blocked across POSIX/Linux/macOS; files moved externally may require manual inspection.

Rollback first checks the inode/content identity of files created by this transaction, then isolates them with a no-overwrite rename. Another process may still hold a writable file descriptor to the isolated inode, and POSIX provides no way to determine whether that descriptor will write later. Therefore, the installer does not unlink the isolated file: it preserves a `.name.rollback-*` recovery entry, marks rollback incomplete, and retains and reports the transaction-journal path. Concurrent replacement or writes, moved target directories, unavailable quarantine rename, and rollback failures are reported explicitly; uncertain data is preserved rather than automatically cleaned up. If a concurrent process has already deleted a newly created file, rollback does not recreate it. If the installer reports an incomplete rollback or retained recovery material, inspect the reported journal path and entries before retrying; do not remove or retry around uncertain rollback artifacts blindly.

The installer takes an exclusive advisory lock on the target directory for its full run; a second invocation for the same target fails without modifying it. For the common case where one installer process is forcibly killed, rerunning the same command can finish the installation: in particular, it recognizes and removes only its exact provider-settings staging alias after verifying the active settings inode, expected owner and generated content, a link count of exactly two, and the absence of another cooperating installer. Template files remain idempotent, hooks are not duplicated, and unrelated user settings are not rewritten. Unrecognized or ambiguous residue is preserved and reported for manual inspection.

This is not a crash-consistent multi-file transaction. Abrupt process termination may still leave a partial installation; the documented retry guarantee is for ordinary single-installer SIGKILL recovery when the remaining state passes the strict checks above. Power loss, missing directory `fsync` guarantees, filesystem damage, concurrent external edits or non-cooperating writers, directory renames, and every possible rollback artifact are not automatically repaired. Failure to initialize the journal stops the installer before target files are written. A mid-transaction journal update failure triggers rollback; if recovery is incomplete, the installer preserves recovery entries and the journal and reports that status. If only the baseline snapshot of an existing `AGENTS.md` fails, that file remains unchanged and is reported as a conflict, while other independent templates may still be installed; inspect the conflict output to determine whether a manual merge is needed. Directory descriptors and identity checks do not provide absolute protection against non-cooperative writers or concurrent directory renames.

## What the Startup Hooks Do

- The Codex project hook is written to `.codex/hooks.json`; the Claude Code project hook is written to `.claude/settings.json`.
- On every session start/resume/clear/compact/fork, the hook first checks whether `.agent-maintenance/bootstrap-complete` is non-empty; if so, it exits quietly. Otherwise, it requires `prompts/bootstrap-project.md` to exist. If the prompt file is missing, the script prints an error to stderr and exits with status 0 without injecting the bootstrap instruction. The host CLI may or may not display stderr from a hook that exits successfully, so do not rely on this diagnostic being shown. If the prompt file exists, the hook injects an instruction for the agent to read and execute it first.
- The hook script does not start a sub-agent, execute the bootstrap prompt, inspect source code, write project documentation, or access the network. A startup hook can inject context but does not trigger a model turn by itself; interactive sessions usually require the user to send the first message. Therefore, to run the complete initialization now, explicitly use `--bootstrap codex|claude`.
- Codex may require reviewing and trusting project hooks in `/hooks`; Claude Code may require the user to trust the project settings. Trust and confirmation are managed by each CLI, and the installer does not attempt to bypass them.

Treat hooks as part of the project code: inspect `.agent-maintenance/session-start.sh` and the generated settings before enabling them for the first time. The hook checks both the completion marker and whether the bootstrap prompt exists; it does not inspect the prompt's contents. When the prompt exists, it prints fixed text; the agent performs the actual file inspection and writing according to the bootstrap prompt and CLI permissions.

## Completion Marker

The bootstrap prompt requires the agent to write `.agent-maintenance/bootstrap-complete` only after completing the documentation review, verification, and report of remaining unknowns. In this repository, the marker means that the initialization process has run; it does not mean that all facts are known or that the maintainer has accepted pending decisions. If initialization is blocked or incomplete, the marker should remain absent so the hook continues prompting at later startups.

## Installer Regression Tests

The repository's `.github/workflows/installer-tests.yml` runs `bash tests/test-install.sh` on pushes, pull requests, and manual triggers. The suite uses isolated temporary directories and covers read-only Claude settings preflight; failures during template copying and provider writes; preservation of concurrent external changes; refusal to replace `AGENTS.md` or settings files; journal initialization and mid-transaction update failures; `AGENTS.md` baseline-snapshot failure; secondary rollback failures; rejection of symlink parent directories; deterministic syscall-boundary comparisons between the original PR head and the current implementation; and a real SIGKILL after Provider A publishes its active settings but before its staging link is removed, followed by a retry and unsafe-residue/lock-contention checks. Run `bash tests/test-install.sh` locally.

## Official Behavior Documentation

- [Codex project-level `AGENTS.md` instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Codex hooks](https://learn.chatgpt.com/docs/hooks)
- [Codex `exec` non-interactive mode and sandbox](https://learn.chatgpt.com/docs/non-interactive-mode)
- [Claude Code hooks](https://code.claude.com/docs/en/hooks)
- [Claude Code hooks guide](https://code.claude.com/docs/en/hooks-guide)
- [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference)

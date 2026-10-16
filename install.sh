#!/usr/bin/env bash
set -eo pipefail

# A raw-GitHub pipe has no script directory, so clone the full source tree before
# delegating to the regular installer. Local checkout/template installs stay offline.
if [[ -z "${BASH_SOURCE[0]:-}" ]]; then
  command -v git >/dev/null 2>&1 || { echo "ERROR: git is required for pipe installation." >&2; exit 127; }

  source_dir="$(mktemp -d)"
  trap 'rm -rf "$source_dir"' EXIT
  echo "Cloning Self-Evolution Flywheel source..."
  git clone --quiet --depth 1 --single-branch --branch main \
    "https://github.com/jack4leo/self-evolution-flywheel.git" "$source_dir"
  [[ -f "$source_dir/install.sh" && -f "$source_dir/prompts/bootstrap-project.md" ]] || {
    echo "ERROR: cloned source is missing installer files." >&2
    exit 2
  }

  bash "$source_dir/install.sh" "$@"
  exit $?
fi

usage() {
  cat <<'USAGE'
Usage: ./install.sh [--target DIR] [--no-hooks] [--bootstrap codex|claude]

Install Self-Evolution Flywheel project guidance into an existing repository.
Existing files are never overwritten. A different AGENTS.md may receive a
reviewed, marker-delimited routing block; other conflicts are preserved.
Existing Codex/Claude JSON settings are merged additively; invalid settings are
left untouched and cause an error.

Options:
  --target DIR              Destination project root (default: current directory)
  --no-hooks                Copy guidance without registering startup hooks
  --bootstrap codex|claude  After installation, start that CLI with the bootstrap prompt
  -h, --help                Show this help
USAGE
}

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ORIGINAL_ARGS=("$@")
TARGET_DIR="$PWD"
TRANSACTION_HELPER="$SOURCE_DIR/.agent-maintenance/installer-transaction.py"
[[ -f "$TRANSACTION_HELPER" ]] || {
  echo "ERROR: missing installer transaction helper: .agent-maintenance/installer-transaction.py" >&2
  exit 2
}
INSTALL_HOOKS=1
BOOTSTRAP_AGENT=""

while (($#)); do
  case "$1" in
    --target)
      [[ $# -ge 2 ]] || { echo "ERROR: --target requires a directory" >&2; exit 2; }
      TARGET_DIR="$2"
      shift 2
      ;;
    --no-hooks)
      INSTALL_HOOKS=0
      shift
      ;;
    --bootstrap)
      [[ $# -ge 2 ]] || { echo "ERROR: --bootstrap requires codex or claude" >&2; exit 2; }
      BOOTSTRAP_AGENT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "$BOOTSTRAP_AGENT" in
  ""|codex|claude) ;;
  *) echo "ERROR: --bootstrap must be codex or claude" >&2; exit 2 ;;
esac

[[ -d "$TARGET_DIR" ]] || { echo "ERROR: target directory does not exist: $TARGET_DIR" >&2; exit 2; }
TARGET_DIR="$(cd "$TARGET_DIR" && pwd -P)"
[[ -f "$SOURCE_DIR/prompts/bootstrap-project.md" ]] || {
  echo "ERROR: run this installer from a Self-Evolution Flywheel checkout/template copy." >&2
  exit 2
}

if [[ "$INSTALL_HOOKS" == 1 ]] && ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is required to safely merge Codex/Claude JSON settings." >&2
  exit 2
fi

# Project-local Codex hooks require the target itself to be the Git root.
if [[ "$INSTALL_HOOKS" == 1 ]]; then
  git_root="$(git -C "$TARGET_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
  if [[ -z "$git_root" ]]; then
    echo "ERROR: project hooks require a Git repository root. Use --no-hooks for file-only installation." >&2
    exit 2
  fi
  if [[ "$(cd "$git_root" && pwd -P)" != "$TARGET_DIR" ]]; then
    echo "ERROR: --target must be the Git repository root: $git_root" >&2
    echo "       Use --no-hooks to install files into a subdirectory." >&2
    exit 2
  fi
fi

# Keep one exclusive lock on the target directory for the full installer run.
# The helper execs this script with the locked directory descriptor inherited;
# SIGKILL closes it automatically and does not leave a lock file behind.
if [[ -n "${SELF_EVOLUTION_FLYWHEEL_LOCK_FD:-}" ]]; then
  python3 "$TRANSACTION_HELPER" verify-lock "$TARGET_DIR" "$SELF_EVOLUTION_FLYWHEEL_LOCK_FD" || exit $?
else
  exec python3 "$TRANSACTION_HELPER" lock-exec "$TARGET_DIR" "$(command -v bash)" "$SOURCE_DIR/install.sh" "${ORIGINAL_ARGS[@]}"
fi

# Recover only a provider staging hard link that can be tied to this installer's
# exact generated settings inode, owner, contents and two-link publish boundary.
if [[ "$INSTALL_HOOKS" == 1 ]]; then
  python3 "$TRANSACTION_HELPER" recover-hook-staging "$TARGET_DIR" codex
  python3 "$TRANSACTION_HELPER" recover-hook-staging "$TARGET_DIR" claude
fi

files=(
  AGENTS.md
  CLAUDE.md
  LESSONS.md
  install.sh
  .agent-maintenance/session-start.sh
  .agent-maintenance/installer-transaction.py
  .github/PULL_REQUEST_TEMPLATE.md
)
while IFS= read -r -d '' source_path; do
  files+=("${source_path#"$SOURCE_DIR"/}")
done < <(find "$SOURCE_DIR/docs" "$SOURCE_DIR/prompts" -type f \
  ! -path "$SOURCE_DIR/docs/source-and-extraction.md" -print0)
for relative_path in "${files[@]}"; do
  [[ -f "$SOURCE_DIR/$relative_path" ]] || {
    echo "ERROR: missing installer source file: $relative_path" >&2
    exit 2
  }
done

validate_destination_parents() {
  local relative_path="$1"
  local parent_path="${relative_path%/*}"
  [[ "$parent_path" == "$relative_path" ]] && return 0

  local current="$TARGET_DIR"
  local component
  local -a components
  IFS='/' read -r -a components <<< "$parent_path"
  for component in "${components[@]}"; do
    current="$current/$component"
    if [[ -L "$current" ]]; then
      echo "ERROR: target path traverses a symbolic-link directory: ${current#"$TARGET_DIR"/}" >&2
      return 1
    fi
    if [[ -e "$current" && ! -d "$current" ]]; then
      echo "ERROR: target path parent is not a directory: ${current#"$TARGET_DIR"/}" >&2
      return 1
    fi
  done
}

for relative_path in "${files[@]}"; do
  validate_destination_parents "$relative_path" || exit 3
done
if [[ "$INSTALL_HOOKS" == 1 ]]; then
  validate_destination_parents ".codex/hooks.json" || exit 3
  validate_destination_parents ".claude/settings.json" || exit 3
fi

preflight_hook_config() {
  local provider="$1"
  local settings_path="$2"
  python3 - "$provider" "$settings_path" <<'PY'
import json
import os
import stat
import sys

provider, filename = sys.argv[1:]
try:
    if os.path.lexists(filename):
        info = os.lstat(filename)
        if stat.S_ISLNK(info.st_mode):
            raise OSError("settings file is a symbolic link")
        if not stat.S_ISREG(info.st_mode):
            raise OSError("settings path is not a regular file")
        if info.st_nlink > 1:
            raise OSError("hard-linked settings files are not accepted")
        for name in os.listxattr(filename, follow_symlinks=False):
            os.getxattr(filename, name, follow_symlinks=False)
        with open(filename, encoding="utf-8") as handle:
            try:
                config = json.load(handle)
            finally:
                os.utime(handle.fileno(), ns=(info.st_atime_ns, info.st_mtime_ns))
    else:
        config = {}
except Exception as exc:
    print(f"ERROR: cannot safely prepare {filename}: {exc}; no files were installed.", file=sys.stderr)
    sys.exit(3)

if not isinstance(config, dict):
    print(f"ERROR: {filename} must contain a JSON object; no files were installed.", file=sys.stderr)
    sys.exit(3)
hooks = config.get("hooks", {})
if not isinstance(hooks, dict):
    print(f"ERROR: {filename}: 'hooks' must be a JSON object; no files were installed.", file=sys.stderr)
    sys.exit(3)
sessions = hooks.get("SessionStart", [])
if not isinstance(sessions, list):
    print(f"ERROR: {filename}: 'hooks.SessionStart' must be a JSON array; no files were installed.", file=sys.stderr)
    sys.exit(3)
for session in sessions:
    if isinstance(session, dict) and not isinstance(session.get("hooks", []), list):
        print(f"ERROR: {filename}: each SessionStart 'hooks' value must be a JSON array; no files were installed.", file=sys.stderr)
        sys.exit(3)

hook_commands = {
    "codex": 'bash "$(git rev-parse --show-toplevel)/.agent-maintenance/session-start.sh" codex',
    "claude": 'bash "${CLAUDE_PROJECT_DIR}/.agent-maintenance/session-start.sh" claude',
}
registered = any(
    isinstance(session, dict)
    and any(
        isinstance(handler, dict) and handler.get("command") == hook_commands[provider]
        for handler in session.get("hooks", [])
    )
    for session in sessions
)
if os.path.lexists(filename) and not registered:
    print(
        f"ERROR: cannot safely merge into pre-existing {filename}: POSIX has no portable conditional replace for non-cooperative writers; file preserved. Add the hook manually or use --no-hooks; no files were installed.",
        file=sys.stderr,
    )
    sys.exit(3)
PY
}

# Validate both providers before installing any template files or changing either
# provider's settings, so a later-provider parse/schema error cannot leave a partial install.
if [[ "$INSTALL_HOOKS" == 1 ]]; then
  preflight_hook_config codex "$TARGET_DIR/.codex/hooks.json"
  preflight_hook_config claude "$TARGET_DIR/.claude/settings.json"
fi

# Never register hooks against a pre-existing project script with different
# contents. Do this before copying files or changing either provider's settings.
if [[ "$INSTALL_HOOKS" == 1 ]]; then
  hook_script="$TARGET_DIR/.agent-maintenance/session-start.sh"
  if [[ -e "$hook_script" || -L "$hook_script" ]]; then
    if [[ ! -f "$hook_script" ]] || ! cmp -s "$SOURCE_DIR/.agent-maintenance/session-start.sh" "$hook_script"; then
      echo "ERROR: existing .agent-maintenance/session-start.sh differs from the installer; it was preserved and no startup hooks were registered." >&2
      echo "       Resolve the file conflict, or use --no-hooks for file-only installation." >&2
      exit 3
    fi
  fi
fi

# Detect predictable destination permission failures before writing any template
# files or provider settings. This checks only paths that would actually change.
preflight_write_access() {
  python3 - "$SOURCE_DIR" "$TARGET_DIR" "$INSTALL_HOOKS" "${files[@]}" <<'PY'
import filecmp
import json
import os
import stat
import sys

source_dir, target_dir, hooks_enabled, *relative_files = sys.argv[1:]
needed_directories = set()

def needs_managed_agents_write(source, destination):
    try:
        info = os.lstat(destination)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        return False
    return not filecmp.cmp(source, destination, shallow=False)

for relative in relative_files:
    destination = os.path.join(target_dir, relative)
    if os.path.lexists(destination):
        if relative == "AGENTS.md" and needs_managed_agents_write(
            os.path.join(source_dir, relative), destination
        ):
            needed_directories.add(os.path.dirname(destination))
        continue
    needed_directories.add(os.path.dirname(destination))

if hooks_enabled == "1":
    hook_commands = {
        ".codex/hooks.json": 'bash "$(git rev-parse --show-toplevel)/.agent-maintenance/session-start.sh" codex',
        ".claude/settings.json": 'bash "${CLAUDE_PROJECT_DIR}/.agent-maintenance/session-start.sh" claude',
    }
    for relative, command in hook_commands.items():
        filename = os.path.join(target_dir, relative)
        config = {}
        if os.path.lexists(filename):
            with open(filename, encoding="utf-8") as handle:
                original = os.fstat(handle.fileno())
                try:
                    config = json.load(handle)
                finally:
                    os.utime(
                        handle.fileno(),
                        ns=(original.st_atime_ns, original.st_mtime_ns),
                    )
        sessions = config.get("hooks", {}).get("SessionStart", [])
        already_registered = any(
            isinstance(session, dict)
            and any(
                isinstance(handler, dict) and handler.get("command") == command
                for handler in session.get("hooks", [])
            )
            for session in sessions
        )
        if not already_registered:
            needed_directories.add(os.path.dirname(filename))

for directory in sorted(needed_directories):
    candidate = directory
    while not os.path.lexists(candidate):
        parent = os.path.dirname(candidate)
        if parent == candidate:
            break
        candidate = parent
    try:
        info = os.lstat(candidate)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise OSError("nearest existing parent is not a real directory")
        if not os.access(candidate, os.W_OK | os.X_OK):
            raise PermissionError("directory is not writable and searchable")
    except OSError as exc:
        relative = os.path.relpath(directory, target_dir)
        print(
            f"ERROR: destination directory is not writable ({relative}): {exc}; no files were installed.",
            file=sys.stderr,
        )
        sys.exit(3)
PY
}

preflight_write_access

work_dir="$(mktemp -d)"
trap 'rm -rf -- "$work_dir"' EXIT
transaction_state="$work_dir/transaction.json"
python3 "$TRANSACTION_HELPER" init "$TARGET_DIR" "$transaction_state"
transaction_active=1
retain_work_dir=0

rollback_transaction() {
  python3 "$TRANSACTION_HELPER" rollback "$TARGET_DIR" "$transaction_state"
}

installer_cleanup() {
  local status=$?
  trap - EXIT
  if ((status != 0 && transaction_active)); then
    echo "ERROR: installation write failed; attempting to roll back this install." >&2
    if ! rollback_transaction; then
      echo "ERROR: rollback was incomplete; uncertain files and recovery entries were preserved rather than deleted." >&2
      retain_work_dir=1
    fi
  fi
  if ((retain_work_dir)); then
    echo "ERROR: rollback snapshots retained for recovery at: $work_dir" >&2
  else
    rm -rf -- "$work_dir"
  fi
  exit "$status"
}

trap installer_cleanup EXIT
managed_route_file="$work_dir/agents-routing.md"
cat > "$managed_route_file" <<'ROUTE'
<!-- BEGIN SELF-EVOLUTION-FLYWHEEL MANAGED ROUTING -->
## Self-Evolution Flywheel

- Before work, read `docs/project-profile.md`, `LESSONS.md`, and `docs/code-standards.md`; read the affected subsystem page when relevant.
- Follow repository evidence, documented validation, and permission boundaries; keep changes focused.
- Before finishing, update affected docs/tests, run applicable checks, and report verified results and limitations.
<!-- END SELF-EVOLUTION-FLYWHEEL MANAGED ROUTING -->
ROUTE

display_managed_diff() {
  python3 - "$1" "$2" <<'PY'
import subprocess
import sys
import unicodedata

try:
    process = subprocess.Popen(
        ["diff", "-u", "-L", "AGENTS.md (current)", "-L", "AGENTS.md (proposed)", *sys.argv[1:]],
        stdout=subprocess.PIPE,
    )
except OSError as exc:
    print(f"ERROR: could not start diff: {exc}", file=sys.stderr)
    sys.exit(2)

def escape_controls(raw):
    text = raw.decode("utf-8", "surrogateescape")
    escaped = []
    for char in text:
        codepoint = ord(char)
        category = unicodedata.category(char)
        if char == "\n":
            escaped.append(char)
        elif 0xDC80 <= codepoint <= 0xDCFF:
            escaped.append(f"\\x{codepoint - 0xDC00:02x}")
        elif category.startswith("C") or category in {"Zl", "Zp"}:
            if codepoint <= 0xFF:
                escaped.append(f"\\x{codepoint:02x}")
            elif codepoint <= 0xFFFF:
                escaped.append(f"\\u{codepoint:04x}")
            else:
                escaped.append(f"\\U{codepoint:08x}")
        else:
            escaped.append(char)
    return "".join(escaped)

assert process.stdout is not None
for line in iter(process.stdout.readline, b""):
    sys.stdout.buffer.write(escape_controls(line).encode("utf-8"))
    sys.stdout.buffer.flush()
process.stdout.close()
sys.exit(process.wait())
PY
}

prepare_managed_agents() {
  local destination_path="$1"
  local baseline="$work_dir/agents.original"
  local stage_file action_file action prompt answer diff_status=0

  if ! command -v python3 >/dev/null 2>&1; then
    echo "PRESERVED existing file (Python 3 is required to safely manage AGENTS.md): AGENTS.md" >&2
    return 1
  fi
  if ! python3 "$TRANSACTION_HELPER" snapshot "$TARGET_DIR" "AGENTS.md" "$baseline"; then
    echo "PRESERVED existing file (could not snapshot it safely): AGENTS.md" >&2
    return 1
  fi
  stage_file="$(mktemp "$work_dir/agents-stage.XXXXXX")"
  action_file="$work_dir/agents-action"
  if ! python3 - "$baseline" "$managed_route_file" "$stage_file" "$action_file" <<'PY'
import sys
from pathlib import Path

source, route_path, stage_path, action_path = map(Path, sys.argv[1:])
begin = "<!-- BEGIN SELF-EVOLUTION-FLYWHEEL MANAGED ROUTING -->"
end = "<!-- END SELF-EVOLUTION-FLYWHEEL MANAGED ROUTING -->"

try:
    original = source.read_bytes()
    text = original.decode("utf-8")
    route = route_path.read_text(encoding="utf-8")
except (OSError, UnicodeError) as exc:
    print(f"ERROR: cannot safely prepare managed routing for AGENTS.md: {exc}; left unchanged.", file=sys.stderr)
    sys.exit(3)

newline = "\r\n" if "\r\n" in text else "\n"
route = route.replace("\r\n", "\n").replace("\n", newline)
lines = text.splitlines(keepends=True)
markers = [line.rstrip("\r\n") for line in lines]
begin_positions = [i for i, line in enumerate(markers) if line == begin]
end_positions = [i for i, line in enumerate(markers) if line == end]

if not begin_positions and not end_positions:
    updated = route + newline + text
    action = "insert"
elif len(begin_positions) == 1 and len(end_positions) == 1 and begin_positions[0] < end_positions[0]:
    first, last = begin_positions[0], end_positions[0]
    prefix = "".join(lines[:first])
    suffix = "".join(lines[last + 1 :])
    updated = prefix + route + suffix
    action = "update"
else:
    print("ERROR: AGENTS.md has missing, duplicated, or out-of-order managed routing markers; left unchanged.", file=sys.stderr)
    sys.exit(3)

try:
    with stage_path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(updated)
    action_path.write_text(action + "\n", encoding="utf-8")
except OSError as exc:
    print(f"ERROR: cannot stage managed routing for AGENTS.md: {exc}; left unchanged.", file=sys.stderr)
    sys.exit(3)
PY
  then
    rm -f "$stage_file"
    return 1
  fi

  action="$(cat "$action_file")"
  if cmp -s "$baseline" "$stage_file"; then
    rm -f "$stage_file"
    echo "UNCHANGED managed routing block in AGENTS.md"
    return 0
  fi

  echo "Proposed diff for AGENTS.md (no changes applied yet):"
  display_managed_diff "$baseline" "$stage_file" || diff_status=$?
  if ((diff_status > 1)); then
    echo "PRESERVED existing file (could not display the proposed diff): AGENTS.md" >&2
    rm -f "$stage_file"
    return 1
  fi

  if [[ "$action" == "insert" ]]; then
    prompt="Insert the managed routing block at the beginning of AGENTS.md? [y/N] "
  else
    prompt="Update the existing managed routing block in AGENTS.md? [y/N] "
  fi
  if ! exec 3<>/dev/tty 2>/dev/null; then
    echo "PRESERVED AGENTS.md: explicit confirmation requires a controlling terminal." >&2
    rm -f "$stage_file"
    return 2
  fi
  if [[ ! -t 1 ]]; then
    display_managed_diff "$baseline" "$stage_file" >&3 || diff_status=$?
    if ((diff_status > 1)); then
      echo "PRESERVED existing file (could not display the proposed diff on the controlling terminal): AGENTS.md" >&2
      rm -f "$stage_file"
      exec 3>&-
      return 1
    fi
  fi
  printf '%s' "$prompt" >&3
  IFS= read -r answer <&3 || answer=""
  exec 3>&-
  case "$answer" in
    y|Y|yes|YES|Yes) ;;
    *)
      echo "PRESERVED AGENTS.md: managed routing change was not confirmed."
      rm -f "$stage_file"
      return 1
      ;;
  esac

  if ! cmp -s "$baseline" "$destination_path"; then
    echo "PRESERVED AGENTS.md: the file changed while awaiting confirmation; review and retry." >&2
    rm -f "$stage_file"
    return 1
  fi
  echo "PRESERVED AGENTS.md: safe automatic replacement is unavailable for non-cooperative writers; merge the reviewed block manually." >&2
  rm -f "$stage_file"
  return 3
}

prompt_ready=0
conflicts=()
confirmation_required=0
manual_merge_required=0
for relative_path in "${files[@]}"; do
  source_path="$SOURCE_DIR/$relative_path"
  destination_path="$TARGET_DIR/$relative_path"
  [[ -f "$source_path" ]] || { echo "ERROR: missing installer source file: $relative_path" >&2; exit 2; }

  if [[ -e "$destination_path" || -L "$destination_path" ]]; then
    if [[ "$relative_path" == "AGENTS.md" ]]; then
      if [[ -L "$destination_path" || ! -f "$destination_path" ]]; then
        echo "PRESERVED existing non-regular or symlink file: AGENTS.md"
        conflicts+=("$relative_path")
      elif [[ "$source_path" -ef "$destination_path" ]] || cmp -s "$source_path" "$destination_path"; then
        echo "UNCHANGED $relative_path"
      elif prepare_managed_agents "$destination_path"; then
        :
      else
        managed_status=$?
        echo "PRESERVED existing file (managed routing not applied): AGENTS.md"
        conflicts+=("$relative_path")
        if ((managed_status == 2)); then
          confirmation_required=1
        elif ((managed_status == 3)); then
          manual_merge_required=1
        fi
      fi
      continue
    fi
    if [[ "$source_path" -ef "$destination_path" ]] || cmp -s "$source_path" "$destination_path"; then
      echo "UNCHANGED $relative_path"
      [[ "$relative_path" == "prompts/bootstrap-project.md" ]] && prompt_ready=1
    else
      echo "PRESERVED existing file (not overwritten): $relative_path"
      conflicts+=("$relative_path")
    fi
    continue
  fi

  if copy_result="$(python3 "$TRANSACTION_HELPER" copy "$TARGET_DIR" "$relative_path" "$source_path" "$transaction_state")"; then
    :
  else
    copy_status=$?
    if ((copy_status == 10)); then
      echo "PRESERVED existing file (appeared during installation): $relative_path"
      conflicts+=("$relative_path")
      continue
    fi
    exit "$copy_status"
  fi
  echo "INSTALLED $relative_path"
  [[ "$relative_path" == "prompts/bootstrap-project.md" ]] && prompt_ready=1
done

merge_hook_config() {
  local provider="$1"
  local settings_path="$2"
  local relative_path="${settings_path#"$TARGET_DIR"/}"
  local result
  result="$(python3 "$TRANSACTION_HELPER" merge-hook "$TARGET_DIR" "$provider" "$relative_path" "$transaction_state")" || return $?
  printf '%s %s\n' "$result" "$settings_path"
}

if [[ "$INSTALL_HOOKS" == 1 ]]; then
  merge_hook_config codex "$TARGET_DIR/.codex/hooks.json"
  merge_hook_config claude "$TARGET_DIR/.claude/settings.json"
fi

# All file and provider writes succeeded. Later notices, optional bootstrap launch,
# or a confirmation-incomplete exit must not undo an otherwise completed install.
transaction_active=0

if ((${#conflicts[@]})); then
  echo
echo "Some existing project files were preserved. Review/merge these if you want the template version:"
  printf '  - %s\n' "${conflicts[@]}"
fi

if [[ "$INSTALL_HOOKS" == 1 ]]; then
  cat <<'NOTICE'

Startup hooks are registered in project-local settings. They only check for
.agent-maintenance/bootstrap-complete and print a short instruction; they do not
run shell commands from the project or fetch network content. Codex/Claude Code
may require you to review/trust the project hook before it runs. See docs/installation.md.
NOTICE
fi

if ((manual_merge_required)); then
  echo "ERROR: installation incomplete: the reviewed AGENTS.md block was not applied because conditional replacement is unavailable; merge it manually." >&2
  exit 4
fi

if ((confirmation_required)); then
  echo "ERROR: installation incomplete: AGENTS.md routing was not applied; rerun with a controlling terminal to review and confirm." >&2
  exit 4
fi

if [[ -n "$BOOTSTRAP_AGENT" ]]; then
  [[ "$prompt_ready" == 1 ]] || {
    echo "ERROR: an existing prompts/bootstrap-project.md differs from the template; preserved it and will not launch it automatically." >&2
    exit 3
  }
  case "$BOOTSTRAP_AGENT" in
    codex)
      command -v codex >/dev/null 2>&1 || { echo "ERROR: codex CLI not found in PATH." >&2; exit 127; }
      echo "Starting Codex with prompts/bootstrap-project.md (workspace-write sandbox)."
      cd "$TARGET_DIR"
      exec codex exec --sandbox workspace-write - < prompts/bootstrap-project.md
      ;;
    claude)
      command -v claude >/dev/null 2>&1 || { echo "ERROR: claude CLI not found in PATH." >&2; exit 127; }
      echo "Starting Claude Code with prompts/bootstrap-project.md."
      prompt="$(cat "$TARGET_DIR/prompts/bootstrap-project.md")"
      cd "$TARGET_DIR"
      exec claude "$prompt"
      ;;
  esac
fi

echo
echo "Installation complete for: $TARGET_DIR"
echo "To initialize now: ./install.sh --bootstrap codex  OR  ./install.sh --bootstrap claude"

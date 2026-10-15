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
TARGET_DIR="$PWD"
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

files=(
  AGENTS.md
  CLAUDE.md
  LESSONS.md
  install.sh
  .agent-maintenance/session-start.sh
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
            raise OSError("atomic replacement would break hard links")
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
rollback_paths=()
rollback_backups=()
rollback_existed=()
created_directories=()
transaction_active=1

record_change() {
  local path="$1"
  local index="${#rollback_paths[@]}"
  local backup="$work_dir/rollback-$index"
  if [[ -e "$path" || -L "$path" ]]; then
    if ! python3 - "$path" "$backup" <<'PY'
import os
import subprocess
import sys

source, backup = sys.argv[1:]
original = os.stat(source, follow_symlinks=False)
try:
    subprocess.run(["cp", "-a", "--", source, backup], check=True)
finally:
    os.utime(
        source,
        ns=(original.st_atime_ns, original.st_mtime_ns),
        follow_symlinks=False,
    )
PY
    then
      echo "ERROR: could not safely snapshot $path before writing." >&2
      return 1
    fi
    rollback_existed+=(1)
  else
    rollback_existed+=(0)
  fi
  rollback_paths+=("$path")
  rollback_backups+=("$backup")
}

record_missing_parent_directories() {
  local directory="$1"
  while [[ "$directory" != "$TARGET_DIR" && "$directory" != "/" \
      && ! -e "$directory" && ! -L "$directory" ]]; do
    created_directories+=("$directory")
    directory="$(dirname "$directory")"
  done
}

rollback_transaction() {
  local index path backup parent temporary status=0
  for ((index=${#rollback_paths[@]} - 1; index >= 0; index--)); do
    path="${rollback_paths[index]}"
    backup="${rollback_backups[index]}"
    if [[ "${rollback_existed[index]}" == 1 ]]; then
      if [[ -f "$path" ]] && cmp -s -- "$backup" "$path"; then
        continue
      fi
      parent="$(dirname "$path")"
      temporary="$(mktemp "$parent/.$(basename "$path").rollback.XXXXXX")" || {
        echo "ERROR: rollback could not stage the original file for $path." >&2
        status=1
        continue
      }
      if ! cp -a -- "$backup" "$temporary" || ! mv -f -- "$temporary" "$path"; then
        rm -f -- "$temporary"
        echo "ERROR: rollback could not restore the original file $path." >&2
        status=1
      fi
    elif ! rm -f -- "$path"; then
      echo "ERROR: rollback could not remove newly installed file $path." >&2
      status=1
    fi
  done
  for ((index=${#created_directories[@]} - 1; index >= 0; index--)); do
    rmdir -- "${created_directories[index]}" 2>/dev/null || true
  done
  return "$status"
}

installer_cleanup() {
  local status=$?
  trap - EXIT
  if ((status != 0 && transaction_active)); then
    echo "ERROR: installation write failed; attempting to roll back this install." >&2
    rollback_transaction || echo "ERROR: rollback was incomplete; inspect the listed paths before retrying." >&2
  fi
  rm -rf -- "$work_dir"
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

preserve_managed_agents_metadata() {
  python3 - "$1" "$2" <<'PY'
import os
import stat
import sys

source, staged = sys.argv[1:]
try:
    original = os.stat(source, follow_symlinks=False)
    if not stat.S_ISREG(original.st_mode):
        raise OSError("source is no longer a regular file")
    if original.st_nlink > 1:
        raise OSError("atomic replacement would break hard links")

    attributes = {
        name: os.getxattr(source, name, follow_symlinks=False)
        for name in os.listxattr(source, follow_symlinks=False)
    }
    staged_stat = os.stat(staged, follow_symlinks=False)
    if (staged_stat.st_uid, staged_stat.st_gid) != (original.st_uid, original.st_gid):
        os.chown(staged, original.st_uid, original.st_gid, follow_symlinks=False)
    os.chmod(staged, stat.S_IMODE(original.st_mode), follow_symlinks=False)

    for name in os.listxattr(staged, follow_symlinks=False):
        if name not in attributes:
            os.removexattr(staged, name, follow_symlinks=False)
    for name, value in attributes.items():
        os.setxattr(staged, name, value, follow_symlinks=False)
    os.utime(
        staged,
        ns=(original.st_atime_ns, original.st_mtime_ns),
        follow_symlinks=False,
    )

    result = os.stat(staged, follow_symlinks=False)
    result_attributes = {
        name: os.getxattr(staged, name, follow_symlinks=False)
        for name in os.listxattr(staged, follow_symlinks=False)
    }
    if (
        (result.st_uid, result.st_gid) != (original.st_uid, original.st_gid)
        or stat.S_IMODE(result.st_mode) != stat.S_IMODE(original.st_mode)
        or result.st_atime_ns != original.st_atime_ns
        or result.st_mtime_ns != original.st_mtime_ns
        or result_attributes != attributes
    ):
        raise OSError("staged metadata did not match the original")
except (OSError, AttributeError, NotImplementedError):
    print(
        "ERROR: could not safely preserve AGENTS.md ownership, permissions, ACLs, or extended attributes; left unchanged.",
        file=sys.stderr,
    )
    sys.exit(1)
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
  if ! cp -p "$destination_path" "$baseline"; then
    echo "PRESERVED existing file (could not snapshot it safely): AGENTS.md" >&2
    return 1
  fi
  stage_file="$(mktemp "$TARGET_DIR/.AGENTS.md.XXXXXX")"
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
  if ! preserve_managed_agents_metadata "$destination_path" "$stage_file"; then
    echo "PRESERVED AGENTS.md: could not safely preserve the original file metadata; left unchanged." >&2
    rm -f "$stage_file"
    return 1
  fi
  if ! record_change "$destination_path"; then
    echo "PRESERVED AGENTS.md: could not snapshot the original file for rollback." >&2
    rm -f "$stage_file"
    return 1
  fi
  if ! mv -f "$stage_file" "$destination_path"; then
    echo "PRESERVED AGENTS.md: could not apply the confirmed managed routing change." >&2
    rm -f "$stage_file"
    return 1
  fi
  if [[ "$action" == "insert" ]]; then
    echo "INSERTED managed routing block at the beginning of AGENTS.md"
  else
    echo "UPDATED managed routing block in AGENTS.md"
  fi
  return 0
}

prompt_ready=0
conflicts=()
confirmation_required=0
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

  record_missing_parent_directories "$(dirname "$destination_path")"
  mkdir -p "$(dirname "$destination_path")"
  record_change "$destination_path"
  cp -p "$source_path" "$destination_path"
  echo "INSTALLED $relative_path"
  [[ "$relative_path" == "prompts/bootstrap-project.md" ]] && prompt_ready=1
done

merge_hook_config() {
  local provider="$1"
  local settings_path="$2"
  python3 - "$provider" "$settings_path" <<'PY'
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

provider, filename = sys.argv[1], Path(sys.argv[2])
if provider == "codex":
    entry = {
        "matcher": "startup|resume|clear|compact|fork",
        "hooks": [{
            "type": "command",
            "command": 'bash "$(git rev-parse --show-toplevel)/.agent-maintenance/session-start.sh" codex',
            "timeout": 5,
            "additionalContextLimit": 1200,
        }],
    }
else:
    entry = {
        "matcher": "startup|resume|clear|compact|fork",
        "hooks": [{
            "type": "command",
            "command": 'bash "${CLAUDE_PROJECT_DIR}/.agent-maintenance/session-start.sh" claude',
        }],
    }

if os.path.lexists(filename):
    try:
        original = os.lstat(filename)
        if stat.S_ISLNK(original.st_mode):
            raise OSError("settings file is a symbolic link")
        if not stat.S_ISREG(original.st_mode):
            raise OSError("settings path is not a regular file")
        if original.st_nlink > 1:
            raise OSError("atomic replacement would break hard links")
        attributes = {
            name: os.getxattr(filename, name, follow_symlinks=False)
            for name in os.listxattr(filename, follow_symlinks=False)
        }
        with filename.open(encoding="utf-8") as handle:
            try:
                config = json.load(handle)
            finally:
                os.utime(handle.fileno(), ns=(original.st_atime_ns, original.st_mtime_ns))
    except Exception as exc:
        print(f"ERROR: cannot safely parse {filename}: {exc}", file=sys.stderr)
        print("       No settings were changed; merge the hook manually.", file=sys.stderr)
        sys.exit(3)
    old_mode = stat.S_IMODE(original.st_mode)
else:
    config, old_mode, original, attributes = {}, 0o644, None, {}

if not isinstance(config, dict):
    print(f"ERROR: {filename} must contain a JSON object; left untouched.", file=sys.stderr)
    sys.exit(3)
hooks = config.setdefault("hooks", {})
if not isinstance(hooks, dict):
    print(f"ERROR: {filename}: 'hooks' must be a JSON object; left untouched.", file=sys.stderr)
    sys.exit(3)
sessions = hooks.setdefault("SessionStart", [])
if not isinstance(sessions, list):
    print(f"ERROR: {filename}: 'hooks.SessionStart' must be a JSON array; left untouched.", file=sys.stderr)
    sys.exit(3)

command = entry["hooks"][0]["command"]
for existing in sessions:
    if not isinstance(existing, dict):
        continue
    existing_handlers = existing.get("hooks", [])
    if not isinstance(existing_handlers, list):
        continue
    for handler in existing_handlers:
        if isinstance(handler, dict) and handler.get("command") == command:
            print(f"HOOK PRESENT {filename}")
            sys.exit(0)

sessions.append(entry)
filename.parent.mkdir(parents=True, exist_ok=True)
fd, temp_name = tempfile.mkstemp(prefix=f".{filename.name}.", dir=filename.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    if original is not None:
        os.chown(temp_name, original.st_uid, original.st_gid, follow_symlinks=False)
    os.chmod(temp_name, old_mode)
    for name in os.listxattr(temp_name, follow_symlinks=False):
        if name not in attributes:
            os.removexattr(temp_name, name, follow_symlinks=False)
    for name, value in attributes.items():
        os.setxattr(temp_name, name, value, follow_symlinks=False)
    if original is not None:
        os.utime(
            temp_name,
            ns=(original.st_atime_ns, original.st_mtime_ns),
            follow_symlinks=False,
        )
        result = os.stat(temp_name, follow_symlinks=False)
        result_attributes = {
            name: os.getxattr(temp_name, name, follow_symlinks=False)
            for name in os.listxattr(temp_name, follow_symlinks=False)
        }
        if (
            (result.st_uid, result.st_gid) != (original.st_uid, original.st_gid)
            or stat.S_IMODE(result.st_mode) != stat.S_IMODE(original.st_mode)
            or result.st_atime_ns != original.st_atime_ns
            or result.st_mtime_ns != original.st_mtime_ns
            or result_attributes != attributes
        ):
            raise OSError("staged settings metadata did not match the original")
    os.replace(temp_name, filename)
except Exception:
    try:
        os.unlink(temp_name)
    except OSError:
        pass
    raise
print(f"HOOK ADDED {filename}")
PY
}

if [[ "$INSTALL_HOOKS" == 1 ]]; then
  for settings_path in "$TARGET_DIR/.codex/hooks.json" "$TARGET_DIR/.claude/settings.json"; do
    record_missing_parent_directories "$(dirname "$settings_path")"
    record_change "$settings_path"
  done
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

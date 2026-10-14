#!/usr/bin/env bash
set -eo pipefail

usage() {
  cat <<'USAGE'
Usage: ./install.sh [--target DIR] [--no-hooks] [--bootstrap codex|claude]

Install Self-Evolution Flywheel project guidance into an existing repository.
Existing files are never overwritten. Existing Codex/Claude JSON settings are
merged additively; invalid settings are left untouched and cause an error.

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

prompt_ready=0
conflicts=()
for relative_path in "${files[@]}"; do
  source_path="$SOURCE_DIR/$relative_path"
  destination_path="$TARGET_DIR/$relative_path"
  [[ -f "$source_path" ]] || { echo "ERROR: missing installer source file: $relative_path" >&2; exit 2; }

  if [[ -e "$destination_path" ]]; then
    if [[ "$source_path" -ef "$destination_path" ]] || cmp -s "$source_path" "$destination_path"; then
      echo "UNCHANGED $relative_path"
      [[ "$relative_path" == "prompts/bootstrap-project.md" ]] && prompt_ready=1
    else
      echo "PRESERVED existing file (not overwritten): $relative_path"
      conflicts+=("$relative_path")
    fi
    continue
  fi

  mkdir -p "$(dirname "$destination_path")"
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

if filename.exists():
    try:
        with filename.open(encoding="utf-8") as handle:
            config = json.load(handle)
    except Exception as exc:
        print(f"ERROR: cannot safely parse {filename}: {exc}", file=sys.stderr)
        print("       No settings were changed; merge the hook manually.", file=sys.stderr)
        sys.exit(3)
    old_mode = stat.S_IMODE(filename.stat().st_mode)
else:
    config, old_mode = {}, 0o644

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
    for handler in existing.get("hooks", []):
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
    os.chmod(temp_name, old_mode)
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
  merge_hook_config codex "$TARGET_DIR/.codex/hooks.json"
  merge_hook_config claude "$TARGET_DIR/.claude/settings.json"
fi

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

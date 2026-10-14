#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

init_git_target() {
  mkdir -p "$1"
  git -C "$1" init -q
}

# A different pre-existing startup script must block installation before any
# project files or either provider's hook settings are written.
conflict_target="$TMP_DIR/conflict-target"
init_git_target "$conflict_target"
mkdir -p "$conflict_target/.agent-maintenance"
printf '#!/usr/bin/env bash\necho user-owned\n' > "$conflict_target/.agent-maintenance/session-start.sh"
cp "$conflict_target/.agent-maintenance/session-start.sh" "$TMP_DIR/original-session-start.sh"
if bash "$REPO_ROOT/install.sh" --target "$conflict_target" > "$TMP_DIR/conflict.log" 2>&1; then
  fail "installer accepted a conflicting session-start.sh"
fi
grep -Fq 'existing .agent-maintenance/session-start.sh differs' "$TMP_DIR/conflict.log" \
  || fail "conflict error was not clear"
cmp -s "$TMP_DIR/original-session-start.sh" "$conflict_target/.agent-maintenance/session-start.sh" \
  || fail "installer changed the user-owned startup script"
[[ ! -e "$conflict_target/AGENTS.md" ]] || fail "installer copied files before rejecting the conflict"
[[ ! -e "$conflict_target/.codex/hooks.json" ]] || fail "Codex hook settings were written despite the conflict"
[[ ! -e "$conflict_target/.claude/settings.json" ]] || fail "Claude hook settings were written despite the conflict"

# File-only installation remains available and still preserves the conflicting file.
bash "$REPO_ROOT/install.sh" --target "$conflict_target" --no-hooks > "$TMP_DIR/no-hooks.log" 2>&1
cmp -s "$TMP_DIR/original-session-start.sh" "$conflict_target/.agent-maintenance/session-start.sh" \
  || fail "--no-hooks overwrote the user-owned startup script"
[[ -f "$conflict_target/AGENTS.md" ]] || fail "--no-hooks did not install project guidance"
[[ ! -e "$conflict_target/.codex/hooks.json" ]] || fail "--no-hooks registered a Codex hook"
[[ ! -e "$conflict_target/.claude/settings.json" ]] || fail "--no-hooks registered a Claude hook"

# Hook-enabled installation rejects non-Git targets; --no-hooks can install there.
non_git_target="$TMP_DIR/non-git-target"
mkdir -p "$non_git_target"
if bash "$REPO_ROOT/install.sh" --target "$non_git_target" > "$TMP_DIR/non-git.log" 2>&1; then
  fail "installer accepted a non-Git target with hooks enabled"
fi
grep -Fq 'project hooks require a Git repository root' "$TMP_DIR/non-git.log" \
  || fail "non-Git rejection was not clear"
[[ ! -e "$non_git_target/AGENTS.md" ]] || fail "installer copied files before rejecting the non-Git target"
bash "$REPO_ROOT/install.sh" --target "$non_git_target" --no-hooks > "$TMP_DIR/non-git-no-hooks.log" 2>&1
[[ -f "$non_git_target/AGENTS.md" ]] || fail "--no-hooks did not install into a non-Git target"
[[ ! -e "$non_git_target/.codex/hooks.json" && ! -e "$non_git_target/.claude/settings.json" ]] \
  || fail "non-Git --no-hooks installation registered a hook"

# A clean Git root still receives both hooks through additive JSON merges.
clean_target="$TMP_DIR/clean-target"
init_git_target "$clean_target"
bash "$REPO_ROOT/install.sh" --target "$clean_target" > "$TMP_DIR/clean.log" 2>&1
python3 - "$clean_target" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
expected = {
    ".codex/hooks.json": 'bash "$(git rev-parse --show-toplevel)/.agent-maintenance/session-start.sh" codex',
    ".claude/settings.json": 'bash "${CLAUDE_PROJECT_DIR}/.agent-maintenance/session-start.sh" claude',
}
for relative_path, command in expected.items():
    config = json.loads((root / relative_path).read_text(encoding="utf-8"))
    handlers = [
        handler
        for session in config["hooks"]["SessionStart"]
        for handler in session.get("hooks", [])
    ]
    assert any(handler.get("command") == command for handler in handlers), relative_path
PY

echo "PASS: installer conflict and target-mode regression tests"

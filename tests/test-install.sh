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

run_installer_in_pty() {
  python3 - "$1" "$2" "$3" "$4" <<'PY'
import os
import pty
import select
import signal
import sys
import time
from pathlib import Path

installer, target, answer, output_path = sys.argv[1:]
pid, master = pty.fork()
if pid == 0:
    os.execv("/bin/bash", ["/bin/bash", installer, "--target", target, "--no-hooks"])

output = bytearray()
sent_answer = False
deadline = time.monotonic() + 60
status = None
while time.monotonic() < deadline:
    ready, _, _ = select.select([master], [], [], 0.1)
    if ready:
        try:
            chunk = os.read(master, 4096)
        except OSError:
            chunk = b""
        output.extend(chunk)
        if not sent_answer and b"[y/N] " in output:
            os.write(master, answer.encode("utf-8") + b"\n")
            sent_answer = True
    waited, status = os.waitpid(pid, os.WNOHANG)
    if waited:
        break
else:
    os.kill(pid, signal.SIGTERM)
    _, status = os.waitpid(pid, 0)
    Path(output_path).write_bytes(output)
    raise SystemExit("installer did not finish within 60 seconds")

Path(output_path).write_bytes(output)
if not sent_answer:
    raise SystemExit("installer did not display its confirmation prompt")
raise SystemExit(os.waitstatus_to_exitcode(status))
PY
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

# A differing AGENTS.md is never replaced silently: show the complete proposed
# diff, ask on the controlling terminal, and insert the managed block at line 1.
agents_target="$TMP_DIR/agents-target"
mkdir -p "$agents_target"
printf '# Maintainer-owned guidance\n\nKeep this text byte-for-byte.\n' > "$agents_target/AGENTS.md"
cp "$agents_target/AGENTS.md" "$TMP_DIR/agents-before.md"
run_installer_in_pty "$REPO_ROOT/install.sh" "$agents_target" y "$TMP_DIR/agents-insert.log"
grep -Fq -- '--- AGENTS.md (current)' "$TMP_DIR/agents-insert.log" \
  || fail "AGENTS.md proposed diff was not displayed"
grep -Fq 'Insert the managed routing block at the beginning of AGENTS.md? [y/N]' "$TMP_DIR/agents-insert.log" \
  || fail "AGENTS.md insertion did not request maintainer confirmation"
python3 - "$agents_target/AGENTS.md" "$TMP_DIR/agents-before.md" <<'PY'
import sys
from pathlib import Path

installed, original = map(Path, sys.argv[1:])
text = installed.read_text(encoding="utf-8")
before = original.read_text(encoding="utf-8")
begin = "<!-- BEGIN SELF-EVOLUTION-FLYWHEEL MANAGED ROUTING -->"
end = "<!-- END SELF-EVOLUTION-FLYWHEEL MANAGED ROUTING -->"
assert text.startswith(begin + "\n"), "managed block was not inserted at the first line"
assert text.count(begin) == 1 and text.count(end) == 1, "managed block markers are not unique"
assert text.endswith("\n" + before), "maintainer-owned AGENTS.md content was not preserved"
PY

# Declining confirmation leaves AGENTS.md unchanged and reports the conflict.
agents_decline_target="$TMP_DIR/agents-decline-target"
mkdir -p "$agents_decline_target"
printf '# Keep me\n' > "$agents_decline_target/AGENTS.md"
cp "$agents_decline_target/AGENTS.md" "$TMP_DIR/agents-decline-before.md"
run_installer_in_pty "$REPO_ROOT/install.sh" "$agents_decline_target" "" "$TMP_DIR/agents-decline.log"
cmp -s "$TMP_DIR/agents-decline-before.md" "$agents_decline_target/AGENTS.md" \
  || fail "declining AGENTS.md insertion changed the file"
grep -Fq 'managed routing change was not confirmed' "$TMP_DIR/agents-decline.log" \
  || fail "declined AGENTS.md insertion was not reported"

# Re-running is idempotent. A changed template updates only the marked block
# after a fresh diff/confirmation, preserving all user-owned surrounding text.
bash "$REPO_ROOT/install.sh" --target "$agents_target" --no-hooks > "$TMP_DIR/agents-idempotent.log" 2>&1
grep -Fq 'UNCHANGED managed routing block in AGENTS.md' "$TMP_DIR/agents-idempotent.log" \
  || fail "current managed AGENTS.md block was not recognized as idempotent"
if grep -Fq '[y/N]' "$TMP_DIR/agents-idempotent.log"; then
  fail "idempotent AGENTS.md installation unexpectedly requested confirmation"
fi

updated_source="$TMP_DIR/updated-source"
mkdir -p "$updated_source"
tar -cf - --exclude='./.git' -C "$REPO_ROOT" . | tar -xf - -C "$updated_source"
python3 - "$updated_source/install.sh" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
old = "- Follow repository evidence, documented validation, and permission boundaries; keep changes focused."
new = "- Follow repository evidence, permission boundaries, and the target project's documented validation."
assert old in text, "test fixture could not find the managed route line"
path.write_text(text.replace(old, new, 1), encoding="utf-8")
PY
run_installer_in_pty "$updated_source/install.sh" "$agents_target" y "$TMP_DIR/agents-update.log" \
  || fail "confirming a managed AGENTS.md update failed"
grep -Fq 'Update the existing managed routing block in AGENTS.md? [y/N]' "$TMP_DIR/agents-update.log" \
  || fail "changed managed block did not request confirmation"
grep -Fq 'UPDATED managed routing block in AGENTS.md' "$TMP_DIR/agents-update.log" \
  || fail "confirmed managed block was not updated"
grep -Fq 'Follow repository evidence, permission boundaries, and the target project' "$agents_target/AGENTS.md" \
  || fail "updated managed routing text was not installed"
grep -Fq '# Maintainer-owned guidance' "$agents_target/AGENTS.md" \
  || fail "managed block update damaged user-owned AGENTS.md content"
bash "$updated_source/install.sh" --target "$agents_target" --no-hooks > "$TMP_DIR/agents-update-idempotent.log" 2>&1
grep -Fq 'UNCHANGED managed routing block in AGENTS.md' "$TMP_DIR/agents-update-idempotent.log" \
  || fail "updated managed block was not idempotent"

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

# A script streamed through stdin has no BASH_SOURCE path. Simulate curl returning
# a complete repository archive and verify pipe mode delegates to the normal installer.
archive="$TMP_DIR/source.tar.gz"
tar -czf "$archive" --exclude='./.git' -C "$REPO_ROOT" .
mock_bin="$TMP_DIR/mock-bin"
mkdir -p "$mock_bin"
cat > "$mock_bin/curl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cat "$SELF_EVOLUTION_TEST_ARCHIVE"
SH
chmod +x "$mock_bin/curl"
remote_target="$TMP_DIR/remote-target"
mkdir -p "$remote_target"
(
  cd "$remote_target"
  PATH="$mock_bin:$PATH" SELF_EVOLUTION_TEST_ARCHIVE="$archive" \
    bash -c 'cat "$1" | bash -s -- --no-hooks' _ "$REPO_ROOT/install.sh"
) > "$TMP_DIR/remote.log" 2>&1
grep -Fq "Installation complete for: $remote_target" "$TMP_DIR/remote.log" \
  || fail "pipe installer did not complete in the current target directory"
[[ -f "$remote_target/prompts/bootstrap-project.md" ]] \
  || fail "pipe installer did not install the bootstrap prompt"

echo "PASS: installer conflict and target-mode regression tests"

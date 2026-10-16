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

# The child may exit while its final diagnostics are still queued on the PTY.
last_output = time.monotonic()
drain_deadline = last_output + 1
while time.monotonic() < drain_deadline:
    ready, _, _ = select.select([master], [], [], 0.1)
    if not ready:
        if time.monotonic() - last_output >= 0.2:
            break
        continue
    try:
        chunk = os.read(master, 4096)
    except OSError:
        break
    if not chunk:
        break
    output.extend(chunk)
    last_output = time.monotonic()

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

# Invalid settings in the later provider are rejected before any template or
# earlier-provider file is written.
invalid_claude_target="$TMP_DIR/invalid-claude-target"
init_git_target "$invalid_claude_target"
mkdir -p "$invalid_claude_target/.codex" "$invalid_claude_target/.claude"
printf '{"hooks":{}}\n' > "$invalid_claude_target/.codex/hooks.json"
printf '{invalid json\n' > "$invalid_claude_target/.claude/settings.json"
cp "$invalid_claude_target/.codex/hooks.json" "$TMP_DIR/codex-before-invalid-claude.json"
cp "$invalid_claude_target/.claude/settings.json" "$TMP_DIR/claude-before-invalid.json"
if bash "$REPO_ROOT/install.sh" --target "$invalid_claude_target" > "$TMP_DIR/invalid-claude.log" 2>&1; then
  fail "installer accepted invalid Claude settings"
fi
[[ ! -e "$invalid_claude_target/AGENTS.md" ]] || fail "invalid later-provider settings still installed template files"
cmp -s "$TMP_DIR/codex-before-invalid-claude.json" "$invalid_claude_target/.codex/hooks.json" \
  || fail "invalid Claude settings caused an earlier Codex settings write"
cmp -s "$TMP_DIR/claude-before-invalid.json" "$invalid_claude_target/.claude/settings.json" \
  || fail "installer changed invalid Claude settings"
grep -Fq 'no files were installed' "$TMP_DIR/invalid-claude.log" \
  || fail "cross-provider preflight failure was not reported"

# Fail the transaction journal's atomic publication before any project write.
journal_failure_modules="$TMP_DIR/journal-failure-modules"
mkdir -p "$journal_failure_modules"
cat > "$journal_failure_modules/sitecustomize.py" <<'PY'
import os

_replace = os.replace
def _fail_journal(src, dst, *args, **kwargs):
    if os.path.basename(os.fspath(dst)) == "transaction.json":
        raise OSError("injected transaction journal failure")
    return _replace(src, dst, *args, **kwargs)
os.replace = _fail_journal
PY
journal_failure_target="$TMP_DIR/journal-failure-target"
init_git_target "$journal_failure_target"
if PYTHONPATH="$journal_failure_modules" bash "$REPO_ROOT/install.sh" --target "$journal_failure_target" > "$TMP_DIR/journal-failure.log" 2>&1; then
  fail "installer succeeded without a transaction journal"
fi
grep -Fq 'injected transaction journal failure' "$TMP_DIR/journal-failure.log" \
  || fail "transaction journal failure was not visible"
[[ ! -e "$journal_failure_target/AGENTS.md" && ! -e "$journal_failure_target/.codex/hooks.json" \
    && ! -e "$journal_failure_target/.claude/settings.json" ]] \
  || fail "transaction journal failure occurred after project files were written"

journal_update_modules="$TMP_DIR/journal-update-modules"
mkdir -p "$journal_update_modules"
cat > "$journal_update_modules/sitecustomize.py" <<'PY'
import os

_replace = os.replace
def _fail_nth_journal_update(src, dst, *args, **kwargs):
    if os.path.basename(os.fspath(dst)) == "transaction.json":
        counter = os.environ["JOURNAL_REPLACE_COUNTER"]
        try:
            with open(counter, encoding="ascii") as handle:
                count = int(handle.read())
        except FileNotFoundError:
            count = 0
        count += 1
        with open(counter, "w", encoding="ascii") as handle:
            handle.write(str(count))
        if count == int(os.environ["JOURNAL_FAIL_AT"]):
            raise OSError("injected transaction journal update failure")
    return _replace(src, dst, *args, **kwargs)
os.replace = _fail_nth_journal_update
PY
journal_update_target="$TMP_DIR/journal-update-target"
init_git_target "$journal_update_target"
counter_file="$TMP_DIR/journal-update-counter"
if PYTHONPATH="$journal_update_modules" JOURNAL_REPLACE_COUNTER="$counter_file" JOURNAL_FAIL_AT=6 \
    bash "$REPO_ROOT/install.sh" --target "$journal_update_target" > "$TMP_DIR/journal-update.log" 2>&1; then
  fail "installer succeeded after a transaction journal update failure"
fi
grep -Fq 'injected transaction journal update failure' "$TMP_DIR/journal-update.log" \
  || fail "mid-transaction journal failure was not visible"
[[ -d "$journal_update_target/.agent-maintenance" ]] \
  || fail "journal update rollback did not conservatively preserve its created directory"
grep -Fq 'PRESERVED directory created before transaction journal failure' "$TMP_DIR/journal-update.log" \
  || fail "directory preserved after journal failure was not reported"
[[ ! -e "$journal_update_target/AGENTS.md" && ! -e "$journal_update_target/CLAUDE.md" \
    && ! -e "$journal_update_target/LESSONS.md" ]] \
  || fail "journal update failure left earlier template files at their active paths"
grep -Fq 'rollback was incomplete' "$TMP_DIR/journal-update.log" \
  || fail "post-journal-failure recovery status was not made visible"
recovery_dir="$(sed -n 's/^ERROR: rollback snapshots retained for recovery at: //p' "$TMP_DIR/journal-update.log" | tail -n 1)"
[[ -n "$recovery_dir" && -f "$recovery_dir/transaction.json" ]] \
  || fail "post-journal-failure transaction log was not retained"

# Fail the observable AGENTS baseline snapshot output; preserve AGENTS.md while
# allowing unrelated template files to install and report the conflict.
snapshot_failure_modules="$TMP_DIR/snapshot-failure-modules"
mkdir -p "$snapshot_failure_modules"
cat > "$snapshot_failure_modules/sitecustomize.py" <<'PY'
import builtins
import os

_open = builtins.open
def _fail_agents_snapshot(file, *args, **kwargs):
    try:
        path = os.fspath(file)
    except TypeError:
        path = ""
    mode = args[0] if args else kwargs.get("mode", "r")
    if os.path.basename(path) == "agents.original" and "w" in mode:
        raise OSError("injected AGENTS baseline snapshot failure")
    return _open(file, *args, **kwargs)
builtins.open = _fail_agents_snapshot
PY
snapshot_failure_target="$TMP_DIR/snapshot-failure-target"
mkdir -p "$snapshot_failure_target"
printf '# Preserve during snapshot failure\n' > "$snapshot_failure_target/AGENTS.md"
cp "$snapshot_failure_target/AGENTS.md" "$TMP_DIR/snapshot-failure-before.md"
PYTHONPATH="$snapshot_failure_modules" bash "$REPO_ROOT/install.sh" --target "$snapshot_failure_target" --no-hooks > "$TMP_DIR/snapshot-failure.log" 2>&1
cmp -s "$TMP_DIR/snapshot-failure-before.md" "$snapshot_failure_target/AGENTS.md" \
  || fail "AGENTS snapshot failure changed the existing file"
grep -Fq 'injected AGENTS baseline snapshot failure' "$TMP_DIR/snapshot-failure.log" \
  || fail "AGENTS snapshot failure was not visible"
grep -Fq 'Some existing project files were preserved' "$TMP_DIR/snapshot-failure.log" \
  || fail "AGENTS snapshot failure was not surfaced as a conflict"
[[ -f "$snapshot_failure_target/CLAUDE.md" ]] \
  || fail "AGENTS snapshot failure incorrectly blocked unrelated safe template copies"

# A read-only later-provider directory must be rejected before any project file
# or earlier-provider setting is written. Run as an unprivileged user even when
# the suite itself is invoked as root so the permission state matches real use.
readonly_claude_target="$TMP_DIR/readonly-claude-target"
init_git_target "$readonly_claude_target"
mkdir -p "$readonly_claude_target/.codex" "$readonly_claude_target/.claude"
chmod 555 "$readonly_claude_target/.claude"
python3 - "$REPO_ROOT/install.sh" "$readonly_claude_target" "$TMP_DIR/readonly-claude.log" "$TMP_DIR" <<'PY'
import os
import subprocess
import sys
from pathlib import Path

installer, target, output_path, temp_root = sys.argv[1:]
if os.geteuid() == 0:
    os.chmod(temp_root, 0o755)
    for path in Path(target).rglob("*"):
        os.chown(path, 65534, 65534, follow_symlinks=False)
    os.chown(target, 65534, 65534)

def drop_privileges():
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)

with Path(output_path).open("wb") as output:
    result = subprocess.run(
        ["bash", installer, "--target", target],
        stdout=output,
        stderr=subprocess.STDOUT,
        preexec_fn=drop_privileges if os.geteuid() == 0 else None,
    )
if result.returncode == 0:
    raise SystemExit("installer accepted a read-only Claude settings directory")
PY
chmod 755 "$readonly_claude_target/.claude"
[[ ! -e "$readonly_claude_target/AGENTS.md" ]] \
  || fail "read-only Claude target left template files installed"
[[ ! -e "$readonly_claude_target/.codex/hooks.json" && ! -e "$readonly_claude_target/.claude/settings.json" ]] \
  || fail "read-only Claude preflight created provider settings"
grep -Fq 'no files were installed' "$TMP_DIR/readonly-claude.log" \
  || fail "read-only Claude preflight failure was not reported before installation"

# Simulate a permission change after preflight but before Claude settings can be
# staged. Earlier template and Codex writes must be rolled back.
rollback_target="$TMP_DIR/rollback-target"
init_git_target "$rollback_target"
mkdir -p "$rollback_target/.codex" "$rollback_target/.claude"
rollback_python_bin="$TMP_DIR/rollback-python-bin"
mkdir -p "$rollback_python_bin"
real_python3="$(command -v python3)"
cat > "$rollback_python_bin/python3" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [[ -n "${TEST_INJECT_MODE:-}" && -e "$TEST_CODEX" && ! -e "$TEST_INJECT_MARKER" ]]; then
  touch "$TEST_INJECT_MARKER"
  if [[ "$TEST_INJECT_MODE" == "concurrent" ]]; then
    cat "$TEST_CODEX_EXPECTED" > "$TEST_CODEX"
    cat "$TEST_AGENTS_EXPECTED" > "$TEST_AGENTS"
  fi
  chmod 555 "$TEST_CLAUDE_DIR"
fi
exec "$TEST_REAL_PYTHON3" "$@"
SH
chmod +x "$rollback_python_bin/python3"
python3 - "$REPO_ROOT/install.sh" "$rollback_target" "$TMP_DIR/rollback.log" "$TMP_DIR" "$rollback_python_bin" "$real_python3" <<'PY'
import os
import subprocess
import sys
from pathlib import Path

installer, target, output_path, temp_root, mock_bin, real_python = sys.argv[1:]
if os.geteuid() == 0:
    os.chmod(temp_root, 0o755)
    for root in (Path(target), Path(mock_bin)):
        for path in root.rglob("*"):
            os.chown(path, 65534, 65534, follow_symlinks=False)
        os.chown(root, 65534, 65534)

def drop_privileges():
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)

environment = os.environ.copy()
environment["PATH"] = mock_bin + os.pathsep + environment["PATH"]
environment["TEST_CLAUDE_DIR"] = str(Path(target) / ".claude")
environment["TEST_CODEX"] = str(Path(target) / ".codex/hooks.json")
environment["TEST_INJECT_MARKER"] = str(Path(target) / ".test-injected")
environment["TEST_REAL_PYTHON3"] = real_python
environment["TEST_INJECT_MODE"] = "rollback"
with Path(output_path).open("wb") as output:
    result = subprocess.run(
        ["bash", installer, "--target", target],
        stdout=output,
        stderr=subprocess.STDOUT,
        env=environment,
        preexec_fn=drop_privileges if os.geteuid() == 0 else None,
    )
if result.returncode == 0:
    raise SystemExit("injected Claude settings write failure unexpectedly succeeded")
PY
chmod 755 "$rollback_target/.claude"
[[ ! -e "$rollback_target/AGENTS.md" && ! -e "$rollback_target/prompts/bootstrap-project.md" ]] \
  || fail "mid-install Claude write failure left template files behind"
[[ ! -e "$rollback_target/.codex/hooks.json" && ! -e "$rollback_target/.claude/settings.json" ]] \
  || fail "mid-install Claude failure left provider settings at their active paths"
grep -Fq 'attempting to roll back this install' "$TMP_DIR/rollback.log" \
  || fail "mid-install write failure did not report rollback"
grep -Fq 'rollback was incomplete' "$TMP_DIR/rollback.log" \
  || fail "rollback did not disclose preserved recovery entries"
recovery_dir="$(sed -n 's/^ERROR: rollback snapshots retained for recovery at: //p' "$TMP_DIR/rollback.log" | tail -n 1)"
[[ -n "$recovery_dir" && -f "$recovery_dir/transaction.json" ]] \
  || fail "conservative rollback did not retain its recovery journal"
compgen -G "$rollback_target/.codex/.hooks.json.rollback-*" >/dev/null \
  || fail "rollback deleted the uncertain Codex inode instead of preserving recovery data"

# If another writer changes a file after this install wrote it, rollback must
# preserve that writer's version, report incomplete recovery, and retain backups.
concurrent_target="$TMP_DIR/concurrent-target"
init_git_target "$concurrent_target"
mkdir -p "$concurrent_target/.codex" "$concurrent_target/.claude"
concurrent_expected="$TMP_DIR/concurrent-codex-expected.json"
printf '{"hooks":{},"external":"concurrent writer"}\n' > "$concurrent_expected"
concurrent_agents_expected="$TMP_DIR/concurrent-agents-expected.md"
printf '# External concurrent AGENTS update\n' > "$concurrent_agents_expected"
python3 - "$REPO_ROOT/install.sh" "$concurrent_target" "$TMP_DIR/concurrent.log" "$TMP_DIR" "$rollback_python_bin" "$real_python3" "$concurrent_expected" "$concurrent_agents_expected" <<'PY'
import os
import subprocess
import sys
from pathlib import Path

installer, target, output_path, temp_root, mock_bin, real_python, expected, expected_agents = sys.argv[1:]
if os.geteuid() == 0:
    os.chmod(temp_root, 0o755)
    for root in (Path(target), Path(mock_bin)):
        for path in root.rglob("*"):
            os.chown(path, 65534, 65534, follow_symlinks=False)
        os.chown(root, 65534, 65534)

def drop_privileges():
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)

environment = os.environ.copy()
environment["PATH"] = mock_bin + os.pathsep + environment["PATH"]
environment["TEST_CLAUDE_DIR"] = str(Path(target) / ".claude")
environment["TEST_CODEX"] = str(Path(target) / ".codex/hooks.json")
environment["TEST_INJECT_MARKER"] = str(Path(target) / ".test-injected")
environment["TEST_CODEX_EXPECTED"] = expected
environment["TEST_AGENTS"] = str(Path(target) / "AGENTS.md")
environment["TEST_AGENTS_EXPECTED"] = expected_agents
environment["TEST_REAL_PYTHON3"] = real_python
environment["TEST_INJECT_MODE"] = "concurrent"
with Path(output_path).open("wb") as output:
    result = subprocess.run(
        ["bash", installer, "--target", target],
        stdout=output,
        stderr=subprocess.STDOUT,
        env=environment,
        preexec_fn=drop_privileges if os.geteuid() == 0 else None,
    )
if result.returncode == 0:
    raise SystemExit("concurrent Claude write failure unexpectedly succeeded")
PY
chmod 755 "$concurrent_target/.claude"
cmp -s "$concurrent_expected" "$concurrent_target/.codex/hooks.json" \
  || fail "rollback overwrote a concurrent Codex settings update"
cmp -s "$concurrent_agents_expected" "$concurrent_target/AGENTS.md" \
  || fail "rollback deleted a newly installed file after a concurrent edit"
[[ ! -e "$concurrent_target/.claude/settings.json" ]] \
  || fail "concurrent write failure created Claude settings in an unwritable directory"
grep -Fq 'PRESERVED concurrent change; rollback skipped: .codex/hooks.json' "$TMP_DIR/concurrent.log" \
  || fail "rollback did not report preserving the concurrent Codex update"
grep -Fq 'PRESERVED concurrent change; rollback skipped: AGENTS.md' "$TMP_DIR/concurrent.log" \
  || fail "rollback did not report preserving the concurrently edited new file"
grep -Fq 'rollback was incomplete' "$TMP_DIR/concurrent.log" \
  || fail "concurrent update did not make incomplete rollback explicit"
recovery_dir="$(sed -n 's/^ERROR: rollback snapshots retained for recovery at: //p' "$TMP_DIR/concurrent.log" | tail -n 1)"
[[ -n "$recovery_dir" && -f "$recovery_dir/transaction.json" ]] \
  || fail "incomplete rollback did not retain its recovery journal"

# Replace a validated parent with a symlink exactly as the first nested write is
# about to run. The descriptor-relative writer must refuse it and roll back.
racy_symlink_target="$TMP_DIR/racy-symlink-target"
racy_symlink_outside="$TMP_DIR/racy-symlink-outside"
racy_python_bin="$TMP_DIR/racy-python-bin"
mkdir -p "$racy_symlink_target/docs" "$racy_symlink_outside/automation" "$racy_python_bin"
cat > "$racy_python_bin/python3" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [[ -e "$TEST_TARGET/AGENTS.md" && -d "$TEST_TARGET/docs" \
    && ! -e "$TEST_MARKER" && ! -L "$TEST_TARGET/docs" ]]; then
  touch "$TEST_MARKER"
  mv "$TEST_TARGET/docs" "$TEST_TARGET/docs.before-race"
  ln -s "$TEST_OUTSIDE" "$TEST_TARGET/docs"
fi
exec "$TEST_REAL_PYTHON3" "$@"
SH
chmod +x "$racy_python_bin/python3"
if PATH="$racy_python_bin:$PATH" TEST_TARGET="$racy_symlink_target" \
    TEST_OUTSIDE="$racy_symlink_outside" TEST_REAL_PYTHON3="$real_python3" \
    TEST_MARKER="$racy_symlink_target/.test-injected" \
    bash "$REPO_ROOT/install.sh" --target "$racy_symlink_target" --no-hooks \
    > "$TMP_DIR/racy-symlink.log" 2>&1; then
  fail "installer accepted a parent replaced by a symlink after preflight"
fi
[[ ! -e "$racy_symlink_outside/automation/runner-contract.md" ]] \
  || fail "post-preflight symlink replacement wrote outside the target"
[[ ! -e "$racy_symlink_target/AGENTS.md" ]] \
  || fail "post-preflight symlink refusal did not roll back earlier template writes"
grep -Fq 'installation write failed; attempting to roll back' "$TMP_DIR/racy-symlink.log" \
  || fail "post-preflight symlink refusal did not run transactional rollback"

# Existing destination parents must be real directories, not symlinks outside the project.
symlink_parent_target="$TMP_DIR/symlink-parent-target"
symlink_parent_outside="$TMP_DIR/symlink-parent-outside"
init_git_target "$symlink_parent_target"
mkdir -p "$symlink_parent_outside"
ln -s "$symlink_parent_outside" "$symlink_parent_target/docs"
if bash "$REPO_ROOT/install.sh" --target "$symlink_parent_target" --no-hooks > "$TMP_DIR/symlink-parent.log" 2>&1; then
  fail "installer accepted a symlinked destination parent"
fi
[[ ! -e "$symlink_parent_outside/project-profile.md" ]] || fail "installer wrote documentation through a symlink outside the target"
[[ ! -e "$symlink_parent_target/AGENTS.md" ]] || fail "symlink-parent rejection occurred after earlier template writes"
grep -Fq 'symbolic-link directory' "$TMP_DIR/symlink-parent.log" \
  || fail "symlink-parent rejection was not clear"

# Hook settings parents are checked too; a symlinked .claude directory must not
# redirect settings writes outside the target repository.
symlink_claude_target="$TMP_DIR/symlink-claude-target"
symlink_claude_outside="$TMP_DIR/symlink-claude-outside"
init_git_target "$symlink_claude_target"
mkdir -p "$symlink_claude_outside"
ln -s "$symlink_claude_outside" "$symlink_claude_target/.claude"
if bash "$REPO_ROOT/install.sh" --target "$symlink_claude_target" > "$TMP_DIR/symlink-claude.log" 2>&1; then
  fail "installer accepted a symlinked .claude directory"
fi
[[ ! -e "$symlink_claude_outside/settings.json" ]] || fail "installer wrote Claude settings through a symlink"
[[ ! -e "$symlink_claude_target/AGENTS.md" ]] || fail "symlinked .claude rejection occurred after template writes"

# A provider settings symlink is refused rather than replacing the link or touching its target.
settings_link_target="$TMP_DIR/settings-link-target"
settings_link_outside="$TMP_DIR/settings-link-outside.json"
init_git_target "$settings_link_target"
mkdir -p "$settings_link_target/.claude"
printf '{"hooks":{}}\n' > "$settings_link_outside"
cp "$settings_link_outside" "$TMP_DIR/settings-link-outside-before.json"
ln -s "$settings_link_outside" "$settings_link_target/.claude/settings.json"
if bash "$REPO_ROOT/install.sh" --target "$settings_link_target" > "$TMP_DIR/settings-link.log" 2>&1; then
  fail "installer accepted a symlinked Claude settings file"
fi
[[ -L "$settings_link_target/.claude/settings.json" ]] || fail "installer replaced the Claude settings symlink"
cmp -s "$TMP_DIR/settings-link-outside-before.json" "$settings_link_outside" \
  || fail "installer changed the symlink target"
[[ ! -e "$settings_link_target/AGENTS.md" ]] || fail "settings symlink rejection occurred after template writes"
grep -Fq 'settings file is a symbolic link' "$TMP_DIR/settings-link.log" \
  || fail "settings symlink rejection was not clear"

# Existing hook JSON that would need modification is refused before project writes;
# its content, ownership, mode, timestamps and xattrs must remain intact.
hook_metadata_target="$TMP_DIR/hook-metadata-target"
init_git_target "$hook_metadata_target"
mkdir -p "$hook_metadata_target/.claude"
printf '{"hooks":{}}\n' > "$hook_metadata_target/.claude/settings.json"
cp "$hook_metadata_target/.claude/settings.json" "$TMP_DIR/hook-settings-original.json"
python3 - "$hook_metadata_target/.claude/settings.json" "$TMP_DIR/hook-metadata-expected.json" <<'PY'
import errno
import json
import os
import stat
import struct
import sys
from pathlib import Path

filename, expected_path = map(Path, sys.argv[1:])
os.chmod(filename, 0o640)
if os.geteuid() == 0:
    os.chown(filename, 65534, 65534)
xattr_supported = False
try:
    os.setxattr(filename, "user.self_evolution_hook_test", b"preserve-me")
    xattr_supported = True
except OSError as exc:
    if exc.errno not in {errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS}:
        raise
named_user = 12345 if os.stat(filename).st_uid != 12345 else 12346
acl = (
    struct.pack("<I", 2)
    + struct.pack("<HHI", 0x01, 0x06, 0xFFFFFFFF)
    + struct.pack("<HHI", 0x02, 0x04, named_user)
    + struct.pack("<HHI", 0x04, 0x04, 0xFFFFFFFF)
    + struct.pack("<HHI", 0x10, 0x04, 0xFFFFFFFF)
    + struct.pack("<HHI", 0x20, 0x00, 0xFFFFFFFF)
)
try:
    os.setxattr(filename, "system.posix_acl_access", acl)
except OSError as exc:
    if exc.errno not in {errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS}:
        raise
initial = os.stat(filename)
os.utime(filename, ns=(max(0, initial.st_mtime_ns - 172800 * 1_000_000_000), initial.st_mtime_ns))
info = os.stat(filename)
attrs = {name: os.getxattr(filename, name) for name in os.listxattr(filename)}
expected_path.write_text(json.dumps({
    "uid": info.st_uid,
    "gid": info.st_gid,
    "mode": stat.S_IMODE(info.st_mode),
    "atime_ns": info.st_atime_ns,
    "mtime_ns": info.st_mtime_ns,
    "attrs": {name: value.hex() for name, value in attrs.items()},
    "xattr_supported": xattr_supported,
}), encoding="utf-8")
PY
if bash "$REPO_ROOT/install.sh" --target "$hook_metadata_target" > "$TMP_DIR/hook-metadata.log" 2>&1; then
  fail "installer replaced pre-existing hook settings without conditional update support"
fi
[[ ! -e "$hook_metadata_target/AGENTS.md" ]] \
  || fail "unsafe existing hook settings were detected after template writes"
grep -Fq 'cannot safely merge into pre-existing' "$TMP_DIR/hook-metadata.log" \
  || fail "unsafe existing settings refusal was not reported"
python3 - "$hook_metadata_target/.claude/settings.json" "$TMP_DIR/hook-metadata-expected.json" "$TMP_DIR/hook-settings-original.json" <<'PY'
import json
import os
import stat
import sys
from pathlib import Path

filename, expected_path, original_path = map(Path, sys.argv[1:])
expected = json.loads(expected_path.read_text(encoding="utf-8"))
info = os.stat(filename)
fd = os.open(filename, os.O_RDONLY | getattr(os, "O_NOATIME", 0))
try:
    actual_bytes = os.read(fd, 1024 * 1024)
finally:
    os.close(fd)
assert actual_bytes == original_path.read_bytes(), "safe refusal changed existing settings bytes"
assert (info.st_uid, info.st_gid) == (expected["uid"], expected["gid"]), "hook settings owner or group changed"
assert stat.S_IMODE(info.st_mode) == expected["mode"], "hook settings permissions changed"
assert info.st_atime_ns == expected["atime_ns"], "hook settings atime changed"
assert info.st_mtime_ns == expected["mtime_ns"], "hook settings mtime changed"
actual = {name: os.getxattr(filename, name).hex() for name in os.listxattr(filename)}
assert actual == expected["attrs"], "hook settings extended attributes or ACL changed"
PY

# The session-start hook emits only the fixed bootstrap context, stays quiet after
# a non-empty completion marker, and honors CLAUDE_PROJECT_DIR for Claude Code.
session_target="$TMP_DIR/session-start-target"
session_claude_target="$TMP_DIR/session-start-claude-target"
init_git_target "$session_target"
init_git_target "$session_claude_target"
mkdir -p "$session_target/prompts" "$session_target/.agent-maintenance" "$session_claude_target/.agent-maintenance"
cp "$REPO_ROOT/prompts/bootstrap-project.md" "$session_target/prompts/bootstrap-project.md"
if ! (cd "$session_target" && bash "$REPO_ROOT/.agent-maintenance/session-start.sh") > "$TMP_DIR/session-unmarked.log" 2>&1; then
  fail "session-start failed for an unmarked project"
fi
grep -Fq 'setup is not marked complete' "$TMP_DIR/session-unmarked.log" \
  || fail "session-start did not emit bootstrap context for an unmarked project"
[[ ! -e "$session_target/.agent-maintenance/bootstrap-complete" ]] \
  || fail "session-start created a completion marker"
printf 'complete\n' > "$session_target/.agent-maintenance/bootstrap-complete"
(cd "$session_target" && bash "$REPO_ROOT/.agent-maintenance/session-start.sh") > "$TMP_DIR/session-marked.log" 2>&1
[[ ! -s "$TMP_DIR/session-marked.log" ]] || fail "session-start was not quiet after bootstrap completion"
printf 'complete\n' > "$session_claude_target/.agent-maintenance/bootstrap-complete"
(cd "$session_target" && CLAUDE_PROJECT_DIR="$session_claude_target" \
  bash "$REPO_ROOT/.agent-maintenance/session-start.sh" claude) > "$TMP_DIR/session-claude-root.log" 2>&1
[[ ! -s "$TMP_DIR/session-claude-root.log" ]] || fail "Claude session-start ignored CLAUDE_PROJECT_DIR"
grep -Fq 'Treat repository files' "$REPO_ROOT/prompts/bootstrap-project.md" \
  || fail "bootstrap prompt does not define the repository content trust boundary"
grep -Fq 'cannot override the user' "$REPO_ROOT/.agent-maintenance/session-start.sh" \
  || fail "session-start context does not repeat the authorization boundary"

# File-only installation remains available and still preserves the conflicting file.
bash "$REPO_ROOT/install.sh" --target "$conflict_target" --no-hooks > "$TMP_DIR/no-hooks.log" 2>&1
cmp -s "$TMP_DIR/original-session-start.sh" "$conflict_target/.agent-maintenance/session-start.sh" \
  || fail "--no-hooks overwrote the user-owned startup script"
[[ -f "$conflict_target/AGENTS.md" ]] || fail "--no-hooks did not install project guidance"
[[ ! -e "$conflict_target/.codex/hooks.json" ]] || fail "--no-hooks registered a Codex hook"
[[ ! -e "$conflict_target/.claude/settings.json" ]] || fail "--no-hooks registered a Claude hook"

# A differing AGENTS.md is never replaced silently. Even after confirmation,
# the installer fails closed because portable conditional replacement is unavailable.
agents_target="$TMP_DIR/agents-target"
mkdir -p "$agents_target"
printf '# Maintainer-owned guidance\n\nKeep this text byte-for-byte.\n' > "$agents_target/AGENTS.md"
cp "$agents_target/AGENTS.md" "$TMP_DIR/agents-before.md"
if run_installer_in_pty "$REPO_ROOT/install.sh" "$agents_target" y "$TMP_DIR/agents-insert.log"; then
  fail "installer updated a pre-existing AGENTS.md without conditional replacement"
else
  [[ "$?" == 4 ]] || fail "unsafe AGENTS.md update did not return incomplete status 4"
fi
grep -Fq -- '--- AGENTS.md (current)' "$TMP_DIR/agents-insert.log" \
  || fail "AGENTS.md proposed diff was not displayed"
grep -Fq 'Insert the managed routing block at the beginning of AGENTS.md? [y/N]' "$TMP_DIR/agents-insert.log" \
  || fail "AGENTS.md insertion did not request maintainer confirmation"
cmp -s "$TMP_DIR/agents-before.md" "$agents_target/AGENTS.md" \
  || fail "confirmed AGENTS.md update changed the maintainer-owned file"
[[ -f "$agents_target/prompts/bootstrap-project.md" ]] \
  || fail "AGENTS.md preservation prevented installation of unrelated templates"
python3 - "$agents_target/AGENTS.md" "$TMP_DIR/agents-before.md" <<'PY'
import sys
from pathlib import Path

installed, original = map(Path, sys.argv[1:])
assert installed.read_bytes() == original.read_bytes(), "AGENTS.md bytes changed"
PY

# A confirmed update of a pre-existing managed block must fail closed; its
# owner, mode, and extended attributes (including ACLs) remain untouched.
metadata_target="$TMP_DIR/agents-metadata-target"
mkdir -p "$metadata_target"
printf '# Preserve file metadata\n' > "$metadata_target/AGENTS.md"
python3 - "$metadata_target/AGENTS.md" "$TMP_DIR/metadata-expected.json" <<'PY'
import errno
import json
import os
import stat
import struct
import sys
from pathlib import Path

filename, expected_path = map(Path, sys.argv[1:])
os.chmod(filename, 0o640)
if os.geteuid() == 0:
    os.chown(filename, 65534, 65534)
xattr_supported = False
try:
    os.setxattr(filename, "user.self_evolution_test", b"preserve-me")
    xattr_supported = True
except OSError as exc:
    if exc.errno not in {errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS}:
        raise
named_user = 12345 if os.stat(filename).st_uid != 12345 else 12346
acl = (
    struct.pack("<I", 2)
    + struct.pack("<HHI", 0x01, 0x06, 0xFFFFFFFF)
    + struct.pack("<HHI", 0x02, 0x04, named_user)
    + struct.pack("<HHI", 0x04, 0x04, 0xFFFFFFFF)
    + struct.pack("<HHI", 0x10, 0x04, 0xFFFFFFFF)
    + struct.pack("<HHI", 0x20, 0x00, 0xFFFFFFFF)
)
acl_supported = False
try:
    os.setxattr(filename, "system.posix_acl_access", acl)
    acl_supported = True
except OSError as exc:
    if exc.errno not in {errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS}:
        raise
result = os.stat(filename)
expected_path.write_text(
    json.dumps({
        "uid": result.st_uid,
        "gid": result.st_gid,
        "mode": stat.S_IMODE(result.st_mode),
        "xattr_supported": xattr_supported,
        "acl_supported": acl_supported,
        "acl_hex": acl.hex(),
    }),
    encoding="utf-8",
)
PY
if run_installer_in_pty "$REPO_ROOT/install.sh" "$metadata_target" y "$TMP_DIR/agents-metadata.log"; then
  fail "installer updated pre-existing AGENTS.md without conditional replacement"
fi
python3 - "$metadata_target/AGENTS.md" "$TMP_DIR/metadata-expected.json" <<'PY'
import json
import os
import stat
import sys
from pathlib import Path

filename, expected_path = map(Path, sys.argv[1:])
expected = json.loads(expected_path.read_text(encoding="utf-8"))
actual = os.stat(filename)
fd = os.open(filename, os.O_RDONLY | getattr(os, "O_NOATIME", 0))
try:
    original_bytes = os.read(fd, 1024 * 1024)
finally:
    os.close(fd)
assert original_bytes == b"# Preserve file metadata\n", "safe refusal changed AGENTS.md bytes"
assert (actual.st_uid, actual.st_gid) == (expected["uid"], expected["gid"]), "AGENTS.md owner or group changed"
assert stat.S_IMODE(actual.st_mode) == expected["mode"], "AGENTS.md permissions changed"
if expected["xattr_supported"]:
    assert os.getxattr(filename, "user.self_evolution_test") == b"preserve-me", "AGENTS.md extended attribute was lost"
if expected["acl_supported"]:
    assert os.getxattr(filename, "system.posix_acl_access") == bytes.fromhex(expected["acl_hex"]), "AGENTS.md ACL was lost or changed"
PY

# Atomic replacement cannot retain a file's hard-link relationship, so decline it.
agents_hardlink_target="$TMP_DIR/agents-hardlink-target"
mkdir -p "$agents_hardlink_target"
printf '# Shared inode must remain intact\n' > "$agents_hardlink_target/AGENTS.md"
ln "$agents_hardlink_target/AGENTS.md" "$agents_hardlink_target/AGENTS.md.shared"
cp "$agents_hardlink_target/AGENTS.md" "$TMP_DIR/agents-hardlink-before.md"
if run_installer_in_pty "$REPO_ROOT/install.sh" "$agents_hardlink_target" y "$TMP_DIR/agents-hardlink.log"; then
  fail "hard-linked AGENTS.md update did not report the incomplete safe refusal"
else
  [[ "$?" == 4 ]] || fail "hard-linked AGENTS.md refusal returned an unexpected status"
fi
cmp -s "$TMP_DIR/agents-hardlink-before.md" "$agents_hardlink_target/AGENTS.md" \
  || fail "hard-linked AGENTS.md was replaced"
python3 - "$agents_hardlink_target/AGENTS.md" "$agents_hardlink_target/AGENTS.md.shared" <<'PY'
import os
import sys

assert os.path.samefile(*sys.argv[1:]), "AGENTS.md hard-link relationship was broken"
PY
grep -Fq 'PRESERVED existing file (managed routing not applied): AGENTS.md' "$TMP_DIR/agents-hardlink.log" \
  || fail "hard-linked AGENTS.md refusal was not reported"

# Untrusted control sequences in existing AGENTS.md content must be rendered
# visibly, never emitted as terminal control bytes in the proposed diff.
agents_control_target="$TMP_DIR/agents-control-target"
mkdir -p "$agents_control_target"
python3 - "$agents_control_target/AGENTS.md" <<'PY'
import sys
from pathlib import Path

Path(sys.argv[1]).write_bytes(
    b"# Terminal content\n"
    b"unsafe: \x1b[2J CSI \x1b]0;title-test\x07 C1: \xc2\x9b\n"
)
PY
run_installer_in_pty "$REPO_ROOT/install.sh" "$agents_control_target" n "$TMP_DIR/agents-control.log" \
  || fail "declining a control-character AGENTS.md update failed unexpectedly"
python3 - "$TMP_DIR/agents-control.log" <<'PY'
import sys
from pathlib import Path

output = Path(sys.argv[1]).read_bytes()
for control in (b"\x1b", b"\x07", b"\xc2\x9b"):
    assert control not in output, f"raw terminal control byte was emitted: {control!r}"
for visible in (b"\\x1b[2J", b"\\x1b]0;title-test", b"\\x07", b"\\x9b"):
    assert visible in output, f"escaped control was not visible in diff: {visible!r}"
PY

# Without a controlling terminal the managed change is not applied, and the
# installer must return a detectable incomplete status without claiming success.
agents_no_tty_target="$TMP_DIR/agents-no-tty-target"
mkdir -p "$agents_no_tty_target"
printf '# Keep without a TTY\n' > "$agents_no_tty_target/AGENTS.md"
cp "$agents_no_tty_target/AGENTS.md" "$TMP_DIR/agents-no-tty-before.md"
python3 - "$REPO_ROOT/install.sh" "$agents_no_tty_target" "$TMP_DIR/agents-no-tty.log" <<'PY'
import subprocess
import sys
from pathlib import Path

installer, target, output_path = sys.argv[1:]
with Path(output_path).open("wb") as output:
    result = subprocess.run(
        ["bash", installer, "--target", target, "--no-hooks"],
        stdin=subprocess.DEVNULL,
        stdout=output,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
if result.returncode != 4:
    raise SystemExit(f"expected exit status 4 without a controlling terminal, got {result.returncode}")
PY
cmp -s "$TMP_DIR/agents-no-tty-before.md" "$agents_no_tty_target/AGENTS.md" \
  || fail "no-TTY confirmation path changed AGENTS.md"
grep -Fq 'explicit confirmation requires a controlling terminal' "$TMP_DIR/agents-no-tty.log" \
  || fail "no-TTY confirmation requirement was not reported"
grep -Fq 'installation incomplete:' "$TMP_DIR/agents-no-tty.log" \
  || fail "no-TTY installation did not report its incomplete state"
if grep -Fq 'Installation complete for:' "$TMP_DIR/agents-no-tty.log"; then
  fail "no-TTY installation falsely claimed completion"
fi

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

# A byte-identical AGENTS.md is left alone without a prompt; differing content
# requires manual merge because a conditional atomic replacement is unavailable.
agents_identical_target="$TMP_DIR/agents-identical-target"
mkdir -p "$agents_identical_target"
cp "$REPO_ROOT/AGENTS.md" "$agents_identical_target/AGENTS.md"
bash "$REPO_ROOT/install.sh" --target "$agents_identical_target" --no-hooks > "$TMP_DIR/agents-identical.log" 2>&1
grep -Fq 'UNCHANGED AGENTS.md' "$TMP_DIR/agents-identical.log" \
  || fail "byte-identical AGENTS.md was not recognized as unchanged"
if grep -Fq '[y/N]' "$TMP_DIR/agents-identical.log"; then
  fail "byte-identical AGENTS.md unexpectedly requested confirmation"
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
cat > "$agents_target/AGENTS.md" <<'AGENTS'
<!-- BEGIN SELF-EVOLUTION-FLYWHEEL MANAGED ROUTING -->
- Follow repository evidence, documented validation, and permission boundaries; keep changes focused.
<!-- END SELF-EVOLUTION-FLYWHEEL MANAGED ROUTING -->

# Maintainer-owned guidance
AGENTS
cp "$agents_target/AGENTS.md" "$TMP_DIR/agents-update-before.md"
if run_installer_in_pty "$updated_source/install.sh" "$agents_target" y "$TMP_DIR/agents-update.log"; then
  fail "installer updated a pre-existing managed block without conditional replacement"
else
  [[ "$?" == 4 ]] || fail "unsafe managed-block update did not return incomplete status 4"
fi
grep -Fq 'Update the existing managed routing block in AGENTS.md? [y/N]' "$TMP_DIR/agents-update.log" \
  || fail "changed managed block did not request confirmation"
cmp -s "$TMP_DIR/agents-update-before.md" "$agents_target/AGENTS.md" \
  || fail "confirmed managed-block update changed AGENTS.md"

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

# A missing bootstrap prompt is diagnosed in stdout for the SessionStart model
# context, without emitting the normal bootstrap instructions or failing the hook.
missing_prompt_target="$TMP_DIR/missing-prompt-target"
init_git_target "$missing_prompt_target"
mkdir -p "$missing_prompt_target/.agent-maintenance"
cp "$REPO_ROOT/.agent-maintenance/session-start.sh" \
  "$missing_prompt_target/.agent-maintenance/session-start.sh"
[[ ! -e "$missing_prompt_target/.agent-maintenance/bootstrap-complete" ]] \
  || fail "missing-prompt fixture unexpectedly has a completion marker"
[[ ! -e "$missing_prompt_target/prompts/bootstrap-project.md" ]] \
  || fail "missing-prompt fixture unexpectedly has the bootstrap prompt"
missing_prompt_status=0
(
  cd "$missing_prompt_target"
  bash .agent-maintenance/session-start.sh codex \
    > "$TMP_DIR/missing-prompt.stdout" 2> "$TMP_DIR/missing-prompt.stderr"
) || missing_prompt_status=$?
[[ "$missing_prompt_status" -eq 0 ]] \
  || fail "missing-prompt SessionStart hook exited with status $missing_prompt_status"
python3 - "$TMP_DIR/missing-prompt.stdout" "$TMP_DIR/missing-prompt.stderr" <<'PY'
import sys
from pathlib import Path

stdout, stderr = (Path(path).read_bytes() for path in sys.argv[1:])
expected = b"Self-Evolution Flywheel: prompts/bootstrap-project.md is missing; cannot bootstrap.\n"
assert stdout == expected, f"unexpected missing-prompt stdout: {stdout!r}"
assert stderr == b"", f"missing-prompt diagnostic was written to stderr: {stderr!r}"
PY

# A script streamed through stdin has no BASH_SOURCE path. Simulate git clone
# returning one complete checkout and verify the pipe shim delegates to its installer.
mock_bin="$TMP_DIR/mock-bin"
mkdir -p "$mock_bin"
cat > "$mock_bin/git" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "clone" ]]; then
  destination="${@: -1}"
  mkdir -p "$destination"
  cp -R "$SELF_EVOLUTION_TEST_SOURCE_DIR"/. "$destination"/
  exit 0
fi
exec /usr/bin/git "$@"
SH
chmod +x "$mock_bin/git"
remote_target="$TMP_DIR/remote-target"
mkdir -p "$remote_target"
(
  cd "$remote_target"
  PATH="$mock_bin:$PATH" SELF_EVOLUTION_TEST_SOURCE_DIR="$REPO_ROOT" \
    bash -c 'cat "$1" | bash -s -- --no-hooks' _ "$REPO_ROOT/install.sh"
) > "$TMP_DIR/remote.log" 2>&1
grep -Fq "Installation complete for: $remote_target" "$TMP_DIR/remote.log" \
  || fail "pipe installer did not complete in the current target directory"
grep -Fq 'Cloning Self-Evolution Flywheel source' "$TMP_DIR/remote.log" \
  || fail "pipe installer did not clone the source checkout"
[[ -f "$remote_target/prompts/bootstrap-project.md" ]] \
  || fail "pipe installer did not install the bootstrap prompt"

python3 "$REPO_ROOT/tests/test-installer-races.py"
python3 "$REPO_ROOT/tests/test-installer-recovery.py"
python3 "$REPO_ROOT/tests/test-installer-security.py"

echo "PASS: installer safety, hook and session-start regression tests"

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

# Hook JSON replacement preserves existing ownership, mode, timestamps and xattrs.
hook_metadata_target="$TMP_DIR/hook-metadata-target"
init_git_target "$hook_metadata_target"
mkdir -p "$hook_metadata_target/.claude"
printf '{"hooks":{}}\n' > "$hook_metadata_target/.claude/settings.json"
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
bash "$REPO_ROOT/install.sh" --target "$hook_metadata_target" > "$TMP_DIR/hook-metadata.log" 2>&1 \
  || fail "hook merge failed while preserving metadata"
python3 - "$hook_metadata_target/.claude/settings.json" "$TMP_DIR/hook-metadata-expected.json" <<'PY'
import json
import os
import stat
import sys
from pathlib import Path

filename, expected_path = map(Path, sys.argv[1:])
expected = json.loads(expected_path.read_text(encoding="utf-8"))
info = os.stat(filename)
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

# Updating a managed block must preserve the existing file owner, mode, and
# extended attributes (including ACLs where the platform exposes them).
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
run_installer_in_pty "$REPO_ROOT/install.sh" "$metadata_target" y "$TMP_DIR/agents-metadata.log" \
  || fail "confirming a managed AGENTS.md metadata update failed"
python3 - "$metadata_target/AGENTS.md" "$TMP_DIR/metadata-expected.json" <<'PY'
import json
import os
import stat
import sys
from pathlib import Path

filename, expected_path = map(Path, sys.argv[1:])
expected = json.loads(expected_path.read_text(encoding="utf-8"))
actual = os.stat(filename)
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
run_installer_in_pty "$REPO_ROOT/install.sh" "$agents_hardlink_target" y "$TMP_DIR/agents-hardlink.log" \
  || fail "hard-linked AGENTS.md refusal unexpectedly failed the installer"
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

echo "PASS: installer safety, hook and session-start regression tests"

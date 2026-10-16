#!/usr/bin/env python3
"""SIGKILL recovery tests for provider-settings staging hard links."""
from __future__ import annotations

import json
import os
import pathlib
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "install.sh"
HELPER = REPO_ROOT / ".agent-maintenance/installer-transaction.py"
CODEX_COMMAND = 'bash "$(git rev-parse --show-toplevel)/.agent-maintenance/session-start.sh" codex'
CLAUDE_COMMAND = 'bash "${CLAUDE_PROJECT_DIR}/.agent-maintenance/session-start.sh" claude'
TEMP_RE = re.compile(r"^\.hooks\.json\.flywheel-[0-9]+-[0-9a-f]{12}$")


def read_noatime(path: pathlib.Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOATIME", 0)
    fd = os.open(path, flags)
    try:
        chunks = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(fd)


def expected_claude_settings() -> dict:
    return {
        "userOwned": {"label": "keep byte-for-byte", "nested": [1, "two"]},
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup|resume|clear|compact|fork",
                    "hooks": [
                        {"type": "command", "command": CLAUDE_COMMAND},
                        {"type": "command", "command": "user-owned-extra-hook"},
                    ],
                }
            ]
        },
    }


def make_fixture(
    base: pathlib.Path, label: str, with_claude_settings: bool = True
) -> tuple[pathlib.Path, pathlib.Path | None, dict | None]:
    target = base / label
    target.mkdir()
    subprocess.run(["git", "init", "--quiet", str(target)], check=True)
    if not with_claude_settings:
        return target, None, None
    claude_dir = target / ".claude"
    claude_dir.mkdir()
    claude_path = claude_dir / "settings.json"
    expected = expected_claude_settings()
    claude_path.write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(claude_path, 0o640)
    xattr_name = "user.self_evolution_recovery_test"
    xattr_supported = False
    try:
        os.setxattr(claude_path, xattr_name, b"preserve-user-metadata")
        xattr_supported = True
    except OSError as exc:
        if exc.errno not in {1, 13, 22, 95, 45, 61}:
            raise
    original_mtime_ns = 1_700_000_000_123_456_789
    os.utime(claude_path, ns=(original_mtime_ns, original_mtime_ns))
    info = os.stat(claude_path)
    metadata = {
        "bytes": read_noatime(claude_path),
        "uid": info.st_uid,
        "gid": info.st_gid,
        "mode": stat.S_IMODE(info.st_mode),
        "atime_ns": info.st_atime_ns,
        "mtime_ns": info.st_mtime_ns,
        "xattr_supported": xattr_supported,
        "xattr_name": xattr_name,
    }
    if xattr_supported:
        metadata["xattr_value"] = os.getxattr(claude_path, xattr_name)
    return target, claude_path, metadata


def installer_env(tmp_root: pathlib.Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    temp_dir = tmp_root / "installer-tmp"
    temp_dir.mkdir(exist_ok=True)
    env = os.environ.copy()
    env["TMPDIR"] = str(temp_dir)
    env.pop("PYTHONPATH", None)
    if extra:
        env.update(extra)
    return env


def install(target: pathlib.Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(INSTALLER), "--target", str(target)],
        cwd=target,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=90,
    )


def crash_after_codex_publish(
    base: pathlib.Path,
    tmp_root: pathlib.Path,
    label: str,
    with_claude_settings: bool = True,
):
    target, claude_path, metadata = make_fixture(base, label, with_claude_settings)
    hook_dir = tmp_root / f"{label}-python-hook"
    hook_dir.mkdir()
    marker = tmp_root / f"{label}-kill-marker"
    sitecustomize = r'''import os
import re
import signal

_real_unlink = os.unlink
_root = os.environ.get("SELF_EVOLUTION_RECOVERY_TEST_ROOT")
_marker = os.environ.get("SELF_EVOLUTION_RECOVERY_TEST_MARKER")
_pattern = re.compile(r"^\.hooks\.json\.flywheel-[0-9]+-[0-9a-f]{12}$")

def _kill_before_unlink(path, *args, **kwargs):
    try:
        parent_fd = kwargs.get("dir_fd")
        if (
            _root
            and _marker
            and parent_fd is not None
            and isinstance(path, str)
            and _pattern.fullmatch(path)
        ):
            active = os.path.join(_root, ".codex", "hooks.json")
            staged = os.stat(path, dir_fd=parent_fd, follow_symlinks=False)
            current = os.stat(active, follow_symlinks=False)
            if (
                os.path.basename(path).startswith(".hooks.json.flywheel-")
                and os.path.samefile(f"/proc/self/fd/{parent_fd}", os.path.dirname(active))
                and (staged.st_dev, staged.st_ino) == (current.st_dev, current.st_ino)
                and staged.st_nlink == 2
            ):
                with open(_marker, "w", encoding="utf-8") as handle:
                    handle.write(path + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.killpg(os.getpgrp(), signal.SIGKILL)
    except FileNotFoundError:
        pass
    return _real_unlink(path, *args, **kwargs)

os.unlink = _kill_before_unlink
'''
    (hook_dir / "sitecustomize.py").write_text(sitecustomize, encoding="utf-8")
    env = installer_env(
        tmp_root,
        {
            "PYTHONPATH": str(hook_dir),
            "SELF_EVOLUTION_RECOVERY_TEST_ROOT": str(target),
            "SELF_EVOLUTION_RECOVERY_TEST_MARKER": str(marker),
        },
    )
    log = tmp_root / f"{label}-interrupted.log"
    with log.open("wb") as output:
        process = subprocess.Popen(
            ["bash", str(INSTALLER), "--target", str(target)],
            cwd=target,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            returncode = process.wait(timeout=90)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise AssertionError("SIGKILL injection did not reach the provider publish/unlink boundary")
    assert returncode == -signal.SIGKILL, f"expected SIGKILL interruption, got {returncode}; log: {log.read_text(errors='replace')}"
    assert marker.is_file(), "injection marker was not written at the Provider A post-publish/pre-unlink boundary"
    marker_name = marker.read_text(encoding="utf-8").strip()
    assert TEMP_RE.fullmatch(marker_name), f"unexpected staged alias name: {marker_name!r}"
    alias = target / ".codex" / marker_name
    active = target / ".codex" / "hooks.json"
    assert alias.is_file() and active.is_file(), "SIGKILL did not leave the expected active settings and staged alias"
    assert os.path.samefile(alias, active), "injected alias is not a hard link to the active provider config"
    assert os.stat(active).st_nlink == 2, "injected link count was not exactly the expected two links"
    return target, claude_path, metadata, alias, active


def assert_user_metadata_unchanged(path: pathlib.Path, expected: dict) -> None:
    info = os.stat(path)
    assert read_noatime(path) == expected["bytes"], "existing Claude JSON bytes were changed"
    assert (info.st_uid, info.st_gid) == (expected["uid"], expected["gid"]), "existing settings owner/group changed"
    assert stat.S_IMODE(info.st_mode) == expected["mode"], "existing settings mode changed"
    assert info.st_atime_ns == expected["atime_ns"], "existing settings atime changed"
    assert info.st_mtime_ns == expected["mtime_ns"], "existing settings mtime changed"
    if expected["xattr_supported"]:
        assert os.getxattr(path, expected["xattr_name"]) == expected["xattr_value"], "existing settings xattr changed"


def assert_install_complete(
    target: pathlib.Path,
    claude_path: pathlib.Path | None,
    metadata: dict | None,
    alias: pathlib.Path,
) -> None:
    assert not alias.exists(), "recognized stale provider staging hard link was not cleaned"
    codex_path = target / ".codex" / "hooks.json"
    assert codex_path.is_file() and os.stat(codex_path).st_nlink == 1, "Codex active settings did not return to one link"
    claude_path = claude_path or target / ".claude" / "settings.json"
    if metadata is not None:
        assert_user_metadata_unchanged(claude_path, metadata)
    codex = json.loads(codex_path.read_text(encoding="utf-8"))
    codex_handlers = [handler for session in codex["hooks"]["SessionStart"] for handler in session.get("hooks", [])]
    assert [handler.get("command") for handler in codex_handlers].count(CODEX_COMMAND) == 1, "Codex hook missing or duplicated"
    claude = json.loads(claude_path.read_text(encoding="utf-8"))
    claude_handlers = [handler for session in claude["hooks"]["SessionStart"] for handler in session.get("hooks", [])]
    assert [handler.get("command") for handler in claude_handlers].count(CLAUDE_COMMAND) == 1, "Claude hook missing or duplicated"
    expected_user_hook_count = 1 if metadata is not None else 0
    assert [handler.get("command") for handler in claude_handlers].count("user-owned-extra-hook") == expected_user_hook_count, "user-owned hook changed or duplicated"
    expected_files = [
        "AGENTS.md",
        "CLAUDE.md",
        "LESSONS.md",
        "install.sh",
        ".agent-maintenance/session-start.sh",
        ".agent-maintenance/installer-transaction.py",
        ".github/PULL_REQUEST_TEMPLATE.md",
    ]
    for directory in (REPO_ROOT / "docs", REPO_ROOT / "prompts"):
        expected_files.extend(
            str(path.relative_to(REPO_ROOT))
            for path in directory.rglob("*")
            if path.is_file() and path != REPO_ROOT / "docs/source-and-extraction.md"
        )
    for relative in expected_files:
        assert (target / relative).read_bytes() == (REPO_ROOT / relative).read_bytes(), f"template file missing or differs: {relative}"


def assert_fail_closed(target: pathlib.Path, env: dict[str, str], alias: pathlib.Path, phrase: str) -> None:
    before = alias.lstat()
    result = install(target, env)
    assert result.returncode != 0, f"unsafe provider staging state was accepted:\n{result.stdout}"
    assert phrase.lower() in result.stdout.lower(), f"failure did not explain the unsafe state:\n{result.stdout}"
    assert alias.exists(), "unsafe or unrecognized candidate was deleted"
    after = alias.lstat()
    assert (before.st_dev, before.st_ino, before.st_nlink, before.st_uid, before.st_gid) == (
        after.st_dev, after.st_ino, after.st_nlink, after.st_uid, after.st_gid
    ), "fail-closed check changed the candidate entry or inode metadata"


def test_sigkill_retry_repairs_install(tmp_root: pathlib.Path) -> None:
    target, claude_path, metadata, alias, _ = crash_after_codex_publish(
        tmp_root, tmp_root, "sigkill-recovery"
    )
    result = install(target, installer_env(tmp_root))
    assert result.returncode == 0, (
        "re-running the same install command did not recover the SIGKILL interruption; "
        f"exit={result.returncode}\n{result.stdout}"
    )
    assert_install_complete(target, claude_path, metadata, alias)


def test_sigkill_retry_installs_missing_second_provider(tmp_root: pathlib.Path) -> None:
    target, claude_path, metadata, alias, _ = crash_after_codex_publish(
        tmp_root, tmp_root, "missing-second-provider", with_claude_settings=False
    )
    result = install(target, installer_env(tmp_root))
    assert result.returncode == 0, (
        "re-running after a Provider A SIGKILL did not install the missing Provider B hook; "
        f"exit={result.returncode}\n{result.stdout}"
    )
    assert claude_path is None and metadata is None
    assert_install_complete(target, claude_path, metadata, alias)


def test_extra_hardlink_fails_closed(tmp_root: pathlib.Path) -> None:
    target, _, _, alias, active = crash_after_codex_publish(tmp_root, tmp_root, "extra-hardlink")
    extra = target / ".codex" / "user-owned-extra-link"
    os.link(active, extra)
    assert os.stat(active).st_nlink == 3
    assert_fail_closed(target, installer_env(tmp_root), alias, "link")
    assert os.path.samefile(alias, active) and os.path.samefile(extra, active)
    assert os.stat(active).st_nlink == 3


def test_wrong_inode_fails_closed(tmp_root: pathlib.Path) -> None:
    target, _, _, alias, active = crash_after_codex_publish(tmp_root, tmp_root, "wrong-inode")
    alias.unlink()
    alias.write_text("not the active settings inode\n", encoding="utf-8")
    os.chmod(alias, 0o644)
    if os.geteuid() == 0:
        os.chown(alias, 65534, 65534)
    assert not os.path.samefile(alias, active)
    assert_fail_closed(target, installer_env(tmp_root), alias, "staging")
    assert active.exists() and os.stat(active).st_nlink == 1


def test_wrong_owner_fails_closed(tmp_root: pathlib.Path) -> None:
    if os.geteuid() != 0:
        return
    target, _, _, alias, active = crash_after_codex_publish(tmp_root, tmp_root, "wrong-owner")
    os.chown(active, 65534, 65534)
    assert os.stat(active).st_nlink == 2
    assert os.stat(alias).st_uid == 65534
    assert_fail_closed(target, installer_env(tmp_root), alias, "owner")
    assert os.path.samefile(alias, active) and os.stat(active).st_nlink == 2


def test_unknown_name_fails_closed(tmp_root: pathlib.Path) -> None:
    target, _, _, alias, active = crash_after_codex_publish(tmp_root, tmp_root, "unknown-name")
    unknown = alias.with_name(alias.name + "-unexpected")
    alias.rename(unknown)
    result = install(target, installer_env(tmp_root))
    assert result.returncode != 0, f"unknown alias name was accepted:\n{result.stdout}"
    assert "unrecognized" in result.stdout.lower() or "unknown" in result.stdout.lower(), result.stdout
    assert unknown.exists() and os.path.samefile(unknown, active)
    assert os.stat(active).st_nlink == 2


def test_competing_installer_does_not_recover(tmp_root: pathlib.Path) -> None:
    target, _, _, alias, active = crash_after_codex_publish(tmp_root, tmp_root, "lock-contention")
    ready = tmp_root / "lock-holder-ready"
    holder = subprocess.Popen(
        [
            sys.executable,
            str(HELPER),
            "lock-exec",
            str(target),
            "/bin/sh",
            "-c",
            'printf ready > "$1"; sleep 10',
            "lock-holder",
            str(ready),
        ],
        cwd=target,
        env=installer_env(tmp_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and holder.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), f"lock-holder failed to start: {holder.stdout.read() if holder.poll() is not None else ''}"
        result = install(target, installer_env(tmp_root))
        assert result.returncode != 0, f"a competing installer ran while the target lock was held:\n{result.stdout}"
        assert "another installer" in result.stdout.lower() or "lock" in result.stdout.lower(), result.stdout
        assert alias.exists() and os.path.samefile(alias, active), "competing installer changed the stale alias"
        assert os.stat(active).st_nlink == 2
    finally:
        if holder.poll() is None:
            os.killpg(holder.pid, signal.SIGKILL)
        holder.wait(timeout=10)


def main() -> None:
    if sys.platform != "linux":
        raise SystemExit("SIGKILL syscall-boundary recovery tests currently require Linux /proc and process-group semantics")
    with tempfile.TemporaryDirectory(prefix="self-evolution-installer-recovery-") as tmp_name:
        root = pathlib.Path(tmp_name)
        test_sigkill_retry_repairs_install(root)
        test_sigkill_retry_installs_missing_second_provider(root)
        test_extra_hardlink_fails_closed(root)
        test_wrong_inode_fails_closed(root)
        test_wrong_owner_fails_closed(root)
        test_unknown_name_fails_closed(root)
        test_competing_installer_does_not_recover(root)
    print("PASS: provider staging SIGKILL recovery, strict identity checks, and installer lock contention")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Deterministic syscall-boundary regression tests for installer races.

The old helper is loaded from the original PR head so the same injected
interleavings can demonstrate the old failure and the current invariant.
"""
from __future__ import annotations

import contextlib
import errno
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from unittest import mock

sys.dont_write_bytecode = True

OLD_HEAD = "3141190ca86e824c3366a7f60ab4828aa11aac21"
HELPER_PATH = pathlib.Path(__file__).resolve().parents[1] / ".agent-maintenance/installer-transaction.py"


def load_module(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load helper module {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def save_empty_state(module, path: pathlib.Path):
    module.save_state(str(path), {"operations": [], "created_directories": []})


def test_existing_file_replace_race(old, current, temp: pathlib.Path):
    old_root = temp / "replace-old"
    old_root.mkdir()
    (old_root / ".codex").mkdir()
    destination = old_root / ".codex/hooks.json"
    destination.write_text('{"hooks":{},"owner":"original"}\n', encoding="utf-8")
    external = b'{"hooks":{},"external":"concurrent update"}\n'
    state = temp / "replace-old-state.json"
    save_empty_state(old, state)
    real_replace = os.replace
    injected = False

    def replace_after_check(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
        nonlocal injected
        if not injected:
            fd = os.open(dst, os.O_WRONLY | os.O_TRUNC, dir_fd=dst_dir_fd)
            try:
                os.write(fd, external)
            finally:
                os.close(fd)
            injected = True
        return real_replace(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    with mock.patch.object(old.os, "replace", replace_after_check), contextlib.redirect_stdout(io.StringIO()):
        old.op_merge_hook(str(old_root), "codex", ".codex/hooks.json", str(state))
    assert injected, "legacy comparison did not reach its replace syscall boundary"
    assert destination.read_bytes() != external, "legacy replace race did not overwrite the injected external update"

    # The current helper has no replacement syscall for an existing config: it
    # must refuse before that commit boundary. Replay the same writer payload as
    # an already-visible external state and require byte-for-byte preservation.
    new_root = temp / "replace-new"
    new_root.mkdir()
    (new_root / ".codex").mkdir()
    new_destination = new_root / ".codex/hooks.json"
    new_destination.write_bytes(external)
    new_state = temp / "replace-new-state.json"
    save_empty_state(current, new_state)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            current.op_merge_hook(str(new_root), "codex", ".codex/hooks.json", str(new_state))
        except SystemExit as exc:
            assert exc.code == 11, f"current helper returned unexpected refusal status: {exc.code}"
        else:
            raise AssertionError("current helper replaced an existing settings file")
    assert new_destination.read_bytes() == external, "current helper did not preserve the external settings bytes"


def move_parent_at_link(module, target: pathlib.Path, outside: pathlib.Path):
    real_link = os.link
    injected = False

    def link_after_move(src, dst, *args, **kwargs):
        nonlocal injected
        if not injected:
            os.rename(target / "docs", outside / "moved-docs")
            os.symlink(outside / "moved-docs", target / "docs")
            injected = True
        return real_link(src, dst, *args, **kwargs)

    return mock.patch.object(module.os, "link", link_after_move), lambda: injected


def test_directory_move_race(old, current, temp: pathlib.Path):
    for label, module in (("old", old), ("new", current)):
        area = temp / f"move-{label}"
        target = area / "project"
        outside = area / "outside"
        target.mkdir(parents=True)
        (target / "docs").mkdir()
        outside.mkdir()
        source = area / "source.txt"
        source.write_text("installer payload\n", encoding="utf-8")
        state = area / "state.json"
        save_empty_state(module, state)
        patch, was_injected = move_parent_at_link(module, target, outside)
        if label == "old":
            with patch, contextlib.redirect_stdout(io.StringIO()):
                module.op_copy(str(target), "docs/outline.md", str(source), str(state))
            assert was_injected(), "legacy helper did not reach link publication"
            assert (outside / "moved-docs/outline.md").read_text(encoding="utf-8") == "installer payload\n"
        else:
            publication_warning = io.StringIO()
            with patch, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(publication_warning):
                try:
                    module.op_copy(str(target), "docs/outline.md", str(source), str(state))
                except module.InstallError as exc:
                    assert "moved during publication" in str(exc)
                else:
                    raise AssertionError("current helper did not detect the moved destination directory")
            assert was_injected(), "current helper did not reach the injected publication boundary"
            assert "PRESERVED file written through a directory moved during publication" in publication_warning.getvalue(), (
                "directory migration was not surfaced at publication time"
            )
            error_output = io.StringIO()
            with contextlib.redirect_stderr(error_output):
                result = module.rollback(str(target), str(state))
            assert result == 1, "rollback did not expose its inability to safely traverse the moved parent"
            assert "rollback could not safely process" in error_output.getvalue(), (
                "moved-parent rollback limitation was not reported"
            )
            assert (outside / "moved-docs/outline.md").read_text(encoding="utf-8") == "installer payload\n", (
                "rollback removed uncertain data from the directory moved outside the project"
            )


def test_rollback_open_fd_race(old, current, temp: pathlib.Path):
    for label, module in (("old", old), ("new", current)):
        root = temp / f"rollback-{label}"
        root.mkdir()
        source = temp / f"rollback-source-{label}.txt"
        source.write_text("installer content\n", encoding="utf-8")
        state = temp / f"rollback-state-{label}.json"
        save_empty_state(module, state)
        with contextlib.redirect_stdout(io.StringIO()):
            module.op_copy(str(root), "victim.txt", str(source), str(state))
        victim = root / "victim.txt"
        writer_fd = os.open(victim, os.O_RDWR)
        injected = False

        def write_through_held_fd():
            nonlocal injected
            os.lseek(writer_fd, 0, os.SEEK_END)
            os.write(writer_fd, b"\nexternal write after identity check\n")
            injected = True

        errors = io.StringIO()
        if label == "old":
            real_unlink = os.unlink

            def unlink_after_identity(path, *args, **kwargs):
                if not injected and str(path).startswith(".victim.txt.rollback-"):
                    write_through_held_fd()
                return real_unlink(path, *args, **kwargs)

            patch = mock.patch.object(module.os, "unlink", unlink_after_identity)
        else:
            real_print = print

            def print_after_identity(*args, **kwargs):
                nonlocal injected
                real_print(*args, **kwargs)
                if not injected and args and str(args[0]).startswith("PRESERVED rollback recovery file"):
                    write_through_held_fd()

            patch = mock.patch.dict(module.__dict__, {"print": print_after_identity})
        with patch, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
            result = module.rollback(str(root), str(state))
        assert injected, f"{label} rollback injection did not write after identity re-check"
        quarantine_files = list(root.glob(".victim.txt.rollback-*"))
        if label == "old":
            assert result == 0, "legacy rollback did not report its unsafe successful deletion"
            assert not victim.exists() and not quarantine_files, "legacy rollback unexpectedly retained the unlinked inode"
            os.close(writer_fd)
            assert not list(root.iterdir()), "legacy rollback left a pathname for the external FD write"
        else:
            assert result == 1, "current rollback did not report its preserved recovery entry"
            assert not victim.exists() and len(quarantine_files) == 1, "current rollback did not retain one quarantine path"
            os.close(writer_fd)
            recovered = quarantine_files[0].read_bytes()
            assert b"external write after identity check" in recovered, "current rollback lost the open-FD external write"
            assert "PRESERVED rollback recovery file" in errors.getvalue(), "recovery artifact was not reported"


def test_rollback_failure_visible(current, temp: pathlib.Path):
    root = temp / "rollback-failure"
    root.mkdir()
    source = temp / "rollback-failure-source.txt"
    source.write_text("keep on rollback error\n", encoding="utf-8")
    state = temp / "rollback-failure-state.json"
    save_empty_state(current, state)
    with contextlib.redirect_stdout(io.StringIO()):
        current.op_copy(str(root), "victim.txt", str(source), str(state))
    victim = root / "victim.txt"
    before = victim.read_bytes()

    def fail_quarantine(_parent_fd, _source, _destination):
        raise OSError(errno.EACCES, "injected rollback permission failure")

    errors = io.StringIO()
    with mock.patch.object(current, "rename_noreplace", fail_quarantine), contextlib.redirect_stderr(errors):
        result = current.rollback(str(root), str(state))
    assert result == 1, "rollback syscall failure was reported as successful"
    assert victim.read_bytes() == before, "failed rollback damaged the installed file"
    assert "rollback could not safely process victim.txt" in errors.getvalue(), (
        "rollback failure details were not visible"
    )


def main():
    old_source = subprocess.check_output(
        ["git", "show", f"{OLD_HEAD}:.agent-maintenance/installer-transaction.py"],
        cwd=HELPER_PATH.parents[1],
    )
    with tempfile.TemporaryDirectory(prefix="installer-race-tests-") as tmp_name:
        temp = pathlib.Path(tmp_name)
        old_path = temp / "legacy-installer-transaction.py"
        old_path.write_bytes(old_source)
        old = load_module(old_path, "legacy_installer_transaction")
        current = load_module(HELPER_PATH, "current_installer_transaction")
        test_existing_file_replace_race(old, current, temp)
        test_directory_move_race(old, current, temp)
        test_rollback_open_fd_race(old, current, temp)
        test_rollback_failure_visible(current, temp)
    print("PASS: legacy/current deterministic race contrasts and visible rollback failure")


if __name__ == "__main__":
    main()

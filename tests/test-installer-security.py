#!/usr/bin/env python3
"""Regression tests for installer symlink races and conservative rollback."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import unittest

sys.dont_write_bytecode = True
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "install.sh"
HELPER = REPO_ROOT / ".agent-maintenance/installer-transaction.py"
SESSION_START = REPO_ROOT / ".agent-maintenance/session-start.sh"
CODEX_COMMAND = 'bash "$(git rev-parse --show-toplevel)/.agent-maintenance/session-start.sh" codex'


def load_helper():
    spec = importlib.util.spec_from_file_location("installer_transaction_security_test", HELPER)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load transaction helper: {HELPER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def init_git_target(path: pathlib.Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", str(path)], check=True)


class InstallerSecurityRegressionTests(unittest.TestCase):
    def test_settings_symlink_race_cannot_touch_external_file_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="installer-settings-race-") as temp_name:
            temp = pathlib.Path(temp_name)
            target = temp / "project"
            init_git_target(target)
            (target / ".codex").mkdir()
            settings = target / ".codex/hooks.json"
            payload = json.dumps(
                {"hooks": {"SessionStart": [{"hooks": [{"command": CODEX_COMMAND}]}]}}
            ) + "\n"
            settings.write_text(payload, encoding="utf-8")

            external = temp / "outside-settings.json"
            external.write_text(payload, encoding="utf-8")
            old_mtime_ns = 1_600_000_000_123_456_789
            os.utime(external, ns=(old_mtime_ns, old_mtime_ns))
            marker = temp / "race-injected"
            shim = temp / "python-shim"
            shim.mkdir()
            (shim / "sitecustomize.py").write_text(
                textwrap.dedent(
                    """\
                    import builtins
                    import os
                    import pathlib

                    _real_open = builtins.open
                    _settings = os.environ["RACE_SETTINGS"]
                    _external = os.environ["RACE_EXTERNAL"]
                    _marker = os.environ["RACE_MARKER"]

                    def _race_at_open(file, *args, **kwargs):
                        try:
                            path = os.path.abspath(os.fspath(file))
                        except TypeError:
                            path = ""
                        if path == _settings and not os.path.exists(_marker):
                            os.unlink(_settings)
                            os.symlink(_external, _settings)
                            pathlib.Path(_marker).write_text("injected", encoding="utf-8")
                        return _real_open(file, *args, **kwargs)

                    builtins.open = _race_at_open
                    """
                ),
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(shim)
            environment["RACE_SETTINGS"] = str(settings)
            environment["RACE_EXTERNAL"] = str(external)
            environment["RACE_MARKER"] = str(marker)
            result = subprocess.run(
                ["bash", str(INSTALLER), "--target", str(target)],
                cwd=target,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
                timeout=60,
            )

            self.assertTrue(marker.is_file(), "test did not replace settings at the open boundary")
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertTrue(settings.is_symlink(), "the injected settings symlink was not preserved")
            self.assertEqual(
                external.stat().st_mtime_ns,
                old_mtime_ns,
                "preflight changed the external target's mtime through a symlink race",
            )
            self.assertFalse((target / "AGENTS.md").exists(), "unsafe settings reached template writes")

    def test_rollback_never_rmdirs_a_directory_moved_outside_target(self) -> None:
        helper = load_helper()
        with tempfile.TemporaryDirectory(prefix="installer-directory-race-") as temp_name:
            temp = pathlib.Path(temp_name)
            target = temp / "project"
            outside = temp / "outside"
            (target / "docs" / "empty").mkdir(parents=True)
            outside.mkdir()
            state_path = temp / "transaction.json"
            helper.save_state(
                str(state_path),
                {"operations": [], "created_directories": ["docs/empty", "docs"]},
            )
            real_rmdir = os.rmdir
            injected = False

            def move_parent_at_rmdir(name, *args, **kwargs):
                nonlocal injected
                if name == "empty" and not injected:
                    os.rename(target / "docs", outside / "moved-docs")
                    os.symlink(outside / "moved-docs", target / "docs")
                    injected = True
                return real_rmdir(name, *args, **kwargs)

            errors = io.StringIO()
            with mock_os_rmdir(move_parent_at_rmdir), contextlib.redirect_stderr(errors):
                status = helper.rollback(str(target), str(state_path))

            self.assertEqual(status, 1, "preserved directories must make rollback explicitly incomplete")
            self.assertFalse(injected, "rollback attempted pathname deletion through a held directory fd")
            self.assertTrue((target / "docs" / "empty").is_dir(), "rollback removed its empty created directory")
            self.assertIn("PRESERVED created directory during rollback", errors.getvalue())

    def test_session_start_rejects_prompt_symlink_outside_project(self) -> None:
        with tempfile.TemporaryDirectory(prefix="session-prompt-symlink-") as temp_name:
            temp = pathlib.Path(temp_name)
            target = temp / "project"
            init_git_target(target)
            (target / "prompts").mkdir()
            external = temp / "external-bootstrap.md"
            external.write_text("untrusted external instructions\n", encoding="utf-8")
            (target / "prompts/bootstrap-project.md").symlink_to(external)

            result = subprocess.run(
                ["bash", str(SESSION_START), "codex"],
                cwd=target,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("symbolic link", result.stdout)
            self.assertNotIn("read and execute prompts/bootstrap-project.md", result.stdout)
            self.assertNotIn("untrusted external instructions", result.stdout)
            self.assertEqual(result.stderr, "")

    def test_help_and_docs_match_manual_merge_and_stdout_behavior(self) -> None:
        help_result = subprocess.run(
            ["bash", str(INSTALLER), "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        docs = (REPO_ROOT / "docs/installation.md").read_text(encoding="utf-8")
        self.assertIn("must be merged manually", help_result.stdout)
        self.assertIn("adding a hook to a pre-existing JSON file requires a manual merge", help_result.stdout)
        self.assertIn("never automatically replaced", readme)
        self.assertIn("requires a manual merge", readme)
        self.assertIn("prints a diagnostic to stdout", docs)
        self.assertNotIn("prints an error to stderr", docs)


class mock_os_rmdir:
    """Temporarily patch the shared os module's rmdir and restore it reliably."""

    def __init__(self, replacement):
        self.replacement = replacement
        self.original = None

    def __enter__(self):
        self.original = os.rmdir
        os.rmdir = self.replacement

    def __exit__(self, *_exc):
        os.rmdir = self.original


if __name__ == "__main__":
    unittest.main(verbosity=2)

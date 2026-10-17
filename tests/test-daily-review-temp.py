#!/usr/bin/env python3
"""Regression tests for the daily-review temporary-file example."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPT = (ROOT / "prompts/daily-review.md").read_text(encoding="utf-8")


def run_shell(script: str, *, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("TMPDIR", None)
    return subprocess.run(
        ["bash", "-c", script], cwd=cwd, env=env,
        text=True, capture_output=True, check=False,
    )


def main() -> None:
    # The old "$TMPDIR/..." form expands to a root-level path when TMPDIR is
    # absent; inspect the expansion only, without touching the real project or
    # root filesystem.
    old = run_shell('printf "%s\\n" "$TMPDIR/frozen-review-manifest.json"', cwd=ROOT)
    assert old.returncode == 0
    assert old.stdout.strip() == "/frozen-review-manifest.json"

    assert 'review_tmp_dir="$(mktemp -d)"' in PROMPT
    assert 'trap review_tmp_dir_cleanup EXIT' in PROMPT
    assert '"$TMPDIR/' not in PROMPT
    assert "temporary files retained at" in PROMPT

    success_script = r'''
set -eu
review_tmp_dir="$(mktemp -d)"
review_tmp_dir_cleanup() {
  status=$?
  if [ "$status" -eq 0 ]; then rm -rf -- "$review_tmp_dir"; else printf '%s\n' "$review_tmp_dir"; fi
  return "$status"
}
trap review_tmp_dir_cleanup EXIT
printf '%s\n' "$review_tmp_dir/frozen-review-manifest.json"
printf '%s\n' "$1" > "$review_tmp_dir/frozen-review-manifest.json"
'''
    failure_script = r'''
set -eu
review_tmp_dir="$(mktemp -d)"
review_tmp_dir_cleanup() {
  status=$?
  if [ "$status" -eq 0 ]; then rm -rf -- "$review_tmp_dir"; else printf '%s\n' "$review_tmp_dir"; fi
  return "$status"
}
trap review_tmp_dir_cleanup EXIT
printf '%s\n' "$review_tmp_dir"
false
'''

    with tempfile.TemporaryDirectory(prefix="daily-review-temp-test-") as work:
        workdir = Path(work)
        first = subprocess.Popen(
            ["bash", "-c", success_script, "_", "run-A"], cwd=workdir,
            env={k: v for k, v in os.environ.items() if k != "TMPDIR"},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        second = subprocess.Popen(
            ["bash", "-c", success_script, "_", "run-B"], cwd=workdir,
            env={k: v for k, v in os.environ.items() if k != "TMPDIR"},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        out_a, err_a = first.communicate()
        out_b, err_b = second.communicate()
        assert first.returncode == second.returncode == 0, (err_a, err_b)
        path_a = Path(out_a.splitlines()[0])
        path_b = Path(out_b.splitlines()[0])
        assert path_a != path_b, (path_a, path_b)
        assert not path_a.parent.exists()
        assert not path_b.parent.exists()

        failed = subprocess.run(
            ["bash", "-c", failure_script], cwd=workdir,
            env={k: v for k, v in os.environ.items() if k != "TMPDIR"},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        assert failed.returncode != 0
        retained = Path(failed.stdout.splitlines()[-1])
        assert retained.is_dir(), failed.stderr
        assert retained.parent == Path("/tmp") or retained.parent.is_dir()
        # Failure artifacts are deliberately retained for recovery, then this
        # test owns and removes the synthetic directory.
        import shutil
        shutil.rmtree(retained)

    print("PASS: daily-review temporary directory isolation and cleanup policy")


if __name__ == "__main__":
    main()

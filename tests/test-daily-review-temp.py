#!/usr/bin/env python3
"""Execute the daily-review temporary-directory example, not a copied fixture."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPT = (ROOT / "prompts/daily-review.md").read_text(encoding="utf-8")
SETUP = PROMPT.split("```bash\n", 1)[1].split("```", 1)[0].split(
    "python3 scripts/freeze-review-range.py", 1
)[0]


def environment() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("TMPDIR", None)
    return env


def run(script: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", "-c", script], cwd=cwd, env=environment(),
                          text=True, capture_output=True, timeout=10)


def main() -> None:
    old = run('printf "%s\\n" "$TMPDIR/frozen-review-manifest.json"', ROOT)
    assert old.stdout.strip() == "/frozen-review-manifest.json"
    assert '"$TMPDIR/' not in PROMPT
    with tempfile.TemporaryDirectory(prefix="daily-review-test-") as directory:
        work = Path(directory)
        script = SETUP + '''
printf '%s\\n' "$review_tmp_dir"
printf 'manifest\\n' > "$review_tmp_dir/frozen-review-manifest.json"
sleep 0.1
'''
        processes = [subprocess.Popen(["bash", "-c", script], cwd=work,
                                      env=environment(), text=True,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                     for _ in range(2)]
        paths = []
        try:
            for process in processes:
                out, err = process.communicate(timeout=10)
                assert process.returncode == 0, err
                paths.append(Path(out.strip()))
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
        assert paths[0] != paths[1]
        assert all(not path.exists() for path in paths)

        failed = run(SETUP + 'printf "%s\\n" "$review_tmp_dir"\nfalse\necho UNREACHABLE\n', work)
        assert failed.returncode != 0
        assert "UNREACHABLE" not in failed.stdout
        retained = Path(failed.stdout.strip())
        try:
            assert retained.is_dir()
            assert str(retained) in failed.stderr
        finally:
            if retained.is_dir():
                shutil.rmtree(retained)

        no_temp = run('mktemp() { return 73; }\n' + SETUP + 'echo UNREACHABLE\n', work)
        assert no_temp.returncode != 0
        assert "UNREACHABLE" not in no_temp.stdout
        assert not list(work.iterdir())
    print("PASS: daily-review documented setup: isolation, cleanup, failure retention, mktemp failure")


if __name__ == "__main__":
    main()

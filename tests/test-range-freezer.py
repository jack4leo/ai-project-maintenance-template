#!/usr/bin/env python3
"""Regression tests for the read-only frozen review-range runner."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
import zlib
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "scripts" / "freeze-review-range.py"
POLICY_SOURCE = REPO_ROOT / "docs" / "automation" / "range-exclusions.json"
sys.dont_write_bytecode = True
FREEZER = types.ModuleType("freeze_review_range")
FREEZER.__file__ = str(RUNNER)
exec(compile(RUNNER.read_text(encoding="utf-8"), str(RUNNER), "exec"), FREEZER.__dict__)


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and completed.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed: {completed.stderr.decode(errors='replace')}"
        )
    return completed


def git_text(repo: Path, *args: str) -> str:
    return git(repo, *args).stdout.decode("utf-8").strip()


def commit(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)
    return git_text(repo, "rev-parse", "HEAD")


def set_marker(repo: Path, value: str) -> None:
    lessons = repo / "LESSONS.md"
    lines = lessons.read_text(encoding="utf-8").splitlines()
    lines[0] = f"<!-- reviewed-through: {value} -->"
    lessons.write_text("\n".join(lines) + "\n", encoding="utf-8")


def create_repo(path: Path, object_format: str = "sha1") -> tuple[Path, str, str]:
    path.mkdir(parents=True, exist_ok=True)
    repo = path / "repo"
    repo.mkdir()
    init_args = ["init", "-q", "-b", "main"]
    if object_format != "sha1":
        init_args.insert(1, f"--object-format={object_format}")
    git(repo, *init_args)
    git(repo, "config", "user.name", "Range Test")
    git(repo, "config", "user.email", "range-test@example.invalid")
    (repo / "docs" / "automation").mkdir(parents=True)
    (repo / "docs" / "reviews").mkdir(parents=True)
    (repo / "LESSONS.md").write_text(
        "<!-- reviewed-through: UNKNOWN (test bootstrap) -->\n# Lessons\n",
        encoding="utf-8",
    )
    (repo / "docs" / "automation" / "range-exclusions.json").write_bytes(
        POLICY_SOURCE.read_bytes()
    )
    (repo / "tracked.txt").write_text("initial\n", encoding="utf-8")
    (repo / "docs" / "reviews" / "keep.md").write_text(
        "preserve this archive placeholder\n", encoding="utf-8"
    )
    anchor = commit(repo, "initial anchor")
    set_marker(repo, anchor)
    baseline_head = commit(repo, "record test watermark")
    return repo, anchor, baseline_head


def invoke(repo: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, str(RUNNER), "--repo", str(repo)],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def path_snapshot(repo: Path) -> dict[str, tuple[int, int, int, int]]:
    snapshot: dict[str, tuple[int, int, int, int]] = {}
    for root, dirs, files in os.walk(repo, followlinks=False):
        dirs[:] = [name for name in dirs if name != ".git"]
        for name in files:
            path = Path(root) / name
            rel = path.relative_to(repo).as_posix()
            info = path.lstat()
            snapshot[rel] = (
                info.st_mode,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
            )
        for name in list(dirs):
            path = Path(root) / name
            if path.is_symlink():
                info = path.lstat()
                rel = path.relative_to(repo).as_posix()
                snapshot[rel] = (
                    info.st_mode,
                    info.st_size,
                    info.st_mtime_ns,
                    info.st_ctime_ns,
                )
    return snapshot


class FrozenRangeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="range-freezer-test-")
        self.addCleanup(self.temp.cleanup)
        self.temp_path = Path(self.temp.name)
        self.repo, self.anchor, self.baseline_head = create_repo(self.temp_path)

    def assert_cli_failure(self, repo: Path, expected: str | None = None) -> None:
        completed = invoke(repo)
        self.assertNotEqual(completed.returncode, 0, completed.stdout.decode(errors="replace"))
        self.assertEqual(completed.stdout, b"", "failed freeze must not emit a successful manifest")
        error = completed.stderr.decode("utf-8", errors="replace")
        if expected:
            self.assertIn(expected, error)

    def test_complete_linear_history_is_oldest_first_and_full_sha(self) -> None:
        (self.repo / "one.txt").write_text("one\n", encoding="utf-8")
        one = commit(self.repo, "first range commit")
        (self.repo / "two.txt").write_text("two\n", encoding="utf-8")
        two = commit(self.repo, "second range commit")

        manifest = FREEZER.freeze_range(self.repo)
        self.assertEqual(manifest["from"], self.anchor)
        self.assertEqual(manifest["through"], two)
        self.assertEqual([item["sha"] for item in manifest["commits"]], [
            self.baseline_head,
            one,
            two,
        ])
        for item in manifest["commits"]:
            self.assertRegex(item["sha"], r"^[0-9a-f]{40}$")
            self.assertRegex(item["tree"], r"^[0-9a-f]{40}$")
            for parent in item["parents"]:
                self.assertRegex(parent, r"^[0-9a-f]{40}$")

    def test_merge_history_has_deterministic_parent_before_child_order(self) -> None:
        git(self.repo, "switch", "-c", "side")
        (self.repo / "side.txt").write_text("side\n", encoding="utf-8")
        side = commit(self.repo, "side branch commit")
        git(self.repo, "switch", "main")
        (self.repo / "main.txt").write_text("main\n", encoding="utf-8")
        main = commit(self.repo, "main branch commit")
        git(self.repo, "merge", "--no-ff", "side", "-m", "merge side")
        merge = git_text(self.repo, "rev-parse", "HEAD")

        manifest = FREEZER.freeze_range(self.repo)
        ids = [item["sha"] for item in manifest["commits"]]
        self.assertEqual(ids, [self.baseline_head, *sorted([side, main]), merge])
        positions = {sha: index for index, sha in enumerate(ids)}
        for item in manifest["commits"]:
            for parent in item["parents"]:
                if parent in positions:
                    self.assertLess(positions[parent], positions[item["sha"]])
        self.assertEqual(manifest["commits"][-1]["parents"], [main, side])

    def test_sha256_object_format_uses_full_object_ids(self) -> None:
        repo, anchor, _ = create_repo(self.temp_path / "sha256", "sha256")
        manifest = FREEZER.freeze_range(repo)
        self.assertEqual(manifest["from"], anchor)
        self.assertEqual(len(manifest["from"]), 64)
        self.assertEqual(len(manifest["through"]), 64)
        for item in manifest["commits"]:
            self.assertEqual(len(item["sha"]), 64)
            self.assertEqual(len(item["tree"]), 64)
            self.assertTrue(all(len(parent) == 64 for parent in item["parents"]))

    def test_shallow_clone_fails_closed(self) -> None:
        source = self.repo
        shallow = self.temp_path / "shallow"
        clone = subprocess.run(
            ["git", "clone", "--quiet", "--depth", "1", f"file://{source}", str(shallow)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(clone.returncode, 0, clone.stderr.decode(errors="replace"))
        self.assert_cli_failure(shallow, "shallow history")

    def test_missing_parent_object_fails_closed(self) -> None:
        object_path = self.repo / ".git" / "objects" / self.anchor[:2] / self.anchor[2:]
        self.assertTrue(object_path.is_file(), "fixture commit should be a loose object")
        object_path.unlink()
        self.assert_cli_failure(self.repo)

    def test_missing_reachable_blob_fails_closed(self) -> None:
        broken = self.repo / "reachable.txt"
        broken.write_text("reachable blob\n", encoding="utf-8")
        commit(self.repo, "add reachable blob")
        blob = git_text(self.repo, "rev-parse", "HEAD:reachable.txt")
        object_path = self.repo / ".git" / "objects" / blob[:2] / blob[2:]
        self.assertTrue(object_path.is_file(), "fixture blob should be a loose object")
        object_path.unlink()
        self.assert_cli_failure(self.repo)

    def test_hash_mismatched_reachable_object_fails_closed(self) -> None:
        blob = git_text(self.repo, "rev-parse", f"{self.anchor}:tracked.txt")
        object_path = self.repo / ".git" / "objects" / blob[:2] / blob[2:]
        raw = zlib.decompress(object_path.read_bytes())
        header, content = raw.split(b"\0", 1)
        self.assertIn(b"initial", content)
        altered_content = content.replace(b"initial", b"Initial", 1)
        self.assertEqual(len(altered_content), len(content))
        object_path.chmod(0o644)
        object_path.write_bytes(zlib.compress(header + b"\0" + altered_content))
        self.assert_cli_failure(self.repo)

    def test_rewritten_non_ancestor_watermark_fails_closed(self) -> None:
        git(self.repo, "checkout", "--orphan", "rewritten")
        git(self.repo, "rm", "-rf", ".")
        (self.repo / "docs" / "automation").mkdir(parents=True)
        (self.repo / "LESSONS.md").write_text(
            f"<!-- reviewed-through: {self.anchor} -->\n# Lessons\n",
            encoding="utf-8",
        )
        (self.repo / "docs" / "automation" / "range-exclusions.json").write_bytes(
            POLICY_SOURCE.read_bytes()
        )
        (self.repo / "rewritten.txt").write_text("new root\n", encoding="utf-8")
        commit(self.repo, "force-pushed replacement root")
        self.assert_cli_failure(self.repo, "not an ancestor")

    def test_missing_unknown_and_malformed_watermarks_fail_closed(self) -> None:
        lessons = self.repo / "LESSONS.md"
        original = lessons.read_text(encoding="utf-8")
        cases = [
            ("<!-- no watermark -->\n# Lessons\n", "exactly one"),
            ("<!-- reviewed-through:  -->\n# Lessons\n", "first line"),
            ("<!-- reviewed-through: UNKNOWN (bootstrap) -->\n# Lessons\n", "full 40-character"),
            (f"<!-- reviewed-through: {self.anchor[:8]} -->\n# Lessons\n", "full 40-character"),
            (f"<!-- reviewed-through: {'f' * 40} -->\n# Lessons\n", "does not resolve"),
            (
                f"<!-- reviewed-through: {self.anchor} -->\n"
                f"<!-- reviewed-through: {self.anchor} -->\n# Lessons\n",
                "exactly one",
            ),
        ]
        for data, expected in cases:
            with self.subTest(watermark=data.splitlines()[0]):
                lessons.write_text(data, encoding="utf-8")
                self.assert_cli_failure(self.repo, expected)
        lessons.write_text(original, encoding="utf-8")

    def test_exclusions_are_explicit_and_rule_changes_affect_key(self) -> None:
        generated = self.repo / "dist" / "generated.js"
        generated.parent.mkdir()
        generated.write_text("generated output\n", encoding="utf-8")
        (self.repo / "image.bin").write_bytes(b"\x89PNG\x00binary\x01")
        through = commit(self.repo, "add generated and binary files")

        manifest = FREEZER.freeze_range(self.repo)
        self.assertEqual(manifest["through"], through)
        by_path: dict[str, set[str]] = {}
        for item in manifest["excluded_paths"]:
            by_path.setdefault(item["path"], set()).add(item["rule_id"])
        self.assertIn("generated-output", by_path["dist/generated.js"])
        self.assertIn("binary-nul-content", by_path["image.bin"])
        self.assertEqual(manifest["exclusion_policy"]["source_path"], "docs/automation/range-exclusions.json")
        self.assertEqual(
            manifest["exclusion_policy"]["source_sha256"],
            hashlib.sha256(POLICY_SOURCE.read_bytes()).hexdigest(),
        )

        payload = {key: value for key, value in manifest.items() if key != "range_key"}
        self.assertEqual(FREEZER.add_range_key(payload)["range_key"], manifest["range_key"])
        altered = json.loads(json.dumps(payload))
        altered["exclusion_policy"]["rules"][0]["reason"] += " Revised policy."
        self.assertNotEqual(
            FREEZER.add_range_key(payload)["range_key"],
            FREEZER.add_range_key(altered)["range_key"],
            "the range key must bind exclusion-policy content even with identical boundaries and commits",
        )

    def test_binary_deletion_checks_old_blob_across_chunk_boundary(self) -> None:
        binary = self.repo / "large.bin"
        binary.write_bytes(b"A" * (64 * 1024) + b"\0" + b"B" * 20)
        commit(self.repo, "add large binary with boundary NUL")
        binary.unlink()
        commit(self.repo, "delete large binary")

        manifest = FREEZER.freeze_range(self.repo)
        deletion = [
            item
            for item in manifest["excluded_paths"]
            if item["path"] == "large.bin"
            and item["status"] == "D"
            and item["rule_id"] == "binary-nul-content"
        ]
        self.assertEqual(len(deletion), 1)
        self.assertIsNotNone(deletion[0]["old_oid"])
        self.assertIsNone(deletion[0]["new_oid"])

    def test_gitlink_is_reported_and_symlink_is_not_silently_excluded(self) -> None:
        (self.repo / "target.txt").write_text("target\n", encoding="utf-8")
        os.symlink("target.txt", self.repo / "link.txt")
        commit(self.repo, "add a symlink")
        git(
            self.repo,
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{self.anchor},modules/nested",
        )
        git(self.repo, "commit", "-m", "add gitlink")

        manifest = FREEZER.freeze_range(self.repo)
        records = manifest["excluded_paths"]
        gitlink = [item for item in records if item["path"] == "modules/nested"]
        self.assertEqual(len(gitlink), 1)
        self.assertEqual(gitlink[0]["rule_id"], "gitlink-submodule")
        self.assertEqual(gitlink[0]["new_oid"], self.anchor)
        self.assertNotIn("link.txt", {item["path"] for item in records})

    def test_non_utf8_changed_path_fails_closed(self) -> None:
        raw_path = os.fsencode(self.repo) + b"/bad-\xff-name.txt"
        fd = os.open(raw_path, os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            os.write(fd, b"unrepresentable path\n")
        finally:
            os.close(fd)
        commit(self.repo, "add non-UTF-8 path")
        self.assert_cli_failure(self.repo, "not valid UTF-8")

    def test_same_inputs_retry_to_identical_canonical_manifest_and_key(self) -> None:
        first = FREEZER.canonical_json(FREEZER.freeze_range(self.repo))
        second = FREEZER.canonical_json(FREEZER.freeze_range(self.repo))
        self.assertEqual(first, second)
        parsed = json.loads(first)
        self.assertTrue(parsed["range_key"].startswith("sha256:"))
        self.assertEqual(first, FREEZER.canonical_json(parsed))
        self.assertEqual(parsed["excluded_paths"], [])
        self.assertEqual(
            {rule["id"] for rule in parsed["exclusion_policy"]["rules"]},
            {"generated-output", "binary-nul-content", "gitlink-submodule"},
        )

    def test_dirty_worktree_policy_fails_closed(self) -> None:
        policy = self.repo / "docs" / "automation" / "range-exclusions.json"
        policy.write_bytes(policy.read_bytes() + b"\n")
        with self.assertRaisesRegex(FREEZER.FreezeError, "differs from its committed version"):
            FREEZER.freeze_range(self.repo)

    def test_watermark_change_during_freeze_fails_closed(self) -> None:
        original_reader = FREEZER.read_watermark
        calls = 0

        def mutate_after_first_read(repo: Path, length: int) -> tuple[str, bytes, tuple[int, ...]]:
            nonlocal calls
            result = original_reader(repo, length)
            calls += 1
            if calls == 1:
                set_marker(repo, "f" * length)
            return result

        with mock.patch.object(FREEZER, "read_watermark", side_effect=mutate_after_first_read):
            with self.assertRaisesRegex(FREEZER.FreezeError, "changed while the range was being frozen"):
                FREEZER.freeze_range(self.repo)

    def test_advancing_head_creates_a_different_range_and_key(self) -> None:
        first = FREEZER.freeze_range(self.repo)
        (self.repo / "later.txt").write_text("later\n", encoding="utf-8")
        later_head = commit(self.repo, "advance head")
        second = FREEZER.freeze_range(self.repo)
        self.assertEqual(second["through"], later_head)
        self.assertNotEqual(first["through"], second["through"])
        self.assertNotEqual(first["range_key"], second["range_key"])

    def test_same_watermark_and_head_produces_an_empty_commit_list(self) -> None:
        head = git_text(self.repo, "rev-parse", "HEAD")
        set_marker(self.repo, head)
        manifest = FREEZER.freeze_range(self.repo)
        self.assertEqual(manifest["from"], head)
        self.assertEqual(manifest["through"], head)
        self.assertEqual(manifest["commits"], [])

    def test_runner_never_writes_lessons_or_docs_reviews_and_preserves_atime(self) -> None:
        lessons = self.repo / "LESSONS.md"
        policy = self.repo / "docs" / "automation" / "range-exclusions.json"
        review_dir = self.repo / "docs" / "reviews"
        keep = review_dir / "keep.md"
        lessons_bytes = lessons.read_bytes()
        policy_bytes = policy.read_bytes()
        keep_bytes = keep.read_bytes()
        before_review_dir = review_dir.stat()

        old_atime_ns = 1_000_000_000
        for path in (lessons, policy):
            info = path.stat()
            os.utime(path, ns=(old_atime_ns, info.st_mtime_ns))
        git_objects = [
            path
            for path in (self.repo / ".git" / "objects").rglob("*")
            if path.is_file()
        ]
        for path in git_objects:
            info = path.stat()
            os.utime(path, ns=(old_atime_ns, info.st_mtime_ns))
        lessons_atime = lessons.stat().st_atime_ns
        policy_atime = policy.stat().st_atime_ns
        object_atimes = {path: path.stat().st_atime_ns for path in git_objects}
        before_tree = path_snapshot(self.repo)

        completed = invoke(self.repo)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors="replace"))
        output = json.loads(completed.stdout)
        self.assertIn("range_key", output)

        self.assertEqual(path_snapshot(self.repo), before_tree)
        self.assertEqual(lessons.stat().st_atime_ns, lessons_atime)
        self.assertEqual(policy.stat().st_atime_ns, policy_atime)
        for path, atime_ns in object_atimes.items():
            self.assertEqual(path.stat().st_atime_ns, atime_ns, str(path))
        self.assertEqual(
            FREEZER.read_regular_file_noatime(lessons, "LESSONS.md")[0], lessons_bytes
        )
        self.assertEqual(
            FREEZER.read_regular_file_noatime(policy, "range exclusion policy")[0],
            policy_bytes,
        )
        self.assertEqual(keep.read_bytes(), keep_bytes)
        after_review_dir = review_dir.stat()
        self.assertEqual(after_review_dir.st_mtime_ns, before_review_dir.st_mtime_ns)
        self.assertEqual(after_review_dir.st_ctime_ns, before_review_dir.st_ctime_ns)

    def test_packed_git_object_atime_is_preserved(self) -> None:
        git(self.repo, "gc", "--prune=now")
        packed_files = [
            path
            for path in (self.repo / ".git" / "objects").rglob("*")
            if path.is_file()
        ]
        self.assertTrue(any(path.suffix == ".pack" for path in packed_files))
        old_atime_ns = 1_000_000_000
        for path in packed_files:
            info = path.stat()
            os.utime(path, ns=(old_atime_ns, info.st_mtime_ns))
        before = {path: path.stat().st_atime_ns for path in packed_files}

        completed = invoke(self.repo)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors="replace"))
        for path, atime_ns in before.items():
            self.assertEqual(path.stat().st_atime_ns, atime_ns, str(path))

    def test_failure_does_not_emit_partial_manifest(self) -> None:
        lessons = self.repo / "LESSONS.md"
        lessons.write_text("<!-- reviewed-through: UNKNOWN -->\n# Lessons\n", encoding="utf-8")
        self.assert_cli_failure(self.repo, "full 40-character")


if __name__ == "__main__":
    unittest.main(verbosity=2)

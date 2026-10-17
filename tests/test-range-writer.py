#!/usr/bin/env python3
"""Regression tests for the frozen-range writer's contract and safety boundary."""

from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
WRITER_PATH = REPO_ROOT / "scripts" / "write-frozen-review.py"
FREEZER_PATH = REPO_ROOT / "scripts" / "freeze-review-range.py"
sys.dont_write_bytecode = True
WRITER = types.ModuleType("write_frozen_review")
WRITER.__file__ = str(WRITER_PATH)
exec(compile(WRITER_PATH.read_text(encoding="utf-8"), str(WRITER_PATH), "exec"), WRITER.__dict__)
FREEZER = types.ModuleType("freeze_review_range")
FREEZER.__file__ = str(FREEZER_PATH)
exec(compile(FREEZER_PATH.read_text(encoding="utf-8"), str(FREEZER_PATH), "exec"), FREEZER.__dict__)


FROM = "a" * 40
THROUGH = "b" * 40


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr.decode("utf-8", errors="replace"))
    return result.stdout.decode("utf-8", errors="replace").strip()


def make_manifest(from_sha: str = FROM, through: str = THROUGH) -> dict[str, object]:
    payload: dict[str, object] = {
        "manifest_version": 1,
        "from": from_sha,
        "through": through,
        "commits": [{"sha": "c" * len(from_sha), "tree": "d" * len(from_sha), "parents": [from_sha]}],
        "exclusion_policy": {
            "source_path": "docs/automation/range-exclusions.json",
            "source_commit": through,
            "source_blob": "e" * len(from_sha),
            "source_sha256": "f" * 64,
            "policy_version": 1,
            "rules": [],
        },
        "excluded_paths": [],
    }
    manifest = dict(payload)
    manifest["range_key"] = "sha256:" + hashlib.sha256(WRITER.canonical_json(payload)).hexdigest()
    return manifest


def reseal_manifest(manifest: dict[str, object]) -> dict[str, object]:
    payload = {key: value for key, value in manifest.items() if key != "range_key"}
    manifest["range_key"] = "sha256:" + hashlib.sha256(WRITER.canonical_json(payload)).hexdigest()
    return manifest


def write_inputs(folder: Path, manifest: dict[str, object], archive: str, lessons: str) -> tuple[Path, Path, Path]:
    manifest_path = folder / "manifest.json"
    archive_path = folder / "archive.md"
    lessons_path = folder / "lessons.md"
    manifest_path.write_bytes(WRITER.canonical_json(manifest) + b"\n")
    archive_path.write_text(archive, encoding="utf-8")
    lessons_path.write_text(lessons, encoding="utf-8")
    return manifest_path, archive_path, lessons_path


class FrozenWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="range-writer-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.name", "Writer Test")
        git(self.repo, "config", "user.email", "writer-test@example.invalid")
        self.lessons = self.repo / "LESSONS.md"
        self.lessons.write_text(
            f"<!-- reviewed-through: {FROM} -->\n# Lessons\n\n## Active lessons\n\n<!-- ACTIVE_LESSONS:START -->\n<!-- ACTIVE_LESSONS:END -->\n\n## Promotion history\n\n<!-- PROMOTED_LESSONS:START -->\n<!-- PROMOTED_LESSONS:END -->\n",
            encoding="utf-8",
        )
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.manifest = make_manifest()

    def run_writer(self, archive_body: str = "Review body", lesson_body: str = "### Rule\n- **Why:** evidence\n- **Evidence:** commit\n- **Fix or follow-up:** done\n- **Seen 1×:** 2026-10-16\n- **Status:** active", archive: str = "docs/reviews/2026-10-16.md") -> dict[str, str]:
        manifest_path, archive_path, lessons_path = write_inputs(
            self.inputs, self.manifest, archive_body, lesson_body
        )
        return WRITER.write_review(self.repo, manifest_path, archive, archive_path, lessons_path)

    def test_manifest_format_and_range_key_are_verified_without_recomputing_range(self) -> None:
        result = self.run_writer()
        self.assertEqual(result["from"], FROM)
        self.assertEqual(result["through"], THROUGH)
        self.assertEqual(result["range_key"], self.manifest["range_key"])
        self.assertIn(str(THROUGH), self.lessons.read_text(encoding="utf-8").splitlines()[0])

        bad = dict(self.manifest)
        bad["range_key"] = "sha256:" + "0" * 64
        mpath, apath, lpath = write_inputs(self.inputs, bad, "bad", "bad")
        before = self.lessons.read_bytes()
        with self.assertRaisesRegex(WRITER.WriterError, "range_key"):
            WRITER.write_review(self.repo, mpath, "docs/reviews/bad.md", apath, lpath)
        self.assertEqual(self.lessons.read_bytes(), before)
        self.assertFalse((self.repo / "docs/reviews/bad.md").exists())

    def test_actual_freezer_manifest_with_exclusions_is_accepted_and_written(self) -> None:
        self.lessons.write_text(
            self.lessons.read_text(encoding="utf-8").replace(FROM, "UNKNOWN", 1),
            encoding="utf-8",
        )
        policy_path = self.repo / "docs/automation/range-exclusions.json"
        policy_path.parent.mkdir(parents=True)
        policy_path.write_text(
            json.dumps(
                {
                    "policy_version": 1,
                    "rules": [
                        {
                            "id": "review-records",
                            "kind": "path-glob",
                            "patterns": ["docs/reviews/**"],
                            "reason": "review records are excluded from code review ranges",
                        }
                    ],
                },
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        (self.repo / "README.md").write_text("baseline\n", encoding="utf-8")
        git(self.repo, "add", "LESSONS.md", "README.md", "docs/automation/range-exclusions.json")
        git(self.repo, "commit", "-m", "baseline")
        from_sha = git(self.repo, "rev-parse", "HEAD")
        self.lessons.write_text(
            self.lessons.read_text(encoding="utf-8").replace("reviewed-through: UNKNOWN", f"reviewed-through: {from_sha}", 1),
            encoding="utf-8",
        )
        review_dir = self.repo / "docs/reviews"
        review_dir.mkdir(parents=True)
        (review_dir / "excluded-input.md").write_text("excluded record\n", encoding="utf-8")
        git(self.repo, "add", "LESSONS.md", "docs/reviews/excluded-input.md")
        git(self.repo, "commit", "-m", "advance range and add excluded review record")

        manifest = FREEZER.freeze_range(self.repo)
        self.assertEqual(manifest["from"], from_sha)
        self.assertEqual(len(manifest["excluded_paths"]), 1)
        manifest_path, archive_path, lessons_path = write_inputs(
            self.inputs, manifest, "review body", "### Actual freezer lesson"
        )
        result = WRITER.write_review(
            self.repo,
            manifest_path,
            "docs/reviews/2026-10-17.md",
            archive_path,
            lessons_path,
        )
        self.assertEqual(result["range_key"], manifest["range_key"])
        self.assertIn(f"reviewed-through: {manifest['through']}", self.lessons.read_text(encoding="utf-8").splitlines()[0])
        self.assertTrue((review_dir / "2026-10-17.md").exists())

    def test_nested_manifest_schema_rejects_non_freezer_shapes_even_with_resealed_key(self) -> None:
        cases: list[tuple[str, dict[str, object]]] = []
        bad_commit = json.loads(json.dumps(self.manifest))
        bad_commit["commits"][0]["unexpected"] = "accepted by the old validator"
        cases.append(("commit record", bad_commit))
        bad_policy = json.loads(json.dumps(self.manifest))
        bad_policy["exclusion_policy"]["rules"] = {"not": "an array"}
        cases.append(("policy rules", bad_policy))
        bad_exclusion = json.loads(json.dumps(self.manifest))
        bad_exclusion["excluded_paths"] = [{"unexpected": "record"}]
        cases.append(("excluded-path record", bad_exclusion))

        for index, (label, bad) in enumerate(cases):
            with self.subTest(label=label):
                reseal_manifest(bad)
                manifest_path, archive_path, lessons_path = write_inputs(
                    self.inputs, bad, f"bad-{index}", f"bad-{index}"
                )
                with self.assertRaisesRegex(WRITER.WriterError, "malformed|unexpected|rules"):
                    WRITER.write_review(
                        self.repo,
                        manifest_path,
                        f"docs/reviews/bad-{index}.md",
                        archive_path,
                        lessons_path,
                    )
                self.assertFalse((self.repo / "docs").exists())

    def test_legacy_single_line_lesson_anchors_remain_supported(self) -> None:
        self.lessons.write_text(
            f"<!-- reviewed-through: {FROM} -->\n# Lessons\n\n## Active lessons\n\n<!-- ACTIVE_LESSONS -->\n\n## Promotion history\n\n<!-- PROMOTED_LESSONS -->\n",
            encoding="utf-8",
        )
        self.run_writer("legacy archive", "### Legacy-compatible lesson")
        lessons = self.lessons.read_text(encoding="utf-8")
        self.assertIn("<!-- ACTIVE_LESSONS -->", lessons)
        self.assertIn("<!-- PROMOTED_LESSONS -->", lessons)
        self.assertIn("Legacy-compatible lesson", lessons)
        self.assertLess(lessons.index("Legacy-compatible lesson"), lessons.index("<!-- PROMOTED_LESSONS -->"))

    def test_same_key_retry_replaces_only_its_blocks_and_preserves_other_ranges(self) -> None:
        review_dir = self.repo / "docs" / "reviews"
        review_dir.mkdir(parents=True)
        (review_dir / ".rollback-retained").write_text("preserve rollback artifact\n", encoding="utf-8")
        (review_dir / ".flywheel-retained").write_text("preserve ordinary hidden file\n", encoding="utf-8")
        self.run_writer("first archive", "### First lesson\n- **Seen 1×:** 2026-10-16")
        archive_path = self.repo / "docs/reviews/2026-10-16.md"
        first_archive = archive_path.read_text(encoding="utf-8")
        self.assertIn("first archive", first_archive)
        self.assertIn(self.manifest["range_key"], first_archive)

        # An unrelated range entry on the same review date must survive this key's retry.
        unrelated = "sha256:" + "e" * 64
        archive_path.write_text(
            first_archive + f"\n<!-- frozen-review-range: {unrelated} -->\nother range\n<!-- /frozen-review-range: {unrelated} -->\n",
            encoding="utf-8",
        )
        self.run_writer("completed archive", "### Completed lesson\n- **Seen 1×:** 2026-10-16")
        archive = archive_path.read_text(encoding="utf-8")
        lessons = self.lessons.read_text(encoding="utf-8")
        self.assertIn("completed archive", archive)
        self.assertNotIn("first archive", archive)
        self.assertIn("other range", archive)
        self.assertEqual(archive.count(self.manifest["range_key"]), 2)  # paired start/end tags
        self.assertEqual(lessons.count(self.manifest["range_key"]), 2)
        self.assertIn("Completed lesson", lessons)
        self.assertNotIn("First lesson", lessons)
        self.assertEqual((review_dir / ".rollback-retained").read_text(encoding="utf-8"), "preserve rollback artifact\n")
        self.assertEqual((review_dir / ".flywheel-retained").read_text(encoding="utf-8"), "preserve ordinary hidden file\n")

    def test_lesson_write_failure_keeps_old_watermark_and_retry_completes_same_key(self) -> None:
        manifest_path, archive_path, lessons_path = write_inputs(
            self.inputs, self.manifest, "saved archive", "### Retry lesson"
        )
        real_write = WRITER.atomic_write_at
        calls = 0

        def fail_lessons(
            directory_fd: int,
            name: str,
            content: bytes,
            description: str,
            expected_snapshot: tuple[bytes | None, tuple[int, ...] | None] | None = None,
        ) -> None:
            nonlocal calls
            calls += 1
            if name == "LESSONS.md" and calls == 2:
                raise WRITER.WriterError("injected Lessons write failure")
            real_write(directory_fd, name, content, description, expected_snapshot)

        with mock.patch.object(WRITER, "atomic_write_at", side_effect=fail_lessons):
            with self.assertRaisesRegex(WRITER.WriterError, "injected Lessons"):
                WRITER.write_review(
                    self.repo,
                    manifest_path,
                    "docs/reviews/2026-10-16.md",
                    archive_path,
                    lessons_path,
                )
        self.assertIn(f"reviewed-through: {FROM}", self.lessons.read_text(encoding="utf-8").splitlines()[0])
        self.assertIn("saved archive", (self.repo / "docs/reviews/2026-10-16.md").read_text(encoding="utf-8"))

        result = self.run_writer("saved archive", "### Retry lesson")
        self.assertEqual(result["range_key"], self.manifest["range_key"])
        self.assertIn(f"reviewed-through: {THROUGH}", self.lessons.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual((self.repo / "docs/reviews/2026-10-16.md").read_text(encoding="utf-8").count(self.manifest["range_key"]), 2)

    def test_unknown_watermark_is_not_bootstrapped_and_does_not_create_archive_dirs(self) -> None:
        self.lessons.write_text(self.lessons.read_text(encoding="utf-8").replace(FROM, "UNKNOWN"), encoding="utf-8")
        manifest_path, archive_path, lessons_path = write_inputs(self.inputs, self.manifest, "review", "lesson")
        with self.assertRaisesRegex(WRITER.WriterError, "UNKNOWN"):
            WRITER.write_review(self.repo, manifest_path, "docs/reviews/2026-10-16.md", archive_path, lessons_path)
        self.assertFalse((self.repo / "docs").exists())
        self.assertIn("reviewed-through: UNKNOWN", self.lessons.read_text(encoding="utf-8").splitlines()[0])

    def test_symlink_archive_parent_is_refused(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        (self.repo / "docs").mkdir()
        os.symlink(outside, self.repo / "docs" / "reviews")
        manifest_path, archive_path, lessons_path = write_inputs(self.inputs, self.manifest, "review", "lesson")
        with self.assertRaises(WRITER.WriterError):
            WRITER.write_review(self.repo, manifest_path, "docs/reviews/2026-10-16.md", archive_path, lessons_path)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertIn(f"reviewed-through: {FROM}", self.lessons.read_text(encoding="utf-8").splitlines()[0])

    def test_stale_snapshot_is_not_overwritten_and_temp_cleanup_requires_inode_proof(self) -> None:
        directory_fd = os.open(self.repo, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            target = self.repo / "snapshot.md"
            target.write_text("original\n", encoding="utf-8")
            original, original_identity, _ = WRITER.read_file_at(directory_fd, "snapshot.md", "snapshot.md")
            target.write_text("newer external content\n", encoding="utf-8")
            with self.assertRaisesRegex(WRITER.WriterError, "changed since it was read"):
                WRITER.atomic_write_at(
                    directory_fd,
                    "snapshot.md",
                    b"stale replacement\n",
                    "snapshot.md",
                    (original, original_identity),
                )
            self.assertEqual(target.read_text(encoding="utf-8"), "newer external content\n")

            temp_name = ".owned-temp"
            held_name = ".held-temp-inode"
            (self.repo / temp_name).write_text("transaction inode\n", encoding="utf-8")
            owned_info = (self.repo / temp_name).stat()
            os.rename(self.repo / temp_name, self.repo / held_name)
            (self.repo / temp_name).write_text("replacement inode\n", encoding="utf-8")
            WRITER._cleanup_owned_temp(directory_fd, temp_name, (owned_info.st_dev, owned_info.st_ino))
            self.assertTrue((self.repo / temp_name).exists(), "cleanup removed a path whose inode was not transaction-owned")
            self.assertEqual((self.repo / held_name).read_text(encoding="utf-8"), "transaction inode\n")
        finally:
            os.close(directory_fd)

    def test_staged_path_inode_swap_is_detected_before_publish_and_unowned_path_is_preserved(self) -> None:
        directory_fd = os.open(self.repo, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        target = self.repo / "snapshot.md"
        target.write_text("original target\n", encoding="utf-8")
        real_fsync = os.fsync
        swapped = False

        def swap_staged_path(fd: int) -> None:
            nonlocal swapped
            real_fsync(fd)
            if swapped:
                return
            names = [
                name
                for name in os.listdir(directory_fd)
                if name.startswith(".snapshot.md.frozen-review-writer-") and name.endswith(".tmp")
            ]
            self.assertEqual(len(names), 1)
            temp_name = names[0]
            os.rename(temp_name, temp_name + ".held", src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            replacement_fd = os.open(
                temp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=directory_fd,
            )
            try:
                os.write(replacement_fd, b"unowned replacement\n")
            finally:
                os.close(replacement_fd)
            swapped = True

        try:
            with mock.patch.object(WRITER.os, "fsync", side_effect=swap_staged_path):
                with self.assertRaisesRegex(WRITER.WriterError, "no longer names this transaction"):
                    WRITER.atomic_write_at(directory_fd, "snapshot.md", b"new target\n", "snapshot.md")
            self.assertTrue(swapped, "test did not replace the staged directory entry")
            self.assertEqual(target.read_text(encoding="utf-8"), "original target\n")
            leftovers = [name for name in os.listdir(directory_fd) if ".frozen-review-writer-" in name]
            self.assertEqual(len(leftovers), 2, "unverified staging paths should remain available for inspection")
            self.assertTrue(any(name.endswith(".held") for name in leftovers))
            self.assertTrue(any(name.endswith(".tmp") for name in leftovers))
        finally:
            os.close(directory_fd)

    def test_path_swap_in_final_rename_gap_is_reported_as_uncertain(self) -> None:
        directory_fd = os.open(self.repo, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        target = self.repo / "snapshot.md"
        target.write_text("original target\n", encoding="utf-8")
        real_replace = os.replace
        swapped = False

        def swap_then_replace(src: str, dst: str, *, src_dir_fd: int, dst_dir_fd: int) -> None:
            nonlocal swapped
            os.rename(src, src + ".held", src_dir_fd=src_dir_fd, dst_dir_fd=src_dir_fd)
            replacement_fd = os.open(
                src,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=src_dir_fd,
            )
            try:
                os.write(replacement_fd, b"unowned replacement\n")
            finally:
                os.close(replacement_fd)
            swapped = True
            real_replace(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

        try:
            with mock.patch.object(WRITER.os, "replace", side_effect=swap_then_replace):
                with self.assertRaisesRegex(WRITER.WriterError, "does not have the staged transaction inode"):
                    WRITER.atomic_write_at(directory_fd, "snapshot.md", b"new target\n", "snapshot.md")
            self.assertTrue(swapped, "test did not inject a path swap in the final rename gap")
            self.assertEqual(target.read_text(encoding="utf-8"), "unowned replacement\n")
            self.assertTrue(any(name.endswith(".held") for name in os.listdir(directory_fd)))
        finally:
            os.close(directory_fd)

    def test_empty_lessons_is_retryable_and_archive_path_is_explicitly_bounded(self) -> None:
        result = self.run_writer("valid review", "", "docs/reviews/2026-10-16.md")
        self.assertIn(result["range_key"], self.lessons.read_text(encoding="utf-8"))
        self.assertIn("no lesson entries", self.lessons.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(WRITER.WriterError, "docs/reviews"):
            WRITER.validate_relative_archive("LESSONS.md")
        with self.assertRaisesRegex(WRITER.WriterError, "parent"):
            WRITER.validate_relative_archive("docs/reviews/../LESSONS.md")


if __name__ == "__main__":
    unittest.main(verbosity=2)

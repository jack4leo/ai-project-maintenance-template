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
PROMOTION_VALIDATOR_PATH = REPO_ROOT / "scripts" / "validate_lesson_promotions.py"
sys.dont_write_bytecode = True
WRITER = types.ModuleType("write_frozen_review")
WRITER.__file__ = str(WRITER_PATH)
exec(compile(WRITER_PATH.read_text(encoding="utf-8"), str(WRITER_PATH), "exec"), WRITER.__dict__)
FREEZER = types.ModuleType("freeze_review_range")
FREEZER.__file__ = str(FREEZER_PATH)
exec(compile(FREEZER_PATH.read_text(encoding="utf-8"), str(FREEZER_PATH), "exec"), FREEZER.__dict__)
PROMOTION_VALIDATOR = types.ModuleType("validate_lesson_promotions")
PROMOTION_VALIDATOR.__file__ = str(PROMOTION_VALIDATOR_PATH)
sys.modules[PROMOTION_VALIDATOR.__name__] = PROMOTION_VALIDATOR
exec(
    compile(PROMOTION_VALIDATOR_PATH.read_text(encoding="utf-8"), str(PROMOTION_VALIDATOR_PATH), "exec"),
    PROMOTION_VALIDATOR.__dict__,
)


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


def promotion_fixture() -> tuple[str, str, str]:
    active = "\n".join(
        [
            "### L-0001 — Preserve review evidence when promoting a stable rule",
            "- **Why:** synthetic test fixture; no claim about project history.",
            "- **Review evidence:**",
            "  - `2026-10-01` — [fixture evidence](https://example.invalid/evidence/2026-10-01)",
            "  - `2026-10-02` — [fixture evidence](https://example.invalid/evidence/2026-10-02)",
            "  - `2026-10-03` — [fixture evidence](https://example.invalid/evidence/2026-10-03)",
            "- **Fix or follow-up:** synthetic fixture.",
            "- **Status:** active",
        ]
    )
    promoted = active.replace("- **Status:** active", "- **Status:** promoted") + "\n- **Promoted rule:** PS-0001\n- **Promotion date:** 2026-10-17"
    standard = "\n".join(
        [
            "##### PS-0001 — Preserve date-specific promotion evidence",
            "- **Scope:** synthetic writer regression fixture.",
            "- **Evidence lessons:** `L-0001`",
        ]
    )
    return active, promoted, standard


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

    def run_writer(
        self,
        archive_body: str = "Review body",
        lesson_body: str = "### Rule\n- **Why:** evidence\n- **Evidence:** commit\n- **Fix or follow-up:** done\n- **Seen 1×:** 2026-10-16\n- **Status:** active",
        archive: str = "docs/reviews/2026-10-16.md",
        promoted_lesson_body: str | None = None,
        promoted_standards_body: str | None = None,
    ) -> dict[str, str]:
        manifest_path, archive_path, lessons_path = write_inputs(
            self.inputs, self.manifest, archive_body, lesson_body
        )
        promoted_lessons_path = None
        promoted_standards_path = None
        if promoted_lesson_body is not None:
            promoted_lessons_path = self.inputs / "promoted-lessons.md"
            promoted_lessons_path.write_text(promoted_lesson_body, encoding="utf-8")
        if promoted_standards_body is not None:
            promoted_standards_path = self.inputs / "promoted-standards.md"
            promoted_standards_path.write_text(promoted_standards_body, encoding="utf-8")
        return WRITER.write_review(
            self.repo,
            manifest_path,
            archive,
            archive_path,
            lessons_path,
            promoted_lessons_path,
            promoted_standards_path,
        )

    def seed_active_lesson(self, active_body: str) -> str:
        prior_key = "sha256:" + "d" * 64
        document = self.lessons.read_text(encoding="utf-8")
        end_marker = "<!-- ACTIVE_LESSONS:END -->"
        block = (
            f"<!-- frozen-review-lessons: {prior_key} -->\n"
            f"{active_body}\n"
            f"<!-- /frozen-review-lessons: {prior_key} -->\n"
        )
        self.lessons.write_text(document.replace(end_marker, block + end_marker, 1), encoding="utf-8")
        return prior_key

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
                    "policy_version": 3,
                    "rules": [
                        {
                            "id": "review-records",
                            "kind": "path-glob",
                            "patterns": ["docs/reviews/**"],
                            "reason": "review records are excluded from code review ranges",
                        },
                        {
                            "id": "generated-data-paths",
                            "kind": "path-prefix",
                            "paths": ["data/generated"],
                            "producer": "ETL snapshot materializer",
                            "reason": "only this explicit generated-data directory is excluded",
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
        generated_dir = self.repo / "data/generated"
        generated_dir.mkdir(parents=True)
        (generated_dir / "snapshot.json").write_text('{"rows":3}\n', encoding="utf-8")
        (self.repo / "src").mkdir()
        (self.repo / "src/workflow.py").write_text("def run():\n    return True\n", encoding="utf-8")
        git(self.repo, "add", "LESSONS.md", "docs/reviews/excluded-input.md", "data/generated/snapshot.json", "src/workflow.py")
        git(self.repo, "commit", "-m", "advance range and add excluded data with workflow code")

        manifest = FREEZER.freeze_range(self.repo)
        self.assertEqual(manifest["from"], from_sha)
        self.assertEqual(manifest["exclusion_policy"]["policy_version"], 3)
        self.assertEqual(next(rule for rule in manifest["exclusion_policy"]["rules"] if rule["id"] == "generated-data-paths")["producer"], "ETL snapshot materializer")
        self.assertEqual(len(manifest["excluded_paths"]), 2)
        self.assertIn(manifest["through"], {item["sha"] for item in manifest["commits"]})
        excluded_paths = {record["path"] for record in manifest["excluded_paths"]}
        self.assertIn("data/generated/snapshot.json", excluded_paths)
        self.assertIn("docs/reviews/excluded-input.md", excluded_paths)
        self.assertNotIn("src/workflow.py", excluded_paths)
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

    def test_writer_loads_legacy_v2_and_v3_empty_and_populated_prefixes(self) -> None:
        for version, paths, producer in (
            (2, ["legacy/output"], None),
            (3, [], None),
            (3, [], "future stage; no paths approved"),
            (3, ["training/checkpoints"], "train.py writes checkpoint data after each epoch"),
        ):
            with self.subTest(version=version, paths=paths, producer=producer):
                manifest = make_manifest()
                rule = {"id": "output", "kind": "path-prefix", "paths": paths, "reason": "explicit decision"}
                if producer is not None:
                    rule["producer"] = producer
                manifest["exclusion_policy"]["policy_version"] = version
                manifest["exclusion_policy"]["rules"] = [rule]
                reseal_manifest(manifest)
                manifest_path, _, _ = write_inputs(self.inputs, manifest, "archive", "")
                self.assertEqual(WRITER.load_manifest(manifest_path), manifest)

    def test_writer_rejects_invalid_v3_producers_even_with_resealed_key(self) -> None:
        for paths in ([], ["training/checkpoints"]):
            for producer in (None, "", "  ", 7, [], {}):
                with self.subTest(paths=paths, producer=producer):
                    manifest = make_manifest()
                    manifest["exclusion_policy"]["policy_version"] = 3
                    manifest["exclusion_policy"]["rules"] = [{
                        "id": "output", "kind": "path-prefix", "paths": paths,
                        "producer": producer, "reason": "explicit decision",
                    }]
                    reseal_manifest(manifest)
                    manifest_path, _, _ = write_inputs(self.inputs, manifest, "archive", "")
                    with self.assertRaisesRegex(WRITER.WriterError, "producer"):
                        WRITER.load_manifest(manifest_path)
        manifest["exclusion_policy"]["rules"][0].pop("producer")
        reseal_manifest(manifest)
        manifest_path, _, _ = write_inputs(self.inputs, manifest, "archive", "")
        with self.assertRaisesRegex(WRITER.WriterError, "producer"):
            WRITER.load_manifest(manifest_path)

    def test_nested_manifest_schema_rejects_non_freezer_shapes_even_with_resealed_key(self) -> None:
        cases: list[tuple[str, dict[str, object]]] = []
        bad_commit = json.loads(json.dumps(self.manifest))
        bad_commit["commits"][0]["unexpected"] = "accepted by the old validator"
        cases.append(("commit record", bad_commit))
        bad_policy = json.loads(json.dumps(self.manifest))
        bad_policy["exclusion_policy"]["rules"] = {"not": "an array"}
        cases.append(("policy rules", bad_policy))
        bad_prefix = json.loads(json.dumps(self.manifest))
        bad_prefix["exclusion_policy"]["policy_version"] = 2
        bad_prefix["exclusion_policy"]["rules"] = [
            {
                "id": "generated-data-paths",
                "kind": "path-prefix",
                "paths": ["data/**"],
                "reason": "wildcards are not literal paths",
            }
        ]
        cases.append(("path-prefix policy", bad_prefix))
        bad_producer = json.loads(json.dumps(self.manifest))
        bad_producer["exclusion_policy"]["policy_version"] = 3
        bad_producer["exclusion_policy"]["rules"] = [{"id": "generated-data-paths", "kind": "path-prefix", "paths": ["data/generated"], "producer": "", "reason": "generated"}]
        cases.append(("empty producer", bad_producer))
        bad_exclusion = json.loads(json.dumps(self.manifest))
        bad_exclusion["excluded_paths"] = [{"unexpected": "record"}]
        cases.append(("excluded-path record", bad_exclusion))

        for index, (label, bad) in enumerate(cases):
            with self.subTest(label=label):
                reseal_manifest(bad)
                manifest_path, archive_path, lessons_path = write_inputs(
                    self.inputs, bad, f"bad-{index}", f"bad-{index}"
                )
                with self.assertRaisesRegex(WRITER.WriterError, "malformed|unexpected|rules|producer"):
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

    def test_promotion_moves_active_lesson_and_upserts_both_history_files_by_range_key(self) -> None:
        active_body, promoted_body, standard_body = promotion_fixture()
        prior_key = self.seed_active_lesson(active_body)
        standards_path = self.repo / "docs/code-standards.md"
        standards_path.parent.mkdir(parents=True)
        standards_path.write_text(
            "# Synthetic standards\n\n<!-- PROMOTED_RULES:START -->\n<!-- PROMOTED_RULES:END -->\n",
            encoding="utf-8",
        )

        self.run_writer(
            "promotion archive",
            "",
            promoted_lesson_body=promoted_body,
            promoted_standards_body=standard_body,
        )
        lessons = self.lessons.read_text(encoding="utf-8")
        active_section = lessons.split("<!-- ACTIVE_LESSONS:START -->", 1)[1].split("<!-- ACTIVE_LESSONS:END -->", 1)[0]
        promoted_section = lessons.split("<!-- PROMOTED_LESSONS:START -->", 1)[1].split("<!-- PROMOTED_LESSONS:END -->", 1)[0]
        standards = standards_path.read_text(encoding="utf-8")
        self.assertIn(prior_key, active_section)
        self.assertNotIn("L-0001", active_section)
        self.assertIn("L-0001", promoted_section)
        self.assertIn(self.manifest["range_key"], promoted_section)
        self.assertIn("PS-0001", standards)
        self.assertIn(self.manifest["range_key"], standards)
        self.assertEqual(PROMOTION_VALIDATOR.validate_documents(lessons, standards), [])

        self.run_writer(
            "promotion retry",
            "",
            promoted_lesson_body=promoted_body,
            promoted_standards_body=standard_body,
        )
        lessons = self.lessons.read_text(encoding="utf-8")
        standards = standards_path.read_text(encoding="utf-8")
        self.assertEqual(lessons.count(self.manifest["range_key"]), 5)
        self.assertEqual(standards.count(self.manifest["range_key"]), 2)
        self.assertEqual(PROMOTION_VALIDATOR.validate_documents(lessons, standards), [])

    def test_stale_active_body_retry_without_promotion_inputs_cannot_reintroduce_promoted_id(self) -> None:
        active_body, promoted_body, standard_body = promotion_fixture()
        self.seed_active_lesson(active_body)
        standards_path = self.repo / "docs/code-standards.md"
        standards_path.parent.mkdir(parents=True)
        standards_path.write_text(
            "# Synthetic standards\n<!-- PROMOTED_RULES:START -->\n<!-- PROMOTED_RULES:END -->\n",
            encoding="utf-8",
        )
        self.run_writer(
            "initial promotion",
            "",
            promoted_lesson_body=promoted_body,
            promoted_standards_body=standard_body,
        )
        archive_path = self.repo / "docs/reviews/2026-10-16.md"
        before = {
            "archive": archive_path.read_bytes(),
            "lessons": self.lessons.read_bytes(),
            "standards": standards_path.read_bytes(),
        }

        with self.assertRaisesRegex(WRITER.WriterError, "already promoted"):
            self.run_writer("stale active retry", active_body)

        self.assertEqual(archive_path.read_bytes(), before["archive"])
        self.assertEqual(self.lessons.read_bytes(), before["lessons"])
        self.assertEqual(standards_path.read_bytes(), before["standards"])

    def test_promotion_inputs_are_paired_and_require_an_existing_active_lesson(self) -> None:
        _active_body, promoted_body, _standard_body = promotion_fixture()
        manifest_path, archive_path, lessons_path = write_inputs(
            self.inputs, self.manifest, "review", ""
        )
        promoted_path = self.inputs / "promoted-lessons.md"
        promoted_path.write_text(promoted_body, encoding="utf-8")
        with self.assertRaisesRegex(WRITER.WriterError, "supplied together"):
            WRITER.write_review(
                self.repo,
                manifest_path,
                "docs/reviews/2026-10-16.md",
                archive_path,
                lessons_path,
                promoted_path,
            )
        self.assertFalse((self.repo / "docs").exists())

        standards_path = self.repo / "docs/code-standards.md"
        standards_path.parent.mkdir(parents=True)
        standards_path.write_text("<!-- PROMOTED_RULES:START -->\n<!-- PROMOTED_RULES:END -->\n", encoding="utf-8")
        standard_path = self.inputs / "promoted-standards.md"
        standard_path.write_text(promotion_fixture()[2], encoding="utf-8")
        with self.assertRaisesRegex(WRITER.WriterError, "first exist in active history"):
            WRITER.write_review(
                self.repo,
                manifest_path,
                "docs/reviews/2026-10-16.md",
                archive_path,
                lessons_path,
                promoted_path,
                standard_path,
            )
        self.assertFalse((self.repo / "docs/reviews/2026-10-16.md").exists())
        self.assertIn(f"reviewed-through: {FROM}", self.lessons.read_text(encoding="utf-8").splitlines()[0])

    def test_promotion_write_failure_keeps_watermark_and_same_key_retry_completes(self) -> None:
        active_body, promoted_body, standard_body = promotion_fixture()
        self.seed_active_lesson(active_body)
        standards_path = self.repo / "docs/code-standards.md"
        standards_path.parent.mkdir(parents=True)
        original_standards = "# Synthetic standards\n<!-- PROMOTED_RULES:START -->\n<!-- PROMOTED_RULES:END -->\n"
        standards_path.write_text(original_standards, encoding="utf-8")
        real_write = WRITER.atomic_write_at

        def fail_standards(directory_fd, name, content, description, expected_snapshot=None):
            if name == "code-standards.md":
                raise WRITER.WriterError("injected standards write failure")
            return real_write(directory_fd, name, content, description, expected_snapshot)

        with mock.patch.object(WRITER, "atomic_write_at", side_effect=fail_standards):
            with self.assertRaisesRegex(WRITER.WriterError, "injected standards"):
                self.run_writer(
                    "saved promotion archive",
                    "",
                    promoted_lesson_body=promoted_body,
                    promoted_standards_body=standard_body,
                )
        self.assertIn(f"reviewed-through: {FROM}", self.lessons.read_text(encoding="utf-8").splitlines()[0])
        self.assertIn("L-0001", self.lessons.read_text(encoding="utf-8"))
        self.assertEqual(standards_path.read_text(encoding="utf-8"), original_standards)
        self.assertTrue((self.repo / "docs/reviews/2026-10-16.md").exists())

        self.run_writer(
            "saved promotion archive",
            "",
            promoted_lesson_body=promoted_body,
            promoted_standards_body=standard_body,
        )
        self.assertIn(f"reviewed-through: {THROUGH}", self.lessons.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(
            PROMOTION_VALIDATOR.validate_documents(
                self.lessons.read_text(encoding="utf-8"),
                standards_path.read_text(encoding="utf-8"),
            ),
            [],
        )

    def test_promotion_does_not_follow_code_standards_symlink(self) -> None:
        active_body, promoted_body, standard_body = promotion_fixture()
        self.seed_active_lesson(active_body)
        docs = self.repo / "docs"
        docs.mkdir()
        outside = self.root / "outside-standards.md"
        outside.write_text("outside remains unchanged\n", encoding="utf-8")
        os.symlink(outside, docs / "code-standards.md")
        with self.assertRaisesRegex(WRITER.WriterError, "without following links"):
            self.run_writer(
                "review",
                "",
                promoted_lesson_body=promoted_body,
                promoted_standards_body=standard_body,
            )
        self.assertEqual(outside.read_text(encoding="utf-8"), "outside remains unchanged\n")
        self.assertFalse((self.repo / "docs/reviews/2026-10-16.md").exists())

    def test_duplicate_promotion_marker_outside_standards_block_fails_before_writes(self) -> None:
        active_body, promoted_body, standard_body = promotion_fixture()
        self.seed_active_lesson(active_body)
        standards_path = self.repo / "docs/code-standards.md"
        standards_path.parent.mkdir(parents=True)
        key = self.manifest["range_key"]
        standards_path.write_text(
            f"<!-- frozen-review-standard: {key} -->\nunscoped duplicate\n"
            f"<!-- /frozen-review-standard: {key} -->\n"
            "<!-- PROMOTED_RULES:START -->\n<!-- PROMOTED_RULES:END -->\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(WRITER.WriterError, "could not be verified"):
            self.run_writer(
                "review",
                "",
                promoted_lesson_body=promoted_body,
                promoted_standards_body=standard_body,
            )
        self.assertFalse((self.repo / "docs/reviews/2026-10-16.md").exists())
        self.assertIn(f"reviewed-through: {FROM}", self.lessons.read_text(encoding="utf-8").splitlines()[0])
        self.assertIn("unscoped duplicate", standards_path.read_text(encoding="utf-8"))

    def test_promotion_retry_recovers_if_standards_wrote_before_lessons_failure(self) -> None:
        active_body, promoted_body, standard_body = promotion_fixture()
        self.seed_active_lesson(active_body)
        standards_path = self.repo / "docs/code-standards.md"
        standards_path.parent.mkdir(parents=True)
        standards_path.write_text(
            "# Synthetic standards\n<!-- PROMOTED_RULES:START -->\n<!-- PROMOTED_RULES:END -->\n",
            encoding="utf-8",
        )
        real_write = WRITER.atomic_write_at

        def fail_lessons(directory_fd, name, content, description, expected_snapshot=None):
            if name == "LESSONS.md":
                raise WRITER.WriterError("injected Lessons write failure")
            return real_write(directory_fd, name, content, description, expected_snapshot)

        with mock.patch.object(WRITER, "atomic_write_at", side_effect=fail_lessons):
            with self.assertRaisesRegex(WRITER.WriterError, "injected Lessons"):
                self.run_writer(
                    "promotion archive",
                    "",
                    promoted_lesson_body=promoted_body,
                    promoted_standards_body=standard_body,
                )

        lessons = self.lessons.read_text(encoding="utf-8")
        standards = standards_path.read_text(encoding="utf-8")
        active_section = lessons.split("<!-- ACTIVE_LESSONS:START -->", 1)[1].split("<!-- ACTIVE_LESSONS:END -->", 1)[0]
        self.assertIn("L-0001", active_section)
        self.assertIn("PS-0001", standards)
        self.assertIn(f"reviewed-through: {FROM}", lessons.splitlines()[0])

        self.run_writer(
            "promotion archive",
            "",
            promoted_lesson_body=promoted_body,
            promoted_standards_body=standard_body,
        )
        self.assertEqual(
            PROMOTION_VALIDATOR.validate_documents(
                self.lessons.read_text(encoding="utf-8"),
                standards_path.read_text(encoding="utf-8"),
            ),
            [],
        )
        self.assertIn(f"reviewed-through: {THROUGH}", self.lessons.read_text(encoding="utf-8").splitlines()[0])

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

    def test_cross_date_same_body_merges_evidence_and_advances_watermark(self) -> None:
        lesson = "\n".join(
            [
                "### L-0001 — Preserve evidence across review dates",
                "- **Why:** synthetic end-to-end regression fixture.",
                "- **Review evidence:**",
                "  - `2026-10-16` — [first-day evidence](https://example.invalid/evidence/first-day)",
                "- **Fix or follow-up:** synthetic fixture.",
                "- **Status:** active",
            ]
        )
        self.run_writer(
            "first-day archive",
            lesson,
            archive="docs/reviews/2026-10-16.md",
        )
        first_through = self.manifest["through"]
        second_day_lesson = lesson.replace(
            "  - `2026-10-16` — [first-day evidence](https://example.invalid/evidence/first-day)",
            "  - `2026-10-16` — [first-day evidence](https://example.invalid/evidence/first-day)\n"
            "  - `2026-10-17` — [second-day evidence](https://example.invalid/evidence/second-day)",
        )
        second_manifest = make_manifest(from_sha=first_through, through="f" * 40)
        second_manifest_path, second_archive_input, second_lessons_input = write_inputs(
            self.inputs, second_manifest, "second-day archive", second_day_lesson
        )

        WRITER.write_review(
            self.repo,
            second_manifest_path,
            "docs/reviews/2026-10-17.md",
            second_archive_input,
            second_lessons_input,
        )
        lessons = self.lessons.read_text(encoding="utf-8")
        self.assertIn(f"reviewed-through: {'f' * 40}", lessons.splitlines()[0])
        self.assertEqual(lessons.count("### L-0001"), 1)
        self.assertIn("first-day evidence", lessons)
        self.assertIn("second-day evidence", lessons)
        self.assertIn("second-day archive", (self.repo / "docs/reviews/2026-10-17.md").read_text(encoding="utf-8"))

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
        with self.assertRaisesRegex(WRITER.WriterError, "ask a maintainer to choose the first target-branch commit"):
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

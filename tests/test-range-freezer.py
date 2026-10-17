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


def git_object_snapshot(repo: Path) -> dict[Path, tuple[int, int, str]]:
    snapshot: dict[Path, tuple[int, int, str]] = {}
    for path in (repo / ".git" / "objects").rglob("*"):
        if path.is_file():
            info = path.stat()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            snapshot[path] = (info.st_size, info.st_mtime_ns, digest)
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
            ("<!-- reviewed-through: UNKNOWN (bootstrap) -->\n# Lessons\n", "reviewed-through is UNKNOWN"),
            (f"<!-- reviewed-through: {self.anchor[:8]} -->\n# Lessons\n", "full 40-character"),
            (f"<!-- reviewed-through: {'f' * 40} -->\n# Lessons\n", "does not resolve"),
            (f"prefix <!-- reviewed-through: {self.anchor} --> trailing\n# Lessons\n", "first line"),
            (f"<!-- reviewed-through: {self.anchor} -->\r\n# Lessons\r\n", None),
            (
                f"<!-- reviewed-through: {self.anchor} -->\n"
                f"<!-- reviewed-through: {self.anchor} -->\n# Lessons\n",
                "exactly one",
            ),
        ]
        for data, expected in cases:
            with self.subTest(watermark=data.splitlines()[0]):
                lessons.write_text(data, encoding="utf-8")
                if expected is None:
                    completed = invoke(self.repo)
                    self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors="replace"))
                else:
                    self.assert_cli_failure(self.repo, expected)
        lessons.write_text(original, encoding="utf-8")

    def test_exclusions_are_explicit_and_rule_changes_affect_key(self) -> None:
        generated = self.repo / "dist" / "generated.js"
        generated.parent.mkdir()
        generated.write_text("generated output\n", encoding="utf-8")
        (self.repo / "image.bin").write_bytes(b"\x89PNG\x00binary\x01")
        (self.repo / "application.sqlite").write_bytes(b"SQLite format 3\x00" + b"\x01\x00" * 32)
        through = commit(self.repo, "add generated and binary files")

        manifest = FREEZER.freeze_range(self.repo)
        self.assertEqual(manifest["through"], through)
        self.assertIn(through, {item["sha"] for item in manifest["commits"]})
        by_path: dict[str, set[str]] = {}
        for item in manifest["excluded_paths"]:
            by_path.setdefault(item["path"], set()).add(item["rule_id"])
        self.assertIn("generated-output", by_path["dist/generated.js"])
        self.assertIn("binary-nul-content", by_path["image.bin"])
        self.assertIn("binary-nul-content", by_path["application.sqlite"])
        generated_policy_rule = next(rule for rule in manifest["exclusion_policy"]["rules"] if rule["id"] == "generated-data-paths")
        self.assertNotIn("producer", generated_policy_rule)
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

    def test_default_generated_data_paths_are_empty_and_do_not_guess(self) -> None:
        policy_version, rules = FREEZER.parse_policy(POLICY_SOURCE.read_bytes())
        self.assertEqual(policy_version, 3)
        generated_rule = next(rule for rule in rules if rule["id"] == "generated-data-paths")
        self.assertEqual(generated_rule["paths"], [])

        snapshot = self.repo / "automation" / "pulls" / "daily-snapshot.json"
        snapshot.parent.mkdir(parents=True)
        snapshot.write_text('{"generated":true}\n', encoding="utf-8")
        unconfigured = ["training/checkpoints/step-10.json", "etl/staging/batch.csv", "new-output/result.txt"]
        for relative in unconfigured:
            target = self.repo / relative
            target.parent.mkdir(parents=True)
            target.write_text("unconfigured data\n", encoding="utf-8")
        commit(self.repo, "add an unconfigured automation snapshot")
        manifest = FREEZER.freeze_range(self.repo)
        self.assertTrue(set(unconfigured).isdisjoint(record["path"] for record in manifest["excluded_paths"]))
        self.assertNotIn(
            "automation/pulls/daily-snapshot.json",
            {record["path"] for record in manifest["excluded_paths"]},
        )

    def test_explicit_generated_data_prefix_skips_only_that_path_and_keeps_mixed_commit(self) -> None:
        policy_path = self.repo / "docs" / "automation" / "range-exclusions.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        generated_rule = next(rule for rule in policy["rules"] if rule["id"] == "generated-data-paths")
        generated_rule["paths"] = ["automation/generated-data"]
        generated_rule["producer"] = "ETL pipeline materializes daily snapshots"
        policy_path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")
        commit(self.repo, "configure an explicit generated-data path")

        snapshot = self.repo / "automation" / "generated-data" / "snapshot.json"
        snapshot.parent.mkdir(parents=True)
        snapshot.write_text('{"count":7}\n', encoding="utf-8")
        sibling = self.repo / "automation" / "generated-data-archive" / "sibling.json"
        sibling.parent.mkdir(parents=True)
        sibling.write_text('{"keep":true}\n', encoding="utf-8")
        nested = self.repo / "automation" / "generated-data" / "nested" / "generated-data" / "same-name.json"
        nested.parent.mkdir(parents=True)
        nested.write_text("nested\n", encoding="utf-8")
        outside = self.repo / "other" / "automation" / "generated-data" / "same-name.json"
        outside.parent.mkdir(parents=True)
        outside.write_text("must remain reviewable\n", encoding="utf-8")
        workflow = self.repo / ".github" / "workflows" / "produce.yml"
        workflow.parent.mkdir(parents=True)
        workflow.write_text("name: Producer\n", encoding="utf-8")
        code = self.repo / "src" / "workflow.py"
        code.parent.mkdir(parents=True)
        code.write_text("def run():\n    return True\n", encoding="utf-8")
        config = self.repo / "config" / "review.toml"
        config.parent.mkdir(parents=True)
        config.write_text("enabled = true\n", encoding="utf-8")
        through = commit(self.repo, "update workflow and generated snapshot")

        manifest = FREEZER.freeze_range(self.repo)
        self.assertIn(through, {item["sha"] for item in manifest["commits"]})
        excluded = [
            record
            for record in manifest["excluded_paths"]
            if record["commit"] == through and record["path"] == "automation/generated-data/snapshot.json"
        ]
        self.assertEqual(len(excluded), 1)
        self.assertEqual(excluded[0]["rule_id"], "generated-data-paths")
        self.assertEqual(excluded[0]["match"], {"path_prefix": "automation/generated-data"})
        self.assertEqual(excluded[0]["reason"], generated_rule["reason"])
        self.assertTrue({outside.relative_to(self.repo).as_posix(), workflow.relative_to(self.repo).as_posix()}.isdisjoint(
            record["path"] for record in manifest["excluded_paths"] if record["commit"] == through
        ))
        self.assertIn(
            "automation/generated-data/nested/generated-data/same-name.json",
            {record["path"] for record in manifest["excluded_paths"] if record["commit"] == through},
        )
        self.assertNotIn(
            "automation/generated-data-archive/sibling.json",
            {record["path"] for record in manifest["excluded_paths"] if record["commit"] == through},
        )
        self.assertNotIn(
            "src/workflow.py",
            {record["path"] for record in manifest["excluded_paths"] if record["commit"] == through},
        )
        self.assertNotIn(
            "config/review.toml",
            {record["path"] for record in manifest["excluded_paths"] if record["commit"] == through},
        )

    def test_explicit_path_prefix_rejects_wildcards_and_v1_remains_supported(self) -> None:
        version, rules = FREEZER.parse_policy(
            json.dumps(
                {
                    "policy_version": 1,
                    "rules": [
                        {
                            "id": "legacy-glob",
                            "kind": "path-glob",
                            "patterns": ["docs/reviews/**"],
                            "reason": "legacy schema fixture",
                        }
                    ],
                }
            ).encode("utf-8")
        )
        self.assertEqual(version, 1)
        self.assertEqual(rules[0]["kind"], "path-glob")

        invalid = {
            "policy_version": 2,
            "rules": [
                {
                    "id": "generated-data-paths",
                    "kind": "path-prefix",
                    "paths": ["automation/**"],
                    "reason": "wildcards are not explicit paths",
                }
            ],
        }
        with self.assertRaisesRegex(FREEZER.FreezeError, "wildcard characters are not allowed"):
            FREEZER.parse_policy(json.dumps(invalid).encode("utf-8"))

    def test_v3_producers_are_free_text_and_normalized_into_manifest_rules(self) -> None:
        producers = ["training job", "stage-2 materializer", "ETL flow", "runtime cache warmer", "new process type"]
        for producer in producers:
            with self.subTest(producer=producer):
                version, rules = FREEZER.parse_policy(json.dumps({
                    "policy_version": 3,
                    "rules": [{"id": "generated-data-paths", "kind": "path-prefix",
                               "paths": ["outputs/model"], "producer": producer, "reason": "fixture reason"}],
                }).encode())
                self.assertEqual(version, 3)
                self.assertEqual(rules[0]["producer"], producer)
        _, empty_rules = FREEZER.parse_policy(json.dumps({
            "policy_version": 3,
            "rules": [{"id": "generated-data-paths", "kind": "path-prefix", "paths": [], "reason": "no paths configured"}],
        }).encode())
        self.assertNotIn("producer", empty_rules[0])

    def test_v2_populated_prefix_remains_compatible_without_invented_producer(self) -> None:
        policy = {"policy_version": 2, "rules": [{
            "id": "legacy-data", "kind": "path-prefix", "paths": ["legacy/output"], "reason": "legacy decision",
        }]}
        self.assertEqual(FREEZER.parse_policy(json.dumps(policy).encode()), (2, policy["rules"]))
        policy["rules"][0]["producer"] = "not part of the legacy schema"
        with self.assertRaisesRegex(FREEZER.FreezeError, "unexpected"):
            FREEZER.parse_policy(json.dumps(policy).encode())

    def test_v3_exact_file_prefix_and_unused_producer_bind_range_key(self) -> None:
        policy_path = self.repo / "docs/automation/range-exclusions.json"
        policy = {"policy_version": 3, "rules": [{
            "id": "training-output", "kind": "path-prefix", "paths": ["training/checkpoint.json"],
            "producer": "train.py writes a checkpoint at the end of each epoch", "reason": "skip only checkpoint data",
        }, {
            "id": "future-process", "kind": "path-prefix", "paths": [],
            "producer": "reserved stage-3 materializer; no paths approved", "reason": "no exclusions yet",
        }]}
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        for relative in ("training/checkpoint.json", "training/checkpoint.json.bak", "other/training/checkpoint.json"):
            target = self.repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("data\n", encoding="utf-8")
        through = commit(self.repo, "add explicitly selected training artifact and siblings")
        manifest = FREEZER.freeze_range(self.repo)
        self.assertIn(through, {item["sha"] for item in manifest["commits"]})
        self.assertEqual([item["path"] for item in manifest["excluded_paths"]], ["training/checkpoint.json"])
        self.assertEqual(manifest["exclusion_policy"]["rules"], policy["rules"])
        self.assertEqual(manifest["excluded_paths"][0]["reason"], "skip only checkpoint data")
        for index in (0, 1):
            altered = json.loads(json.dumps(manifest))
            altered["exclusion_policy"]["rules"][index]["producer"] += " revised source"
            payload = {key: value for key, value in altered.items() if key != "range_key"}
            self.assertNotEqual(FREEZER.add_range_key(payload)["range_key"], manifest["range_key"])

    def test_documented_v3_example_uses_the_real_parser(self) -> None:
        contract = (REPO_ROOT / "docs/automation/runner-contract.md").read_text(encoding="utf-8")
        example = contract.split("```json\n", 1)[1].split("```", 1)[0]
        version, rules = FREEZER.parse_policy(example.encode("utf-8"))
        self.assertEqual(version, 3)
        self.assertTrue(all(rule["producer"].strip() for rule in rules))

    def test_v3_policy_rejects_invalid_producer_and_extra_field_shapes(self) -> None:
        cases = [
            ({"id": "r", "kind": "path-prefix", "paths": ["out"], "reason": "why"}, "producer"),
            ({"id": "r", "kind": "path-prefix", "paths": ["out"], "producer": "", "reason": "why"}, "producer"),
            ({"id": "r", "kind": "path-prefix", "paths": ["out"], "producer": 7, "reason": "why"}, "producer"),
            ({"id": "r", "kind": "path-glob", "patterns": ["out/**"], "producer": "tool", "reason": "why"}, "unexpected"),
            ({"id": "r", "kind": "binary-nul-byte", "producer": "tool", "reason": "why"}, "unexpected"),
        ]
        for paths in ([], ["out"]):
            for producer in (None, "   ", [], {}):
                cases.append(({"id": "r", "kind": "path-prefix", "paths": paths, "producer": producer, "reason": "why"}, "producer"))
        for rule, message in cases:
            with self.subTest(rule=rule):
                with self.assertRaisesRegex(FREEZER.FreezeError, message):
                    FREEZER.parse_policy(json.dumps({"policy_version": 3, "rules": [rule]}).encode())

    def test_v3_path_and_reason_boundary_matrix_is_rejected(self) -> None:
        invalid_paths = ["", "/absolute", "../parent", "a/../b", "a/./b", "a//b", "a/", "a\\b", "a\x00b", "a*b", "a?b"]
        for path in invalid_paths:
            with self.subTest(path=repr(path)):
                rule = {"id": "r", "kind": "path-prefix", "paths": [path], "producer": "process", "reason": "why"}
                with self.assertRaises(FREEZER.FreezeError):
                    FREEZER.parse_policy(json.dumps({"policy_version": 3, "rules": [rule]}).encode())
        duplicate = {"id": "r", "kind": "path-prefix", "paths": ["out", "out"], "producer": "process", "reason": "why"}
        with self.assertRaises(FREEZER.FreezeError):
            FREEZER.parse_policy(json.dumps({"policy_version": 3, "rules": [duplicate]}).encode())
        for reason in (None, "", "   ", 4):
            with self.subTest(reason=repr(reason)):
                rule = {"id": "r", "kind": "path-prefix", "paths": [], "reason": reason}
                with self.assertRaises(FREEZER.FreezeError):
                    FREEZER.parse_policy(json.dumps({"policy_version": 3, "rules": [rule]}).encode())
        with self.assertRaisesRegex(FREEZER.FreezeError, "missing fields"):
            FREEZER.parse_policy(b'{"policy_version":3,"rules":[{"id":"r","kind":"path-prefix","paths":[]}]}')
        for kind in ([], {}):
            with self.subTest(kind=repr(kind)):
                rule = {"id": "r", "kind": kind, "reason": "why"}
                with self.assertRaises(FREEZER.FreezeError):
                    FREEZER.parse_policy(json.dumps({"policy_version": 3, "rules": [rule]}).encode())
        for raw in (
            '{"policy_version":3,"rules":[],"rules":[]}',
            '{"policy_version":true,"rules":[]}',
            '{"policy_version":3,"rules": [{"id":"r","kind":"path-prefix","paths":[],"reason":"why","extra":1}]}',
        ):
            with self.subTest(raw=raw):
                with self.assertRaises(FREEZER.FreezeError):
                    FREEZER.parse_policy(raw.encode())

    def test_validate_policy_cli_is_git_independent_and_silent(self) -> None:
        policy = self.temp_path / "standalone-policy.json"
        policy.write_text(json.dumps({"policy_version": 3, "rules": [{"id": "r", "kind": "path-prefix", "paths": [], "reason": "fixture"}]}), encoding="utf-8")
        good = subprocess.run([sys.executable, str(RUNNER), "--validate-policy", str(policy)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        self.assertEqual(good.returncode, 0, good.stderr.decode())
        self.assertEqual(good.stdout, b"")
        malformed = policy.read_bytes()
        policy.write_text('{"policy_version":3,"rules":[{"id":"r","kind":"path-prefix","paths":["out"],"reason":"missing producer"}]}', encoding="utf-8")
        before_bad = policy.read_bytes()
        bad = subprocess.run([sys.executable, str(RUNNER), "--validate-policy", str(policy)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        self.assertNotEqual(bad.returncode, 0)
        self.assertEqual(bad.stdout, b"")
        self.assertEqual(policy.read_bytes(), before_bad)
        self.assertNotEqual(before_bad, malformed)
        conflict = subprocess.run([sys.executable, str(RUNNER), "--repo", str(self.repo), "--validate-policy", str(policy)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        self.assertNotEqual(conflict.returncode, 0)
        self.assertEqual(conflict.stdout, b"")

    def test_policy_rejects_isolated_surrogate_before_freeze_serialization(self) -> None:
        policy = self.temp_path / "surrogate-policy.json"
        policy.write_bytes(
            b'{"policy_version":3,"rules":[{"id":"r","kind":"path-prefix",'
            b'"paths":[],"reason":"bad\\ud800"}]}'
        )
        validation = subprocess.run(
            [sys.executable, str(RUNNER), "--validate-policy", str(policy)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertNotEqual(validation.returncode, 0)
        self.assertEqual(validation.stdout, b"")

        bad_policy = self.repo / "docs" / "automation" / "range-exclusions.json"
        bad_policy.write_bytes(policy.read_bytes())
        commit(self.repo, "add policy with isolated surrogate escape")
        frozen = invoke(self.repo)
        self.assertNotEqual(frozen.returncode, 0)
        self.assertEqual(frozen.stdout, b"")
        self.assertIn("UTF-8", frozen.stderr.decode("utf-8", errors="replace"))

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
            {"generated-output", "generated-data-paths", "binary-nul-content", "gitlink-submodule"},
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

    def test_runner_never_writes_lessons_reviews_or_git_objects(self) -> None:
        lessons = self.repo / "LESSONS.md"
        policy = self.repo / "docs" / "automation" / "range-exclusions.json"
        review_dir = self.repo / "docs" / "reviews"
        keep = review_dir / "keep.md"
        lessons_bytes = lessons.read_bytes()
        policy_bytes = policy.read_bytes()
        keep_bytes = keep.read_bytes()
        before_review_dir = review_dir.stat()
        self.assertIn(self.anchor.encode("ascii"), lessons_bytes)
        self.assertNotIn(b"UNKNOWN", lessons_bytes)

        old_atime_ns = 1_000_000_000
        for path in (lessons, policy):
            info = path.stat()
            os.utime(path, ns=(old_atime_ns, info.st_mtime_ns))
        git_objects = [
            path
            for path in (self.repo / ".git" / "objects").rglob("*")
            if path.is_file()
        ]
        object_snapshot = git_object_snapshot(self.repo)
        for path in git_objects:
            info = path.stat()
            os.utime(path, ns=(old_atime_ns, info.st_mtime_ns))
        lessons_atime = lessons.stat().st_atime_ns
        policy_atime = policy.stat().st_atime_ns
        before_tree = path_snapshot(self.repo)

        completed = invoke(self.repo)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors="replace"))
        output = json.loads(completed.stdout)
        self.assertIn("range_key", output)

        self.assertEqual(path_snapshot(self.repo), before_tree)
        self.assertEqual(git_object_snapshot(self.repo), object_snapshot)
        self.assertEqual(lessons.stat().st_atime_ns, lessons_atime)
        self.assertEqual(policy.stat().st_atime_ns, policy_atime)
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

    def test_runner_does_not_write_packed_git_objects(self) -> None:
        git(self.repo, "gc", "--prune=now")
        packed_files = [
            path
            for path in (self.repo / ".git" / "objects").rglob("*")
            if path.is_file()
        ]
        self.assertTrue(any(path.suffix == ".pack" for path in packed_files))
        before = git_object_snapshot(self.repo)

        completed = invoke(self.repo)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors="replace"))
        self.assertEqual(git_object_snapshot(self.repo), before)

    def test_failure_does_not_emit_partial_manifest(self) -> None:
        lessons = self.repo / "LESSONS.md"
        lessons.write_text("<!-- reviewed-through: UNKNOWN -->\n# Lessons\n", encoding="utf-8")
        self.assert_cli_failure(self.repo, "ask a maintainer to choose the first target-branch commit")
        self.assertEqual(lessons.read_text(encoding="utf-8").splitlines()[0], "<!-- reviewed-through: UNKNOWN -->")


if __name__ == "__main__":
    unittest.main(verbosity=2)

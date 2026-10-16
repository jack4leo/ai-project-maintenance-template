#!/usr/bin/env python3
"""Synthetic tests for the persisted Lesson-promotion schema gate."""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.dont_write_bytecode = True
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from validate_lesson_promotions import validate_documents  # noqa: E402


LESSON_START = "<!-- ACTIVE_LESSONS:START -->"
LESSON_END = "<!-- ACTIVE_LESSONS:END -->"
PROMOTED_START = "<!-- PROMOTED_LESSONS:START -->"
PROMOTED_END = "<!-- PROMOTED_LESSONS:END -->"
RULE_START = "<!-- PROMOTED_RULES:START -->"
RULE_END = "<!-- PROMOTED_RULES:END -->"


def lesson_record(
    lesson_id: str = "L-0001",
    *,
    dates: tuple[str, ...] = ("2026-01-02", "2026-01-03", "2026-01-04"),
    status: str = "promoted",
    rule_id: str | None = "PS-0001",
    promotion_date: str = "2026-01-05",
    include_evidence_field: bool = True,
) -> str:
    lines = [
        f"### {lesson_id} — Synthetic executable rule",
        "- **Why:** Synthetic test-only fixture; not a claim about repository history.",
    ]
    if include_evidence_field:
        lines.append("- **Review evidence:**")
        lines.extend(
            f"  - `{date}` — [synthetic fixture evidence](https://example.invalid/evidence/{date})"
            for date in dates
        )
    lines.append(f"- **Status:** {status}")
    if rule_id:
        lines.append(f"- **Promoted rule:** {rule_id}")
    if promotion_date:
        lines.append(f"- **Promotion date:** {promotion_date}")
    return "\n".join(lines)


def lessons_document(active: tuple[str, ...] = (), promoted: tuple[str, ...] = ()) -> str:
    return "\n".join(
        [
            "# Synthetic Lessons",
            LESSON_START,
            *active,
            LESSON_END,
            PROMOTED_START,
            *promoted,
            PROMOTED_END,
        ]
    )


def standards_document(
    lesson_ids: tuple[str, ...] = ("L-0001",),
    rule_ids: tuple[str, ...] = ("PS-0001",),
) -> str:
    lines = ["# Synthetic standards", RULE_START]
    for rule_id in rule_ids:
        lines.extend(
            [
                f"##### {rule_id} — Synthetic executable standard",
                "- **Scope:** Synthetic test-only fixture.",
                "- **Evidence lessons:** " + ", ".join(f"`{lesson_id}`" for lesson_id in lesson_ids),
            ]
        )
    lines.append(RULE_END)
    return "\n".join(lines)


class LessonPromotionTests(unittest.TestCase):
    def test_valid_promoted_rule_with_three_distinct_review_dates_passes(self):
        errors = validate_documents(
            lessons_document(promoted=(lesson_record(),)), standards_document()
        )
        self.assertEqual(errors, [])

    def test_lesson_ids_must_be_unique_across_both_lesson_blocks(self):
        errors = validate_documents(
            lessons_document(
                active=(lesson_record(status="active", rule_id=None, promotion_date=""),),
                promoted=(lesson_record(),),
            ),
            standards_document(),
        )
        self.assertTrue(any("duplicate Lesson ID L-0001" in error for error in errors), errors)

    def test_rule_reference_to_missing_lesson_is_rejected(self):
        errors = validate_documents(
            lessons_document(), standards_document(lesson_ids=("L-9999",))
        )
        self.assertTrue(any("unknown Lesson ID L-9999" in error for error in errors), errors)

    def test_fewer_than_three_distinct_review_dates_fails(self):
        errors = validate_documents(
            lessons_document(promoted=(lesson_record(dates=("2026-01-02", "2026-01-03")),)),
            standards_document(),
        )
        self.assertTrue(any("requires at least 3 distinct review-evidence dates; found 2" in error for error in errors), errors)

    def test_repeating_one_review_date_does_not_meet_the_threshold(self):
        errors = validate_documents(
            lessons_document(
                promoted=(lesson_record(dates=("2026-01-02", "2026-01-02", "2026-01-02")),)
            ),
            standards_document(),
        )
        self.assertTrue(any("requires at least 3 distinct review-evidence dates; found 1" in error for error in errors), errors)

    def test_legacy_seen_and_generic_evidence_cannot_fake_structured_dates(self):
        legacy = "\n".join(
            [
                "### L-0001 — Legacy rule with unstructured counts",
                "- **Why:** Legacy fixture only.",
                "- **Evidence:** [one old PR](https://example.invalid/legacy)",
                "- **Seen N×:** 2024-01-01, 2024-01-02, 2024-01-03",
                "- **Status:** promoted",
                "- **Promoted rule:** PS-0001",
                "- **Promotion date:** 2024-01-04",
            ]
        )
        errors = validate_documents(
            lessons_document(promoted=(legacy,)), standards_document()
        )
        self.assertTrue(any("legacy Evidence/Seen fields do not count" in error for error in errors), errors)
        self.assertTrue(any("found 0" in error for error in errors), errors)

    def test_promotion_date_does_not_count_as_review_evidence(self):
        errors = validate_documents(
            lessons_document(
                promoted=(lesson_record(dates=("2026-01-02", "2026-01-03"), promotion_date="2026-01-04"),)
            ),
            standards_document(),
        )
        self.assertTrue(any("found 2" in error for error in errors), errors)

    def test_active_lesson_cannot_be_cited_as_promoted_evidence(self):
        errors = validate_documents(
            lessons_document(
                active=(lesson_record(status="active", rule_id=None, promotion_date=""),)
            ),
            standards_document(),
        )
        self.assertTrue(any("is not in promoted status" in error for error in errors), errors)

    def test_invalid_calendar_date_is_rejected(self):
        errors = validate_documents(
            lessons_document(promoted=(lesson_record(dates=("2026-02-30",)),)),
            standards_document(),
        )
        self.assertTrue(any("invalid review date '2026-02-30'" in error for error in errors), errors)

    def test_promoted_rule_ids_must_be_unique(self):
        first = lesson_record(lesson_id="L-0001", rule_id="PS-0001")
        second = lesson_record(lesson_id="L-0002", rule_id="PS-0002")
        rules = standards_document(
            lesson_ids=("L-0001",), rule_ids=("PS-0001", "PS-0001")
        )
        errors = validate_documents(
            lessons_document(promoted=(first, second)), rules
        )
        self.assertTrue(any("duplicate promoted-rule ID PS-0001" in error for error in errors), errors)

    def test_each_review_date_requires_a_markdown_citation(self):
        uncited = lesson_record().replace(
            "[synthetic fixture evidence](https://example.invalid/evidence/2026-01-02)",
            "uncited legacy text",
            1,
        )
        errors = validate_documents(
            lessons_document(promoted=(uncited,)), standards_document()
        )
        self.assertTrue(any("requires a non-placeholder Markdown link" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)

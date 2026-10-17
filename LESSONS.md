<!-- reviewed-through: UNKNOWN (bootstrap the project before using this watermark) -->
# Project Lessons and Retrospectives (Lessons)

This is the target project's living incident and learning log, not a collection of generic examples. Except for the maintenance protocol defined in this file, every entry must come from commits, issues/PRs, CI output, reproduction records, or verifiable maintainer feedback inspected for this project; do not copy specific technical rules from templates or other projects.

## Maintenance protocol

- Daily review scope: run `scripts/freeze-review-range.py` and use its canonical manifest as the sole range authority; do not calculate the range from this marker or a later HEAD. If the marker is `UNKNOWN`, stop and ask a maintainer to choose the first target-branch commit to include; because the boundary is exclusive, use that commit's target-branch parent (the target-branch/first parent for a merge). Do not infer or auto-initialize this starting boundary; after explicit establishment, only the normal completed-review writer advances it to `through`. Review every commit in the manifest, but skip only the contents of each commit/parent/path recorded in `excluded_paths`; exclusions do not remove commits or their other paths. Record excluded paths and reasons in the archive. The `generated-data-paths` rule accepts only explicit literal paths and defaults empty; do not guess a target project's generated-data locations.
- Focus on errors in development, code review (CR), merge/release, and verification: **fixed and then reworked**, **merged/released when they should not have been**, and **insufficient validation or an untrusted validation baseline**. Do not review contents of generated-data snapshots excluded by the frozen manifest as Lessons, regardless of whether they came from training, an intermediate stage, ETL, a script, runtime behavior, or another generation process. A workflow or generated-data anomaly may be recorded as an automation-health/verification issue only with independent workflow, CI, validator, or similar evidence. Also record `Done right` to preserve effective practices.
- Write rules as short, executable constraints for next time; include the incident cause, impact, fix/follow-up action, and evidence links. When evidence is insufficient, phrase it as an open question, not as a confirmed causal claim.
- Count recurrence by **distinct completed review dates** on which the lesson appeared. Multiple commits or repeated events on the same day count as one day; do not inflate the count through repeated edits or by splitting a review.
- By default, only after a generalized stable rule has appeared independently in reviews on **at least 3 different dates** may it be promoted to the project-specific section of [`docs/code-standards.md`](docs/code-standards.md). During promotion, move the complete lesson record to promotion history, preserve its ID, dates, and citations, and note the promoted rule ID; do not lose the source.
- For a serious one-time security, data-loss, or release incident, an agent may immediately propose a temporary safeguard. Mark the proposal `Temporary rule / pending maintainer confirmation`; this does not count as a three-day promotion or authorize an unapproved product policy.
- After updating a rule, check AGENTS routing, relevant subsystem pages, tests, and other entry points for conflicts; keep one authoritative definition and do not duplicate it by copy-paste.
- Even when nothing is found that day, archive the frozen scope, excluded-path summary, sources checked, and “no new evidence-backed lesson”. Do not directly edit this file or advance the marker during a review; pass archive and Lessons content to `scripts/write-frozen-review.py`, which verifies the updates and advances `reviewed-through` to the manifest's `through` as its final durable write. A first-run `UNKNOWN` marker is not writer input: obtain the maintainer's starting-commit decision separately and keep this marker unchanged until an explicitly approved boundary is established.
- The Lesson-promotion CI check is read-only and checks only the persisted `LESSONS.md` and `docs/code-standards.md` records. It does not calculate or select a review range, inspect commits for a retrospective, create review archives, or read or update `reviewed-through`.

When recording a specific event, evidence may support checking whether it can be reproduced using the reporter's surface, scenario, and inputs; whether test fixtures preserve the shape of the real request or disk data; whether processes, asynchronous tasks, and temporary resources started by tests are cleaned up on both success and failure paths; and whether existing baseline failures were investigated and the conclusion recorded. These are review leads, not assumptions that this project already has these problems or must adopt a particular response; in particular, do not generalize one project's policy for handling red tests into a rule for all projects.

## Record identity and evidence schema

- Give every lesson a stable ID of the form `L-0001` (the numeric suffix has at least four digits). Assign the next unused ID; never change it when wording, dates, or status change, and never reuse an ID. IDs must be unique across the active-lessons and promotion-history blocks.
- Keep active records between `ACTIVE_LESSONS:START` and `ACTIVE_LESSONS:END`, and promoted records between `PROMOTED_LESSONS:START` and `PROMOTED_LESSONS:END`. Each record heading starts `### L-0001 —` followed by the executable rule.
- Under **Review evidence**, each row begins with a backtick-delimited ISO date, followed by an em dash and a Markdown link to specific inspected project evidence. The date is the date of the completed review that observed the lesson, not a commit timestamp, event date, or promotion date. Each row must cite concrete evidence inspected for that date. Multiple rows or citations from the same review date count once.
- A promoted standard uses a stable ID of the form `PS-0001`. Its standards entry must cite one or more lesson IDs, and the union of those lessons' structured review-evidence rows must contain at least three different valid dates. The corresponding promoted lesson record names that `PS-` ID.
- A promotion date is traceability metadata, not evidence. Legacy `Seen N×` text or a generic Evidence field without structured date-specific citations does not count toward the threshold. Migrate only dates and citations supported by repository evidence; do not infer review dates from commit dates, repeated mentions, or the date of this migration. If the evidence cannot be verified, leave the rule unpromoted and state the migration gap.
- CI checks ID syntax/uniqueness, cross-references, date syntax/distinctness, and citation shape. It cannot determine whether a cited artifact is genuine, whether the reviewer actually inspected it, whether the observations are semantically the same lesson, or whether the evidence justifies the rule; those remain human-review responsibilities.

## Active lessons

<!-- ACTIVE_LESSONS:START -->
<!-- ACTIVE_LESSONS:END -->

## Promotion history

> Preserve each promoted lesson's original ID, explanation, dated evidence, and follow-up here; record the promotion date and standards rule ID.

<!-- PROMOTED_LESSONS:START -->
<!-- PROMOTED_LESSONS:END -->

## Entry format

The following is a format template, not evidence and not a record to copy as a factual lesson:

```markdown
### L-0001 — <one executable rule>
- **Why:** <cause and consequence confirmed by the review; clearly mark uncertain parts>
- **Review evidence:**
  - `YYYY-MM-DD` — [specific inspected project evidence](URL-or-repository-path)
  - `YYYY-MM-DD` — [specific inspected project evidence](URL-or-repository-path)
  - `YYYY-MM-DD` — [specific inspected project evidence](URL-or-repository-path)
- **Fix or follow-up:** <fix commit, or owner if unresolved>
- **Done right:** <if any, record a counterexample or effective practice>
- **Status:** active | promoted
- **Promoted rule:** PS-0001 (required only after promotion)
- **Promotion date:** YYYY-MM-DD (required only after promotion; not evidence)
```

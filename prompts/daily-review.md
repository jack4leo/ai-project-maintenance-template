# Daily review of project changes

Follow `AGENTS.md` and `docs/automation/runner-contract.md`. Do not calculate the range from `LESSONS.md` or the current branch yourself. Freeze it first and use only the resulting manifest:

```bash
python3 scripts/freeze-review-range.py --repo . > "$TMPDIR/frozen-review-manifest.json"
```

If freezing fails, the manifest is missing/invalid, or the range cannot be fully inspected, stop and report the gap. In particular, when `reviewed-through` is `UNKNOWN`, ask a maintainer which target-branch commit is the first one to include. The exclusive watermark must be that selected commit's parent on the target branch; for a merge start, use the target-branch parent (normally the first parent), not the side-branch parent. If the selected commit has no target-branch parent, stop for a maintainer-approved baseline design. Do not infer a start commit, initialize, repair, or advance `reviewed-through`, and do not invoke the writer while it is `UNKNOWN`. Do not replace the frozen `from`, `through`, commit list, or policy with newer repository state. The manifest's `commits` array is the complete commit range. `excluded_paths` records path exclusions; they do not remove their commits from the manifest.

Before reading a patch or file, compare each commit/parent/path with `excluded_paths`. Do not open or review the contents of a path excluded for that comparison. Review the remaining, non-excluded changes in each manifest commit; an excluded path does not exclude other paths in the same commit. Avoid whole-commit patches that would print excluded file contents. Record the excluded paths and their policy reasons in the archive so the omission is explicit. Only exclusions actually present in the frozen manifest apply. The `generated-data-paths` policy uses explicitly configured literal file/directory prefixes and defaults to an empty list; do not infer a target project's generated-data locations or widen its patterns.

Read project profile, Lessons, project code standards, subsystem index and relevant subsystem pages. Focus the retrospective on errors in development, code review (CR), merge/release, and verification. Do not review the contents of generated data pulled, generated, and committed by daily GitHub Actions; those contents are not themselves Lessons. For each included commit and its relevant non-excluded context, look for:

1. **Rework:** was the change reverted, corrected, reopened, or did it require another fix? Identify the confirmed defect and evidence.
2. **Should not have merged/released:** did it violate a documented requirement, introduce a confirmed regression, bypass a required check or exceed authorization? Separate objective impact from reviewer opinion.
3. **Validation gap:** was a material path not tested, were tests misleading/flaky, or was a success claim unsupported? Cite the actual CI/test output or the missing gate.
4. **Done right:** what specific test, isolation boundary, review habit or rollout avoided a known failure? Record evidence, not generic praise.

A generated-data or workflow anomaly may be recorded as an automation-health/verification issue only when supported by workflow status, CI, validator output, or other evidence that does not require reading excluded snapshots. Do not promote snapshot contents themselves directly into Lessons.

Check later commits and the final current behavior before concluding an earlier change was wrong; trace rework to its final status and, when conditions allow, reproduce it through the surface and input used by the original reporter. Search relevant tests, issues/PRs and CI results when available. Do not infer a cause from timing alone. If facts conflict, record an unresolved question rather than a verdict.

Identify failing checks that were already present on the main branch or review baseline. Investigate whether each is a real defect when evidence and safe access permit, and record what was checked and the conclusion (or the unresolved owner/action); do not automatically treat a pre-existing red check as proof that the new change passes or fails.

Prepare concise, actionable, project-specific Lessons entries with evidence. Give each lesson a stable, never-reused `L-0001` ID and add date-specific evidence rows only for completed review dates, with a concrete link for each date. Repeated events or citations on the same date count once. A one-off lesson remains active in Lessons. Only after the same lesson is independently evidenced on at least three different dates, promote it to the stable-rules block in `docs/code-standards.md`, assign a `PS-0001` ID, cite the supporting lesson ID(s), and move the complete lesson record to promotion history without changing its ID or dated evidence. Promotion dates do not count as evidence. Do not use legacy `Seen N×` text or generic evidence fields to meet the threshold; migrate only dates and citations verified from repository evidence, and leave unsupported history unpromoted with the gap stated. A severe single event may justify a clearly labeled temporary protection proposal, not an unapproved permanent policy.

Follow the runner contract's stable range-key and recovery protocol. Save an archive record at the location configured in `docs/project-profile.md` (`docs/reviews/YYYY-MM-DD.md` by default); distinct same-day ranges must have separate entries and a retry of the same key must reuse its entry. Include the date/timezone, exact `from` and `through` SHAs, inspected commit count, excluded-path summary, evidence sources checked, findings grouped by category, Lessons and standards changes, unresolved questions, runner status, and checks/CI evidence actually seen. If no evidence-backed issue or `Done right` was found, record the inspected range, exclusions, sources checked, date, and `No new evidence-backed lesson`.

Do not directly edit the archive, `LESSONS.md`, `docs/code-standards.md`, or the `reviewed-through` marker. Write archive, active Lessons, and (only when a promotion is justified) complete promoted-Lesson and promoted-standard content to temporary UTF-8 input files outside the repository. Then use the writer with the exact frozen manifest and configured archive path:

```bash
python3 scripts/write-frozen-review.py \
  --repo . \
  --manifest "$TMPDIR/frozen-review-manifest.json" \
  --archive docs/reviews/YYYY-MM-DD.md \
  --archive-content "$TMPDIR/review-record.md" \
  --lessons-content "$TMPDIR/lesson-entries.md"
```

When promoting, add both optional arguments `--promoted-lessons-content "$TMPDIR/promoted-lessons.md"` and `--promoted-standards-content "$TMPDIR/promoted-standards.md"`. The promoted record must preserve its Lesson ID and all verified dated citations; the standards entry must cite the supporting Lesson ID(s). Include each promoted record only in the promotion input, not in `--lessons-content`; the writer moves those IDs out of active history and upserts the promotion and standards blocks by range key. Do not pass these inputs when no promotion is due; the writer does not decide eligibility or verify that cited evidence is authentic.

An empty Lessons-content file records that there are no new active Lessons; the archive record must not be empty. Promotion inputs are a pair and must not be empty. The writer upserts by range key, verifies the archive and every requested memory update, and advances `reviewed-through` to `through` only as its final durable write. Re-read the written record, Lessons, and standards after it succeeds. If the writer fails, any required write/verification fails, or the archive location is `UNKNOWN`/unwritable, stop, report the incomplete range key and preserve the prior watermark; never manually edit or advance the marker as a fallback. Finish with a short report containing the same key fields and archive path.

The Lesson-promotion CI gate validates only the already-persisted Lessons and standards records. It does not select or calculate the review range, run the retrospective, create the archive, or read/update `reviewed-through`; those responsibilities remain with the frozen-range and writer scripts.

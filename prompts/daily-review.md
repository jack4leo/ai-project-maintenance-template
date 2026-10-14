# Daily review of project changes

Follow `AGENTS.md` and `docs/automation/runner-contract.md`. Review the verified range from the last successful `reviewed-through` SHA up to the collected HEAD. Read project profile, Lessons, project code standards, subsystem index and relevant subsystem pages. If the range is incomplete or ambiguous, stop and report the gap without advancing the watermark.

For each commit and its relevant context, look for:

1. **Rework:** was the change reverted, corrected, reopened, or did it require another fix? Identify the confirmed defect and evidence.
2. **Should not have merged/released:** did it violate a documented requirement, introduce a confirmed regression, bypass a required check or exceed authorization? Separate objective impact from reviewer opinion.
3. **Validation gap:** was a material path not tested, were tests misleading/flaky, or was a success claim unsupported? Cite the actual CI/test output or the missing gate.
4. **Done right:** what specific test, isolation boundary, review habit or rollout avoided a known failure? Record evidence, not generic praise.

Check later commits and the final current behavior before concluding an earlier change was wrong; a follow-up may already have repaired it. Search relevant tests, issues/PRs and CI results when available. Do not infer a cause from timing alone. If facts conflict, record an unresolved question rather than a verdict.

Update `LESSONS.md` with concise, actionable, project-specific rules and evidence. Merge duplicate observations into one rule. Increment `Seen` only for a distinct completed review date; multiple commits or copies on the same date count once. A one-off lesson remains in Lessons. Only after the same lesson is independently evidenced on at least three different dates, promote a stable, generalizable rule into the project-specific section of `docs/code-standards.md`, retain dates and links, and mark its promotion in Lessons. A severe single event may justify a clearly labeled temporary protection proposal, not an unapproved permanent policy.

Save one dated review record for each completed review at the location configured in `docs/project-profile.md` (`docs/reviews/YYYY-MM-DD.md` by default); create parent directories as needed. Include the date/timezone, exact `from` and `through` SHAs, inspected commit count, evidence sources checked, findings grouped by category, Lessons and standards files changed, unresolved questions, runner status, and checks/CI evidence actually seen. If no evidence-backed issue or `Done right` was found, record the inspected range, sources checked, date, and `No new evidence-backed lesson`. If the archive location is `UNKNOWN` or cannot be written, report the problem and do not advance the watermark. Advance the reviewed-through watermark only after every commit in the range has been examined and both the review record and memory-file updates succeed. Finish with a short report containing the same key fields and the archive path.

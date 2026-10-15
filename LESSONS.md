<!-- reviewed-through: UNKNOWN (bootstrap the project before using this watermark) -->
# Project Lessons and Retrospectives (Lessons)

This is the target project's living incident and learning log, not a collection of generic examples. Except for the maintenance protocol defined in this file, every entry must come from commits, issues/PRs, CI output, reproduction records, or verifiable maintainer feedback inspected for this project; do not copy specific technical rules from templates or other projects.

## Maintenance protocol

- Daily review scope: from the commit after the previous `reviewed-through` through the current HEAD obtained at review time; record the exact commit SHA, date, time zone, and scope. Only reviewed commits may advance the watermark.
- Focus on three categories: **fixed and then reworked**, **merged/released when they should not have been**, and **insufficient validation or an untrusted validation baseline**. Also record `Done right` to preserve effective practices.
- Write rules as short, executable constraints for next time; include the incident cause, impact, fix/follow-up action, and evidence links. When evidence is insufficient, phrase it as an open question, not as a confirmed causal claim.
- Count `Seen` by **distinct review dates** on which the lesson appeared. Multiple commits or repeated events on the same day count as one day; do not inflate the count through repeated edits or by splitting a review.
- By default, only after a generalized stable rule has appeared independently in reviews on **at least 3 different dates** may it be promoted to the project-specific section of [`docs/code-standards.md`](docs/code-standards.md). During promotion, move the rule, scope, and evidence, and note the promotion here; do not lose the source.
- A serious one-time security, data-loss, or release incident may immediately warrant a temporary safeguard; clearly mark it `Temporary rule / pending maintainer confirmation`, do not present it as a three-day promotion, and do not expand it into an unapproved product policy.
- After updating a rule, check AGENTS routing, relevant subsystem pages, tests, and other entry points for conflicts; keep one authoritative definition and do not duplicate it by copy-paste.
- Even when nothing is found that day, state the review scope, sources checked, and “no new lessons”; then advance reviewed-through.

When recording a specific event, evidence may support checking whether it can be reproduced using the reporter's surface, scenario, and inputs; whether test fixtures preserve the shape of the real request or disk data; whether processes, asynchronous tasks, and temporary resources started by tests are cleaned up on both success and failure paths; and whether existing baseline failures were investigated and the conclusion recorded. These are review leads, not assumptions that this project already has these problems or must adopt a particular response; in particular, do not generalize one project's policy for handling red tests into a rule for all projects.

## Active lessons

> Keep this empty until Bootstrap is complete. After the initial review, replace this prompt with new entries.

<!-- ACTIVE_LESSONS -->

## Promotion history

> Record the promotion date, standards section, and the distinct review dates on which it was based, preserving traceability.

<!-- PROMOTED_LESSONS -->

## Entry format

```markdown
### <one executable rule>
- **Why:** <cause and consequence confirmed by the review; clearly mark uncertain parts>
- **Evidence:** <commit SHA / issue / PR / CI run / reproduction record link>
- **Fix or follow-up:** <fix commit, or owner if unresolved>
- **Done right:** <if any, record a counterexample or effective practice>
- **Seen N×:** <YYYY-MM-DD, YYYY-MM-DD, ...> (dates must be distinct)
- **Status:** active | promoted (link to the code-standards rule when promoted)
```

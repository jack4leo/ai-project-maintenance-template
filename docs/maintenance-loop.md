# Project maintenance loop

This mechanism centers on “read project memory for every change, update project memory for every review.” `AGENTS.md` handles routing; `docs/subsystems/` records current system facts; `docs/code-standards.md` stores general and promoted stable rules; `LESSONS.md` stores recent evidence-backed lessons. They link to one another without redefining the same content.

## 1. One-time initialization (Bootstrap)

The agent first inspects the repository entry points, existing rules, package/build manifests, CI workflows, test configuration, code directories, and necessary key implementations. Based on this, it fills in `docs/project-profile.md`, lists verified validation commands and permission boundaries, identifies subsystems by runtime responsibility rather than directory name, and writes current-behavior references for each subsystem with an independent contract. It records conventions, CI checks, and security risks that actually exist in the project in the code-standards and contributors documents. Every conclusion must link to source, test, or configuration files.

Do not fill template `UNKNOWN` values with guesses, create release gates that do not exist, or copy subsystem details from other projects. Mark unverifiable content as unknown; leave product tradeoffs and autonomous permissions for maintainer confirmation. Until initialization is complete, the project must not call the template rules customized project standards.

## 2. Each development task

At the start, follow `AGENTS.md` to read the profile, Lessons, applicable standards, and subsystem pages. Trace behavior completely from external entry points through state writes, outputs, and side effects; check analogous entry points and boundary conditions; reproduce first and then modify according to actual risk. When fixing a defect, reproduce it using the reporter's actual surface and original inputs where possible; record specific limitations when conditions are insufficient or reproduction is impossible, and do not present speculation as resolved. Include tests with code changes; when fixing behavior, verify where possible that the regression test fails under the old behavior. When interfaces, state, compatibility, permissions, or failure modes change, update the relevant subsystem page in the same change.

When complete, run the checks specified by the profile against the current review HEAD. Commits/PRs must state the commands and results actually run, items not run and why, and the reviewed SHA. If HEAD changes during checking, review and validate the new HEAD again. When no real integration or platform environment is available, say so plainly; do not substitute unit tests for real-use validation.

## 3. PR / external contribution review

Read `docs/contributors.md` first for security and scope triage, then review the target against code-standards and subsystem refs. Do not review only the diff: verify the claimed behavior and call chain, affected sibling cases outside the change scope, platform/client variants, fallbacks or alternative implementations, and consistency of documentation and tests. If code, tests, CI, or documentation show conflicting rules, report the conflict and correct the single authoritative location. When project-profile escalation conditions apply, a product issue requires an owner decision, or an operation exceeds the permission boundary, stop at the recommendation stage.

## 4. Daily commit retrospective

Each day, an agent authorized to read repository history and validation results reviews commits from after reviewed-through through the latest HEAD. Prioritize three categories: repeated rework, changes that should not have been merged/released, and insufficient validation; also record `Done right`. Every Lesson must have project evidence, a cause, and an executable rule; record events only and do not assume causation. Even when a review finds nothing, leave its scope and the new watermark.

Record distinct dates according to `LESSONS.md`. By default, promote the same lesson to a stable project-specific code-standards rule only after it appears on at least three independent review dates. A serious one-time risk may be proposed as a temporary rule, but mark it as pending owner confirmation. After promotion, retain source dates and evidence; do not delete the historical trail.

## 5. Periodic calibration

Maintainers or agents periodically check whether Lessons have been promoted or invalidated, standards are covered by implementation/CI, subsystem facts have drifted from the code, links and commands remain valid, and `reviewed-through` does not omit commits. Explicitly revise or archive outdated rules; do not let documentation grow without limit merely to appear complete.

## 6. Automation integration

The template provides reusable prompts and [`automation/runner-contract.md`](automation/runner-contract.md), but does not bind any particular model, scheduled service, or token, nor imply that a scheduled agent is configured. After selecting the actual scheduler, the project owner sets the time zone, read-only/write scope, run branch, report destination, and matters requiring maintainer involvement. First run it at least once in read-only mode to confirm that commit scope, watermark updates, and privacy controls are correct; only then open permissions for writing documentation, opening PRs, and similar actions.

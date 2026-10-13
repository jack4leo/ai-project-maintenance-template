# Daily-review runner contract

This is an adapter contract for any authorized scheduled agent. It is intentionally provider-neutral: the template does not configure a model, scheduler, API credential, GitHub App, or workflow. The owner must choose and authorize those separately.

## Required inputs

The runner needs a repository checkout, project timezone, default branch, the last **successfully reviewed** commit SHA, current HEAD, this repository's `AGENTS.md`, `LESSONS.md`, `docs/project-profile.md`, `docs/code-standards.md`, `docs/subsystems/README.md`, and the review prompt. If PR/CI metadata is used, it must be read-only and scoped to this repository.

The run records both boundary SHAs and the time of collection. If the previous SHA is missing, not an ancestor of HEAD, the branch was rewritten, history is shallow, or the intended range cannot be proven complete, do not silently move the watermark: report the gap and ask for recovery instructions. Handle merge commits and amended/rebased history according to a project policy recorded in `project-profile.md`.

## Required behavior

1. Run with the repository timezone. Acquire a single-run lock or otherwise prevent overlapping reviews from racing over `LESSONS.md` and the watermark.
2. Inspect every commit in the verified range and relevant diff/context; read available CI/PR evidence. Do not execute untrusted code merely to review it.
3. Follow [`../../prompts/daily-review.md`](../../prompts/daily-review.md). Cite the commit/PR/check evidence behind each finding; separate observations from causal hypotheses.
4. If successful, write a concise review record and update the reviewed-through SHA. If analysis, writes, or evidence retrieval fails, preserve the last successful watermark so the same range can be retried.
5. Make document-only changes on a dedicated branch or in the project's approved review channel. Report the branch/PR and the exact range. Do not merge, publish, deploy, change account access, or touch production unless the project profile explicitly grants that authority.

## Permissions and privacy

Start read-only. Grant write access only to the project memory files and only after the owner verifies the initial run. Use least-privilege credentials, never print or persist secrets, and do not send source or commit data to unapproved services. Any runner output must redact secret material and avoid copying large diffs or private payloads into logs.

## Successful result fields

A successful run records: review date/timezone; `from` and `through` SHA; number of commits inspected; evidence sources checked; findings grouped as rework / should-not-merge-or-release / validation-gap / done-right; Lessons and standards files changed; unresolved questions; runner status. A no-finding day still records the range and `No new evidence-backed lesson`.

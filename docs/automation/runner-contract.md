# Daily-review runner contract

This is an adapter contract for any authorized scheduled agent. It is intentionally provider-neutral: the template does not configure a model, scheduler, API credential, GitHub App, or workflow. The owner must choose and authorize those separately.

## Required inputs

The runner needs a repository checkout, project timezone, default branch, the last **successfully reviewed** commit SHA, current HEAD, this repository's `AGENTS.md`, `LESSONS.md`, `docs/project-profile.md`, `docs/code-standards.md`, `docs/subsystems/README.md`, and the review prompt. If PR/CI metadata is used, it must be read-only and scoped to this repository.

The run records both boundary SHAs and the time of collection. If the previous SHA is missing, not an ancestor of HEAD, the branch was rewritten, history is shallow, or the intended range cannot be proven complete, do not silently move the watermark: report the gap and ask for recovery instructions. Handle merge commits and amended/rebased history according to a project policy recorded in `project-profile.md`.

The project profile must state the applicable policy for overlapping runs, failures/retries, timeout or interruption, and recovery from partial writes. Do not assume a scheduler, locking service, retry policy, or storage atomicity that the project has not selected and verified. Keep recovery behavior consistent with the watermark and archive guarantees above.

## Idempotency and recovery

- Give each verified range a stable key, for example `<repository>/<default branch>/<from SHA>..<through SHA>`, and store it in the review record. Every retry of that range reuses the same key; attempt timestamps are not deduplication keys.
- Under the default `docs/reviews/YYYY-MM-DD.md` archive, keep a distinct entry per range key. A retry resumes or upserts the same entry; a different range on the same date gets a separate entry (or a separate key-named file). Never replace an earlier completed record just because the date matches.
- Apply archive and memory-file changes as idempotent upserts associated with the range/evidence. A retry must not duplicate records or lessons, or increment `Seen` again for the same review date. Keep the previous watermark while writing and checking these files.
- Re-read and verify every required archive and memory update, then advance the reviewed-through watermark to `through` as the final durable write. If any write or verification fails, or the run is interrupted before that final write, preserve the previous watermark.
- On retry, inspect the existing entry and memory changes for the same key, reconcile what is already complete, and write only missing/corrected content. Do not discard earlier successful records to restart. If partial or corrupt state cannot be reconciled safely, stop and ask the owner; do not assume atomic replacement, backups, or locking unless the selected storage mechanism provides them.

## Required behavior

1. Run with the repository timezone. Acquire a single-run lock or otherwise prevent overlapping reviews from racing over `LESSONS.md` and the watermark.
2. Inspect every commit in the verified range and relevant diff/context; read available CI/PR evidence. Do not execute untrusted code merely to review it.
3. Follow [`../../prompts/daily-review.md`](../../prompts/daily-review.md). Cite the commit/PR/check evidence behind each finding; separate observations from causal hypotheses.
4. If successful, write the review record and required memory updates idempotently, verify them, then advance the reviewed-through SHA as the final write. If analysis, writes, or evidence retrieval fails, preserve the last successful watermark and retry with the same range key.
5. Make document-only changes on a dedicated branch or in the project's approved review channel. Report the branch/PR and the exact range. Do not merge, publish, deploy, change account access, or touch production unless the project profile explicitly grants that authority.

## Permissions and privacy

Start read-only. Grant write access only to the project memory files and only after the owner verifies the initial run. Use least-privilege credentials, never print or persist secrets, and do not send source or commit data to unapproved services. Any runner output must redact secret material and avoid copying large diffs or private payloads into logs.

## Successful result fields

A successful run records: review date/timezone; `from` and `through` SHA; number of commits inspected; evidence sources checked; findings grouped as rework / should-not-merge-or-release / validation-gap / done-right; Lessons and standards files changed; unresolved questions; runner status. Each finding and material conclusion must be traceable to the specific reviewed commit(s) and concrete evidence (for example, a source reference, test command/result, or CI run); record evidence locations/identifiers rather than copying large or sensitive payloads. A no-finding day still records the range and `No new evidence-backed lesson`.

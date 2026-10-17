# Frozen-range writer contract

`scripts/write-frozen-review.py` is the independent write stage. It consumes a manifest emitted by `freeze-review-range.py`; it does not calculate a range, inspect current `HEAD`, review commits, create Lesson IDs, or enforce the distinct-review-date promotion gate.

## Inputs

The caller must provide all of the following explicitly:

- `--manifest`: the canonical UTF-8 JSON file emitted by the range freezer, including its single trailing newline;
- `--archive`: an explicit repository-relative destination under `docs/reviews/` ending in `.md`;
- `--archive-content`: UTF-8 review-record body prepared by the caller; and
- `--lessons-content`: UTF-8 Lesson entries prepared by the caller. An empty file records an empty, retryable Lessons block.
- optionally, both `--promoted-lessons-content` and `--promoted-standards-content`: complete promoted Lesson records and corresponding `PS-` rules, prepared by the caller only after checking the promotion threshold and evidence. They must be supplied together; omitting both leaves promotion history and standards untouched.

The writer validates manifest version, the exact nested schema emitted by the range freezer, full object-ID syntax, canonical serialization, and the `sha256:` range key. It accepts legacy exclusion-policy version 1 and version 2, whose additional `path-prefix` rule contains literal configured paths without wildcards, and current version 3, which preserves free-text `producer` only on `path-prefix` rules and requires it to be non-empty when `paths` is populated; when present on an empty rule it must also be non-empty. The existing non-empty `reason` remains required. This verifies the frozen data's structure and integrity; it does not re-freeze or independently prove the commit range. The current `LESSONS.md` marker must equal the manifest's `from` (first attempt/partial retry) or `through` (same-range idempotent completion). Any other value is stale or out of order and fails closed. `UNKNOWN` is always rejected; the caller must ask a maintainer to choose the first target-branch commit and confirm its target-branch parent as the exclusive boundary before any review/write flow. The writer never infers, initializes, or installs that starting point.

## Write and retry order

For each range key, the writer upserts one delimited block in the archive and one block inside `LESSONS.md`'s active-lessons section. When both optional promotion inputs are present, it also upserts a range-key block in the `PROMOTED_LESSONS` section and in the `PROMOTED_RULES` block of `docs/code-standards.md`. A promoted Lesson ID must already occur once in a writer-managed active range block (or in this same key's promotion block on retry), and must not also appear in the current `--lessons-content`; the writer removes that complete record from active history while preserving the old range block and all other Lesson records. On any retry, an ID already present in promotion history is rejected if it reappears in `--lessons-content`, even when promotion inputs are omitted. It refuses duplicate or conflicting IDs rather than silently merging them. It does not create IDs, decide whether the three-date threshold is met, or authenticate evidence; those remain caller/review and CI responsibilities.

`LESSONS.md` accepts paired `ACTIVE_LESSONS:START` / `ACTIVE_LESSONS:END` and `PROMOTED_LESSONS:START` / `PROMOTED_LESSONS:END` markers, or the legacy single-line anchors for both sections. The standards destination must contain exactly one ordered `PROMOTED_RULES:START` / `PROMOTED_RULES:END` pair. Retrying the same key replaces only that key's blocks; other keys and unrelated content remain intact. Empty active Lessons content is represented by a retryable placeholder, so a later retry can fill the same block.

The sequence is:

1. Validate and lock the writer transaction; validate the manifest and existing watermark.
2. Validate all requested destination sections and compute updates before the first write.
3. Upsert the archive, then (if requested) `docs/code-standards.md`, then `LESSONS.md`, keeping the prior watermark. Re-read/verify every requested range-key block and destination.
4. Atomically replace `LESSONS.md` with the `reviewed-through` value set to the manifest's `through`. No file write follows this final write.

A failure before the final watermark replacement leaves the old marker in place; earlier successful archive, standards, or Lessons blocks remain and are reconciled on retry using the same key. The writer does not roll back or delete those records. Filesystem cleanup only unlinks a temporary path after verifying that its device/inode are the temporary file created by this transaction. The staging path is checked against that inode immediately before replacement, and the published path's inode and bytes are checked afterward. It never removes `.rollback-*` or ordinary `.flywheel-*` paths. Created empty archive directories may remain after a later failure rather than being removed without a transaction-owned inode proof.

## Filesystem boundary and non-goals

The writer uses directory file descriptors, `O_NOFOLLOW` for repository path traversal and file opens, a persistent advisory lock at the Git common directory, regular-file checks, staged same-directory replacement, and read-back checks. The lock file is intentionally retained (not cleaned up). A non-cooperative process with write access to a destination directory can still replace the staging pathname in the narrow interval between the final inode check and the pathname-based rename; the post-write check detects a different published inode but cannot guarantee that the destination was never briefly replaced or restore the old target after that race. If that check fails, inspect both the destination and retained temporary paths before retrying. Hardware/power-loss behavior and filesystems that do not honor expected atomic rename/fsync semantics are also environmental boundaries. The advisory lock coordinates only cooperating writers; it is not a defense against an actor able to mutate these directories concurrently.

Lesson IDs and CI that counts appearances on at least three distinct review dates operate only on persisted `LESSONS.md` content. This writer neither calculates nor gates those values. It does not set a review date/time zone or choose an archive location; the caller supplies the archive path and all content. It does not infer or modify the reviewed-through starting point, change installer code, or change installer recovery behavior.

## Verification

Run `PYTHONDONTWRITEBYTECODE=1 python3 tests/test-range-writer.py` for writer-specific fixtures and `bash tests/test-install.sh` for the full installer and range/writer regression suite.

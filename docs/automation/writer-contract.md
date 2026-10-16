# Frozen-range writer contract

`scripts/write-frozen-review.py` is the independent write stage. It consumes a manifest emitted by `freeze-review-range.py`; it does not calculate a range, inspect current `HEAD`, review commits, create Lesson IDs, or enforce the distinct-review-date promotion gate.

## Inputs

The caller must provide all of the following explicitly:

- `--manifest`: the canonical UTF-8 JSON file emitted by the range freezer, including its single trailing newline;
- `--archive`: an explicit repository-relative destination under `docs/reviews/` ending in `.md`;
- `--archive-content`: UTF-8 review-record body prepared by the caller; and
- `--lessons-content`: UTF-8 Lesson entries prepared by the caller. An empty file records an empty, retryable Lessons block.

The writer validates manifest version and shape, full object-ID syntax, canonical serialization, and the `sha256:` range key. This verifies the frozen data's integrity; it does not re-freeze or independently prove the commit range. The current `LESSONS.md` marker must equal the manifest's `from` (first attempt/partial retry) or `through` (same-range idempotent completion). Any other value is stale or out of order and fails closed. `UNKNOWN` is always rejected; no starting point is inferred or installed.

## Write and retry order

For each range key, the writer upserts one delimited block in the archive and one delimited block inside `LESSONS.md`'s `ACTIVE_LESSONS` section. Retrying the same key replaces only those blocks; other keys, including a different range on the same review date, remain intact. Empty Lessons content is represented by a retryable placeholder, so a later retry can fill the same block.

The sequence is:

1. Validate and lock the writer transaction; validate the manifest and existing watermark.
2. Upsert the archive block and re-read/verify it.
3. Upsert Lessons while keeping the prior watermark; re-read/verify Lessons and re-verify the archive.
4. Atomically replace `LESSONS.md` with the `reviewed-through` value set to the manifest's `through`. No file write follows this final write.

A failure before the final watermark replacement leaves the old marker in place; earlier successful archive/Lessons blocks remain and are reconciled on retry using the same key. The writer does not roll back or delete those records. Filesystem cleanup only unlinks a temporary path after verifying that its device/inode are the temporary file created by this transaction. It never removes `.rollback-*` or ordinary `.flywheel-*` paths. Created empty archive directories may remain after a later failure rather than being removed without a transaction-owned inode proof.

## Filesystem boundary and non-goals

The writer uses directory file descriptors, `O_NOFOLLOW` for repository path traversal and file opens, a persistent advisory lock at the Git common directory, regular-file checks, staged same-directory replacement, and read-back checks. The lock file is intentionally retained (not cleaned up). Uncooperative processes that modify files without taking this lock, hardware/power-loss behavior, and filesystems that do not honor expected atomic rename/fsync semantics remain environmental boundaries; the writer detects observed content/identity changes before replacement and fails closed where possible.

Lesson IDs and CI that counts appearances on at least three distinct review dates operate only on persisted `LESSONS.md` content. This writer neither calculates nor gates those values. It does not set a review date/time zone or choose an archive location; the caller supplies the archive path and content. It does not change installer code or installer recovery behavior.

## Verification

Run `PYTHONDONTWRITEBYTECODE=1 python3 tests/test-range-writer.py` for writer-specific fixtures and `bash tests/test-install.sh` for the full installer and range/writer regression suite.

# Daily-review runner contract

This contract separates **range freezing** from any later review or write stage. The first stage proves and emits one immutable range manifest. It does not review lessons, archive a retrospective, or modify the watermark. Any later writer consumes that already-frozen manifest; it must not derive or silently replace the range from a newer `HEAD` or watermark.

The template does not configure a model, scheduler, API credential, GitHub App, or workflow. The owner must choose and authorize those separately.

## Stage 1: freeze a read-only range

### Inputs and authority

The range freezer reads only:

- Git commit/tree/blob history and repository metadata needed to identify `HEAD`, validate ancestry and completeness, and enumerate changed paths;
- the one `reviewed-through` marker at the top of the working-tree `LESSONS.md`; and
- the exclusion policy at [`range-exclusions.json`](range-exclusions.json), as committed in the frozen `through` commit.

`LESSONS.md` is the sole watermark authority. `docs/project-profile.md` may configure the archive location, but it is not a second watermark store. The marker must occur exactly once and contain a non-empty, full-length hexadecimal commit object ID for this repository's object format. `UNKNOWN`, a missing/duplicate marker, an abbreviated or malformed ID, an ID that does not resolve to a commit, missing required objects, shallow or otherwise incomplete history, or a watermark that is not an ancestor of `HEAD` is a hard failure. Do not guess, bootstrap, fetch, repair, or advance the watermark. In particular, a rebase/force-push that makes the watermark non-ancestral requires explicit recovery outside this stage. Replacement refs or grafts must not be allowed to redefine ancestry.

The lower boundary `from` is the reviewed-through watermark and is **exclusive**. `through` is the full object ID of the `HEAD` observed during freezing and is **inclusive**. The commit list contains every commit reachable from `through` but not from `from`. If `from == through`, the list is empty. The freezer validates connectivity and verifies the content hash of every reachable Git object, not just that an object with the expected name exists. It must fail closed rather than emit a partial or hash-unverified range.

### Commit order and path exclusions

List each included commit once, in a deterministic parent-before-child topological order. If multiple commits are ready at the same point in that order, choose the lexicographically smallest full object ID first. Record each commit's full SHA, tree SHA, and ordered parent SHAs. For path comparison, compare each commit separately with each parent; compare a root commit with the empty tree. Disable rename detection so the same Git tree changes always produce the same path records. A path that cannot be represented as valid UTF-8 is a hard failure, not a lossy or omitted path.

The only path-exclusion authority is the committed JSON policy at `docs/automation/range-exclusions.json` in `through`. The manifest records that source path, its full blob ID and SHA-256 of the exact file bytes, and every configured rule with its rationale. Evaluate rules in file order, but do not stop after the first match: emit one record for each matching rule. If more than one pattern in a path-glob rule matches, record the first matching pattern in that rule's pattern-array order. Path globs are anchored at the repository root: `*` and `?` match within one path segment, while `**` matches zero or more path segments. The binary rule classifies a changed path as binary if either extant side of that parent comparison contains a NUL byte. A gitlink/submodule entry is excluded as a whole because its nested repository contents are not available in this history. An exclusion does not remove its commit from the `commits` array. For every exclusion, emit a separate record identifying the commit, parent (or `null` for a root), repository-relative path, rule ID, matched pattern or classification, and rationale. Order these records by commit-list order, parent order in the commit object (with the root's `null` parent first), path byte sequence, then policy rule order. Do not silently drop paths or rules. Configured rules remain visible even when they match no paths. The policy file is data, not executable code.

### Frozen manifest and range key

Emit one canonical JSON manifest (stdout is permitted). It contains at least:

- `manifest_version`;
- `from` and `through` as full object IDs;
- `commits` in the specified order, with full commit/tree/parent IDs;
- `exclusion_policy`, including source path, source commit/blob ID, exact-byte SHA-256, and all rule definitions/reasons; and
- `excluded_paths`, with one explicit record for every path exclusion.

The range key is `sha256:<lowercase hex>` over the canonical UTF-8 JSON serialization of every manifest field except `range_key`. Canonical serialization uses recursively lexicographically sorted object keys, array order as specified above, compact separators `,` and `:`, unescaped UTF-8 for non-ASCII characters, JSON escaping for required characters, integers only (no floats/NaN), and no trailing newline for the hash input. The emitted JSON may end in one newline. No attempt timestamp, machine path, or other volatile local state belongs in the manifest or key. The commit/tree IDs bind the reviewed Git content; the policy bytes and expanded exclusion records bind the rule set and its effect. Identical inputs therefore yield the same key; a changed `through`, commit graph/content, policy bytes, or exclusion result yields a different key.

### Side-effect boundary and retry behavior

This stage is strictly read-only: it does not write file contents or intentionally change repository metadata. It must not write `LESSONS.md`, create or update anything under `docs/reviews/`, create archives, or advance any watermark. It must not fetch or repair history. Use `O_NOATIME` for direct worktree reads where supported; however, Git subprocesses may update atime on loose or packed object-store files according to the host filesystem's policy. This incidental access-time change is not an application write, and the runner must not try to restore it (restoration can itself change ctime). Set Git to avoid optional locks and lazy fetching. A failed validation emits a non-zero result and no successful manifest. Re-running with the same `from`, `through`, history, and committed policy produces the same manifest and key. If `HEAD` advances, that is a new range and key; never overwrite or reinterpret a previously frozen manifest as the newer range.

## Stage 2: review/write consumer (`scripts/write-frozen-review.py`)

The review agent must use the canonical manifest emitted by `scripts/freeze-review-range.py`; it must not calculate the range from `LESSONS.md` or a later `HEAD`. Review all manifest commits, but before opening each patch or file, match its commit/parent/path against `excluded_paths` and skip the contents of excluded paths for those comparisons. Exclusions do not exclude other paths in the same commit. Record the exclusions and reasons in the archive; do not display whole-commit patches that expose excluded content.

The writer is a separate implementation and permission boundary. It may consume only a previously emitted, canonical manifest whose range key validates; retries and archive, active-Lesson, promotion-history, and standards upserts are keyed to that exact manifest. It may not recalculate `from`, `through`, or the commit list, nor replace a frozen manifest with the current branch state. If the manifest is unavailable or invalid, stop and freeze a new range explicitly rather than guessing. Supply archive and active-Lessons body content in UTF-8 input files and specify an explicit repository-relative `docs/reviews/*.md` archive path. For a justified promotion, pass both the complete promoted Lesson record and corresponding standards rule as the optional paired inputs; the writer migrates the Lesson ID out of active history. It does not select or validate promotion eligibility.

Only this later stage may analyze the commits and, if separately authorized, write review records, Lessons, or standards. The writer verifies the archive and every requested Lessons/standards update before advancing `reviewed-through` to the manifest's `through` as its **last durable write**. The watermark remains unchanged if archive review or any required write/verification fails. Archive entries and all writer blocks are idempotent by range key; retries reconcile the same key rather than creating duplicate entries or deleting unrelated earlier records. A failure may leave an already-written archive, standards, or Lessons block in place; retry with the same manifest and inputs. Any cleanup of partial writes needs its own safe recovery protocol and is not implied by this range contract.

Lesson IDs and CI that counts appearances on at least three distinct review dates are based only on Lessons that have already been written. They do not participate in selecting or proving a range and are outside the range-freezer implementation.

## Review/write behavior

The daily-review consumer and writer must:

1. Use the project's timezone and follow [`../../prompts/daily-review.md`](../../prompts/daily-review.md), with findings grounded in cited commit/PR/check evidence.
2. Preserve the previous watermark through analysis, archive writes, Lessons writes, and verification; `write-frozen-review.py` advances it only as the final durable write after archive review succeeds.
3. Keep a distinct archive entry per range key. Under the default `docs/reviews/YYYY-MM-DD.md` convention, a different range on the same date must not replace an earlier completed record.
4. Report the manifest key and exact boundaries. Do not merge, publish, deploy, change account access, or touch production unless the project profile explicitly grants that authority.

## Permissions and privacy

The range freezer needs read-only Git and file access. A later writer must receive separate, least-privilege authorization for its write scope. Never print or persist secrets, execute untrusted code merely to review it, or send source/commit data to an unapproved service. Logs should avoid copying large diffs or private payloads.

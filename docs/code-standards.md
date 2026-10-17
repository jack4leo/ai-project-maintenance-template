# Code standards

This document defines the minimum review standards applicable to all projects, as well as project-specific conventions continuously maintained by the agent based on **current project evidence**. The two kinds of rules must remain in separate sections; do not treat template placeholders, another repository's habits, or unverified assumptions as this project's rules.

## A. General baseline (does not change with the project stack)

### Change correctness

- Understand existing behavior and the single source of truth before changing anything; trace the complete entry points, state/data flow, error paths, and observable side effects, and check analogous entry points and compatibility paths.
- Keep changes to the minimum necessary scope of the request. Avoid opportunistic refactoring, unrelated formatting, and unrequested product behavior changes.
- When fixing a defect, add a regression test that expresses externally observable behavior; where feasible, confirm that the test fails against the old implementation or when the fix is removed. If an automated test cannot be established, record the specific reason and alternative validation; do not describe it as covered.
- Validate the contract, including normal inputs, boundary/exception inputs, state persistence or restart, compatibility with older configuration, and failure handling (as relevant to the change).

### Data, security, and compatibility

- Do not put secrets, user data, or real credentials in test fixtures, logs, screenshots, commits, or reports; use isolated environments for external services and destructive operations.
- Do not mistake unreadable configuration/data for empty configuration and overwrite user data; for stateful writes, prefer preserving existing atomicity, rollback, and recovery conventions.
- Make clear whether the change affects interfaces, serialization formats, migrations, permissions, authentication, network boundaries, observability fields, dependencies, or release artifacts; cover compatible behavior and failure modes.
- Retries, degradation, or fallback must have explicit trigger conditions, idempotency/safety rationale, ordering, and termination conditions; do not silently change the semantics of user input.
- Logs and traces must be sufficient to explain decisions and errors, while following minimization principles and avoiding unnecessary content or sensitive fields.

### Testing and review

- Use the project's actual formatter, static checks, targeted tests, and necessary full-suite tests; report only commands and results that were actually run.
- Test inputs should preserve the structure of real requests, configuration, or disk formats as far as possible, and cover missing and boundary values relevant to the change; fixtures must remove secrets and real personal data.
- For important defect fixes, where feasible revert the fix, inject a fault, or break the protected behavior to confirm that the regression test actually fails; explain limitations preventing this check, and do not treat the mere existence of a test as proof of effective coverage.
- Clean up child processes, asynchronous tasks, temporary directories, ports, and other resources started by tests; check that failure and cancellation paths also terminate or release resources.
- Select platform, client, and alternative-implementation validation according to the change's impact and the project's support scope; explicitly list untested combinations, and do not require unrelated projects to run a nonexistent matrix.
- Check the implementation, tests, documentation, migrations/examples, and adjacent paths together; preserve validation of important compatibility constraints.
- The final report must state clearly: validated items, unvalidated items and reasons, affected subsystems, and the reviewed commit SHA. Checks not run must not be described as passing.
- If the code HEAD changes during validation, review and validate the final HEAD again; before merging, confirm that required checks target the version under review.

## B. Project-specific standards (continuously maintained by the agent)

> Bootstrap must complete this section from the project's source code, tool configuration, CI, existing rules, and real retrospectives; mark unknowns as `UNKNOWN` and include questions requiring confirmation. Do not copy template examples.

### Technology and repository conventions

- Language, framework, and directory/module conventions: `BOOTSTRAP REQUIRED`
- Formatting, linting, type checking, and build commands: `BOOTSTRAP REQUIRED`
- Dependency, code-generation, migration, and release conventions: `BOOTSTRAP REQUIRED`

### Acceptance and validation requirements

- Targeted and full test commands (including working directory and tags/arguments): `BOOTSTRAP REQUIRED`
- Required CI workflows and passing conditions: `BOOTSTRAP REQUIRED`
- Integration/real-environment tests, isolation method, and untestable scope: `BOOTSTRAP REQUIRED`
- Project-specific normal, boundary, failure, rollback, and compatibility test requirements: `BOOTSTRAP REQUIRED`

### Project-specific risks and stable rules

- Sensitive paths, credentials, personal information, and high-risk operations: `BOOTSTRAP REQUIRED`
- Confirmed design/compatibility decisions and their sources: `BOOTSTRAP REQUIRED`
- Stable rules promoted from Lessons are listed in the block below. Give each rule a unique `PS-0001` ID and cite one or more promoted `L-0001` lesson IDs. The cited lessons must collectively contain at least three distinct, structured review-evidence dates as defined in [`LESSONS.md`](../LESSONS.md).

#### Stable promoted rules

The following bounded block is the authoritative location for project-specific stable promoted rules. Do not count one-off temporary safeguards as stable promotions.

<!-- PROMOTED_RULES:START -->
<!-- PROMOTED_RULES:END -->

If the block is empty, no project-specific stable rule is currently promoted.

Each rule in the block above uses this format:

```markdown
##### PS-0001 — <one executable rule>
- **Scope:** <where the rule applies>
- **Evidence lessons:** `L-0001`, `L-0002`
```

## Maintaining this standard

- The agent may update section B using evidence from `LESSONS.md` and the distinct-date promotion rule; each new convention must state its scope and include an evidence link. Stable promoted rules must use the IDs and cross-references above.
- The read-only Lesson-promotion CI gate validates the persisted record structure and distinct-date threshold. It does not calculate review ranges, create archives, or read or update the `reviewed-through` watermark; humans remain responsible for assessing the cited evidence's authenticity and meaning.
- Section A is the general baseline. If removal or relaxation is needed, first propose a maintainer decision with a risk explanation; do not quietly expand a one-off local exception into a default.
- Whenever CI, test commands, the toolchain, architecture, or an approved policy changes, check whether this section and `docs/project-profile.md` remain accurate.

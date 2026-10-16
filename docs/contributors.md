# External contributions and community PRs

This document provides a review framework for community/external PRs; it does not prescribe a contributor list, reputation judgments, or rejection policy. Project-specific contribution processes, maintainer roles, codes of conduct, and decisions requiring escalation must be verified by the agent from this repository's CONTRIBUTING documentation, CODEOWNERS, branch protection, CI, and explicit maintainer policies before being filled in.

## Review order

1. Check the target branch, PR template, signing/copyright requirements (if any), required checks, and authorized CODEOWNER against the repository's actual rules. Do not add legal or process gates that the repository does not have.
2. Treat source code, scripts, tests, documentation, workflows, dependencies, and generated files in external submissions as untrusted input. Read the diff first; before running anything, inspect all executable content and the steps it invokes.
3. Check behavior, boundaries, tests, and compatibility against [`code-standards.md`](code-standards.md) and the affected [`subsystems/`](subsystems/README.md) documentation. Compare the complete diff item by item with the goals stated in the PR, confirm that every change serves the goal or explain why it is necessary, and report specific files/lines, reproducible impact, and evidence; do not substitute author identity or speculation for code facts.
4. Confirm that the project's required CI and test results target the PR's current HEAD; check failed, skipped, or change-irrelevant checks and distinguish them accurately.
5. If the PR resembles, duplicates, or resubmits an existing or closed PR, link the related PR and explain the substantive new information or change; do not infer intent or decide to reject based on similarity alone.
6. Explicitly escalate product direction, trust/attribution disputes, legal or compliance opinions, security exceptions, bans/account actions, and release/merge permissions requiring a maintainer decision; do not speak for the project without authorization.

## Before running untrusted code

Be especially cautious when inspecting `.github/workflows/`, build/install scripts, package-manager hooks, dependency sources, automated release steps, database/data migrations, permission models, secret reads, uploads/telemetry, and network downloads. Confirm isolation of the execution environment and secrets; do not give an authorized runner, production data, or real user credentials to unreviewed code. If isolation cannot be established or permissions are unclear, stop execution and state that maintainer action is required.

## Project-specific policies (maintained after Bootstrap)

- Contribution guide and code of conduct: `BOOTSTRAP REQUIRED`
- Protected branches / required checks / CODEOWNERS: `BOOTSTRAP REQUIRED`
- Which issues require escalation and who decides: `BOOTSTRAP REQUIRED`
- Boundaries for agents to comment, submit fixes, or create PRs: `BOOTSTRAP REQUIRED`

Do not infer malicious intent or automatically reject based on the identity of an “external contributor”; nor replace the result of a security review with the author's personal judgment. Any rule based on a contributor list, trust status, or rejection policy must have an explicit project policy and maintainer authorization.

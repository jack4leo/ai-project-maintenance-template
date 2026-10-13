# Bootstrap this project for agent-maintained development

Read `AGENTS.md` first, then inspect this repository as an unfamiliar project. Your goal is to adapt the workflow template to **this project's actual evidence**, not to make the files look complete.

## Discovery

1. Read existing root instructions and project docs (including any `AGENTS.md`, `CLAUDE.md`, contribution guides, architecture docs and lessons). Preserve deliberate project decisions; report conflicts instead of overwriting them.
2. Inspect package/build manifests, CI workflows, test configuration, directory layout, executable entry points and a representative path through each important subsystem. Use repository history only to confirm behavior and recurring issues, not as a substitute for source.
3. Identify actual supported languages/platforms, entry points, subsystem responsibilities and owners from code/config/tests. Build a source map with links. Do not infer boundaries from folder names alone.
4. Derive formatting/lint/build/test commands from scripts, CI or documented maintainer instructions. Record command, working directory, prerequisites and scope. Run safe local checks only; never contact production or consume credentials without authorization.

## Adapt project memory

- Fill `docs/project-profile.md` with verified project facts, risk boundaries, actual gates and review schedule. Keep unknown fields `UNKNOWN` and list the evidence/decision needed.
- Keep `docs/code-standards.md`'s generic baseline intact unless the owner approves a change. Replace each `BOOTSTRAP REQUIRED` item with project-specific facts and links, or explicitly leave it `UNKNOWN`. Do not add a rule based only on preference or an unverified failure.
- Fill the project-specific section of `docs/contributors.md` from existing policy, CI protection and owner instructions. Do not invent banned-contributor lists, trust scores, legal rules or merge/release permissions.
- Populate `docs/subsystems/README.md` with a concise index of real responsibility areas. For each area whose contracts matter, copy `docs/subsystems/TEMPLATE.md` to a descriptive filename and document current behavior: ownership, authoritative sources, execution/data flow, state, constraints, failures, compatibility and real verification evidence.
- Initialize `LESSONS.md` only with issues that have verifiable evidence in this repository. Preserve distinct dates and source links; do not treat repeated mentions of one incident as three independent observations. Otherwise leave active lessons empty.
- Keep `AGENTS.md` as a short routing table. If this project has other agent entry files, make them point to the same canonical rules rather than duplicating competing policy.

## Validation and handoff

Check every local Markdown link added or modified, ensure all cited paths exist, and re-run safe documented checks when practical. Review the resulting docs against the source rather than trusting your own summary. Report: files changed; verified commands and results; what remains `UNKNOWN`; decisions requiring an owner; and any source/CI gaps. Do not claim the project is fully bootstrapped if material boundaries or permissions remain unverified.

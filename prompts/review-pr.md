# Review a pull request

Act as an independent reviewer, not as the author. Follow `AGENTS.md`; read `docs/project-profile.md`, `docs/contributors.md`, `docs/code-standards.md`, `LESSONS.md`, and each affected subsystem reference. Review the actual base-to-head diff and surrounding callers/state transitions at the exact head SHA.

Prioritize actionable findings by severity. For each finding, include file/line, the triggering condition, observable impact, evidence or reproduction, and a suggested fix. Focus on behavior/regressions, security and permissions, data loss/migration/compatibility, concurrency/failure handling, missing or misleading tests, documentation drift, and whether untrusted code/workflows can access secrets. Do not report a vague preference as a defect or infer intent/culpability from the contributor's identity.

Check claimed test/CI evidence against the current head. Do not execute untrusted scripts or contact production to investigate. Report what you personally ran, what CI evidence you reviewed, and what remains unverified. Escalate project-owner decisions, permission questions, legal/security exceptions, and merge/release authority according to the project profile; do not take them unilaterally.

Return findings first, highest severity first. If there are no findings, say `No actionable findings` and identify remaining coverage gaps. End with the head SHA and the checks/evidence reviewed. Do not claim that a PR is safe or ready to merge based only on the written description or passing unit tests.

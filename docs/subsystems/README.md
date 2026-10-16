# Subsystem Index

> Bootstrap must generate this index from the target repository's actual runtime responsibilities. The example structure below does not mean the project has these modules; mark unknown or pending boundaries instead of inferring responsibilities from folder names.

A subsystem page answers “how does the current system work, who is responsible for the behavior, and where can it be verified?” It is not a roadmap or implementation plan. Split documentation by stable responsibility boundaries: one subsystem may span multiple directories, and one directory may contain multiple subsystems. Create a separate page only when there is an independent responsibility, data/state contract, or boundary that is easy to modify incorrectly; avoid one document per file.

## Subsystem List (Fill After Initialization)

| Subsystem | Current responsibility / boundary | Authoritative documentation |
| --- | --- | --- |
| `BOOTSTRAP REQUIRED` | Fill in current responsibilities and what it does not cover | Copy [`TEMPLATE.md`](TEMPLATE.md) and change it into a real subsystem page |

## Modification Protocol

Before changing a subsystem, first read its page and the code standards, API/configuration contracts, and tests linked from it. If a change alters an entry point, call path, storage, state transition, dependency boundary, error/fallback behavior, permissions, security defaults, or compatibility, update the corresponding page and this index in the same change. Documentation describes verified current behavior; mark future ideas as proposals separately instead of mixing them with facts.

When describing a semantic change, state the trigger or input and set out the observable behavior before and after the change. Separately identify whether interfaces, state, compatibility, and failure behavior changed (yes/no/unknown); dimensions unrelated to this change need not be expanded, while unexamined dimensions remain `UNKNOWN` rather than being obscured by general wording.

Every important behavior should be traceable to a source path, public interface/configuration, or test. Use relative links and point to stable files and symbols where possible; if the repository supports line links and they will not drift frequently, line numbers may be added. Do not copy long code listings or write only abstract slogans. Keep concrete acceptance commands in `docs/project-profile.md` / `docs/code-standards.md`; pages retain only targeted verification relevant to that subsystem.

## How to Verify

- Every entry should have a concrete owner/implementation path and verification evidence, avoiding vague statements such as “handled by the backend.”
- Documentation links must exist in the repository; test commands must come from existing scripts, workflows, or maintainer confirmation.
- For critical paths, check state changes, failure branches, and compatibility rather than documenting only the success path.
- If a responsibility boundary is disputed, retain established facts, mark it `UNKNOWN`, and ask the project owner to confirm; do not split or merge modules on your own.

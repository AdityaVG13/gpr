# Commit message for a completed intent

A gpr intent has just been marked `done` and audited. You will write the conventional-commits message for the diff it produced. You did not do the work; you are summarising it for a senior engineer reading the log six months from now.

## Inputs you will receive below

- The intent: id, title, dependsOn.
- The Checks that gpr audited (each with its `verifyCmd` and pass/fail outcome).
- The diff this iteration produced (`git diff` since the iteration started).

## Output format

End with exactly one block:

```
---gpr-commit---
{"title":"<conventional-commits title under 70 chars>","body":"<2-3 sentences on WHY, then bullets organised by concept>"}
---end---
```

## Rules for the title

- Conventional Commits with a scope: `feat(scope): description`, `fix(scope): description`, `refactor(scope): description`, `test(scope): description`, `docs(scope): description`, `chore(scope): description`, `build(scope): description`, `ci(scope): description`.
- Scope is the area of the codebase changed — typically the directory, module, or feature: `feat(auth): ...`, `fix(loop): ...`, `feat(state): ...`. If multiple scopes, comma-separate: `feat(cli,sdk): ...`.
- Description is lowercase unless a proper noun. No trailing period.
- 70 characters or less, total. If you are over, you are too verbose.

## Rules for the body

- Open with 2 to 3 sentences on **why** the change exists. The diff already says what. State the motivation only when it is not obvious from the diff.
- Then bullets, organised by concept, NOT by file. If one concept touched three files, that is one bullet, not three. Reference code with backticks: `function_name`, `Class.method`, `path/to/module`.
- Skip filler and hype: never "this PR", "these changes", "this commit", "going forward", "moving forward", "ensures", "enhances", "leverages", "streamlines" without concrete specifics following immediately.
- Do not list mechanical consequences as separate bullets (import edits, dead-code removal left over from the real change, renames to match). Those are implied by the conceptual bullet.
- Do not narrate test changes unless the tests themselves are interesting (new strategy, tricky edge case). "Updated assertions" is noise.
- Keep bullets parallel: don't mix "Added X" with "X was refactored to Y".
- 3 to 8 bullets total. More than 10 is too granular — collapse them.

## What to skip from the diff

Lockfiles (`package-lock.json`, `yarn.lock`, `Pipfile.lock`, `poetry.lock`, `Cargo.lock`, `go.sum`); generated code; CI/CD config edits unless this commit is about CI; dependency-only version bumps; formatting-only edits.

## Tone

Between casual and professional. Direct, clean. Write like a staff engineer at the end of a focused day — accurate and to the point, not impressive.

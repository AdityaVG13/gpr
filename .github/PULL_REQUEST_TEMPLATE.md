<!-- Suggested title: type(scope): description (Conventional Commits). -->

<!--
2-3 sentences on WHY this change exists. The diff already says what. Skip filler.
Don't start with "This PR" / "These changes" / "This commit".
-->

## Changes

<!--
Conceptual bullets, organised by concept. If one concept touched three files,
that is one bullet — not three. Reference code with backticked names:
`function_name`, `Class.method`, `path/to/module`.
-->

-

## Testing

<!--
Only include this section if the test approach is interesting (new test
strategy, tricky edge case). Routine test updates are noise; skip them.
-->

## Checklist

- [ ] `pytest tests/ -q` passes locally
- [ ] `tests/e2e_dryrun.sh` passes locally
- [ ] `gpr lint` clean if Plan files were modified
- [ ] No new dependencies (or justification provided in the description)
- [ ] CHANGELOG.md updated if user-visible behaviour changed

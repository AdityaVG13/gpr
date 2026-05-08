# Contributing to gpr

Thanks for considering a contribution. This is a small project where each addition is reviewed by hand; please read this first.

## Ground rules

- The CLI is the canonical interface. The Claude skill is a thin wrapper. Any new feature should be exposed through the CLI first; the skill follows.
- The state machine lives in `lib/state/`. Each module has a small public surface and a deep implementation. New state primitives should follow the same shape: a handful of free functions over plain dicts, atomic save via tmp + rename, locking via `lib/state/lock.py`.
- No new dependencies in `pyproject.toml` without a clear justification. Standard library only is the default.
- Tests are required for every state-affecting change. Run `pytest tests/ -q` before opening a PR.
- The e2e dry-run (`tests/e2e_dryrun.sh`) must pass.

## Adding an agent backend

1. Add a builder function `agent_<name>` to `lib/agents.sh`. It reads the prompt on stdin and prints raw stdout; it writes a stream log to its first arg; it respects a per-iteration timeout passed as the second arg.
2. Register the name in `agent_supports()` and `agent_run()` switch statements in the same file, plus `agent_model_id()` for cost accounting.
3. If the agent emits a parseable token-usage stream, add a parser to `lib/state/budget.py` and register it in `PARSER_REGISTRY`.
4. Add a per-model entry to `DEFAULT_RATES_USD_PER_MTOK` so cost accounting works.
5. Add a doctor check by extending `cmd_doctor` in `lib/cli.py`.
6. Add at least one test in `tests/test_budget.py` for the parser.

## Writing a good check

The audit is only as strong as its `verifyCmd`. Before merging a Plan that gpr will run, lint it:

```bash
gpr lint
```

Avoid these anti-patterns:

- `test -f path` alone — proves existence, not correctness.
- `grep -q "TODO"` — passes on the literal substring.
- A test the agent can write and tune to its own implementation.
- `|| true`, `; true`, `; exit 0` — silently masks failure.

Prefer:

- A real test runner (`pytest`, `vitest`, `cargo test`) targeting a specific test name.
- A curl + jq combination that asserts a concrete response shape.
- A grep that requires a *behavioural* string (`grep -q "200 OK" access.log`), not a placeholder.
- Multiple chained checks where the second inspects what the first produced.

## Pull request style

Read `install/commands/gpr.md` for the kind of structured output gpr expects from the agent — that same discipline applies to PR descriptions:

- Conventional Commits in the title with a scope: `feat(state): ...`, `fix(loop): ...`, `docs: ...`, `test: ...`. Title under 70 characters.
- Body opens with two or three sentences on **why**, not what. The diff already says what.
- Bullet list of conceptual changes, organised by concept, not by file. If one concept touched three files, that is one bullet.
- A "Testing" section only if the test approach is interesting.
- Skip filler: "this PR adds", "going forward", "leverages", "streamlines", "ensures" without specifics.

A good PR description is shorter than a bad one.

## Reporting issues

Please include:

- The output of `gpr doctor`.
- The exit code from your last `gpr run`.
- A redacted copy of `.gpr/runs/<id>/iter-<NN>/prompt.md` and `signal.json` if the issue is loop-related.
- The agent and model you used.

Issues without reproduction steps may be closed with a request for more information.

## License

By contributing you agree your contributions are licensed under [Apache 2.0](LICENSE), the project's license.

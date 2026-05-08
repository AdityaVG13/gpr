---
name: Bug report
about: Something gpr did wrong
labels: bug
---

## What happened

<!-- 1-2 sentences. -->

## Reproduction

```bash
# the exact commands you ran
```

## Expected vs actual

<!-- What did you expect? What did gpr do instead? -->

## Environment

- gpr version: <run `gpr version`>
- `gpr doctor` output:
  ```
  ```
- agent + model: <e.g. claude / claude-opus-4-7>
- OS:

## Artifacts

If the issue is loop-related, please attach a redacted copy of:

- `.gpr/runs/<id>/iter-<NN>/prompt.md`
- `.gpr/runs/<id>/iter-<NN>/signal.json`
- `.gpr/runs/<id>/iter-<NN>/audit.json` (if present)

Run them through `python3 -c "import sys; from lib.state.redact import redact; print(redact(sys.stdin.read()))"` first if you're unsure.

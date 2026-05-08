# Reverse audit (spec-drift sweep)

This audit runs at the end of a successful run, before declaring `achieved`. Its purpose is the inverse of the per-iteration audit: instead of asking "did you build what the plan says?", it asks "does the plan still describe what you built?".

## Inputs

- The full Plan (`.gpr/Plan.json`) — all intents currently `done`.
- The complete diff from run start to current state.
- The `.gpr/Spine.md`.

## Sweep, per intent

For each intent currently `done`:

1. Re-run its checks' verifyCmds. Any that now fail is a regression — the intent must be reopened with an `auditFailures` entry.
2. Read the intent's title and description. Compare against the actual code paths the diff touched. If the intent says "build X" but the implemented code does X-prime that's notably different, flag for `rescope` review.

## Sweep, against the goal

Re-read the goal. Ask: if a stranger read the goal, would they look at the current repository state and agree the goal is met? List concrete features the goal implies that are absent in the diff. These are gaps the per-iteration audit could not catch because they fell between intent boundaries.

## Verdict

```
---gpr-reverse-audit---
{"clean":true|false,"regressions":[{"intent":"<id>","check":"<id>","reason":"..."}],"goal_gaps":["<short text>"],"recommendation":"declare_achieved" | "reopen_intents" | "add_intents" | "rescope"}
---end---
```

`declare_achieved` means: full pass, no regressions, no goal gaps. The run can mark its `status: achieved`.

`reopen_intents` means: regressions found; reopen the listed intents and continue the loop.

`add_intents` means: the goal has unfilled requirements that no current intent covers; surface them as proposed new intents for the human to approve.

`rescope` means: the work has diverged from the plan badly enough that the plan itself should be revised before continuing.

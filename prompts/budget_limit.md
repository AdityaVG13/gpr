# Budget wrap-up

The current run has crossed the soft-stop threshold (95% of the binding budget axis: tokens, wall-clock, or USD).

**Do not start substantive new work this iteration.** Specifically:

- Do not begin implementing a new check that wasn't already in progress.
- Do not refactor anything that is currently working.
- Do not propose architectural changes.

What to do instead, in order:

1. Summarize what has been accomplished against the goal (which intents are `done`, what evidence exists for them).
2. Identify what remains: which intents are still `open` or `in_progress`, which checks are missing proof.
3. Surface any blockers that the next run (with fresh budget) should know about — write these into `.gpr/Spine.md` so they survive into the next run.
4. If there is one trivially small remaining task (under ~5 minutes of work) that, if completed, would make a substantial intent flip to done, finish it. Otherwise stop.

Emit `progress` (not `done`) unless an intent's audit will genuinely pass. The wrap-up turn cannot mark intents done — the state machine refuses that transition while `wrapUpFlag` is set.

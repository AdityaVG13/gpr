# Stall recovery

The loop has detected that the last several iterations produced no movement on either axis (no payload-hash change AND no checkbox-count change). Same-signature counter has crossed the threshold.

This iteration receives a **case-split stall note** — see the prompt section labeled "STALL NOTE". The note tells you which of four failure shapes you are showing:

- **no-op** — neither code nor plan moved. You are spinning on description.
- **code-without-plan-update** — you wrote code but did not reflect it in `.gpr/Spine.md` or update any check.
- **plan-without-code** — you marked checkboxes done without changing code. Most dangerous; revert and either do the work or emit `blocked`.
- **both-but-no-signature-change** — you are likely flapping (edit, revert, edit, revert). Halt and inspect.

Recovery rule: pick the **smallest possible concrete subtask** of the current intent that produces a real, observable artifact (a single file, a single test, a single function). Do that one thing. Do not write prose; write code. If the smallest subtask is still too large or unclear, emit `blocked` with a precise reason — that is more useful than another empty iteration.

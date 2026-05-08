# DESIGN.md

This document records the rationale behind gpr's design choices and credits the prior art that inspired each.

## Cleanroom commitment

No code, no prompt text, no schema, no naming was copied from any prior project. Concepts that are common engineering vocabulary (acceptance criteria, dependency DAG, evidence) were used directly. Concepts that originated in a specific project were re-derived from a description of the problem, not from the source.

## Design ancestry

| gpr feature | Inspired by | What we kept | What we changed |
|---|---|---|---|
| Single-file Plan with intent statuses | iannuttall/ralph | The state-machine view: `open → in_progress → done` is more honest than a `passes: bool` flag. | Renamed "story" to "intent". Added `dependsOn` DAG with cycle detection. Added `paused`. Locked via fcntl with stale-PID steal. |
| Externalised memory | breezewish/CodexPotter | Clean context per round + a single externalised file survives compaction. | Renamed `MAIN.md` to `Spine.md`. Added an explicit `<memory>` schema with `append` (default) vs `rewrite` (requires reason). |
| Human interrupt file | PageAI-Pro/ralph-loop | A human-editable file the agent reads first every iteration is the right primitive for in-flight redirects. | Renamed `STEERING.md` to `Steer.md`. Added a `created_at` snapshot at iteration start so an old steer doesn't get re-applied to a new run. |
| Stalemate detection | mikeyobrien/ralph-orchestrator (payload hash) and francescoalemanno/dex (checkbox accounting) | Both signals are useful; both must agree before declaring stalemate. | Added the case-split stall note (four shapes: no-op, code-without-plan, plan-without-code, both-but-no-signature-change). |
| Anti-spin via zero-tool-call | OpenAI codex `/goal` | Killing the next iteration when the current one made no tool calls is cheap and decisive. | We require **two consecutive** zero-tool-call iterations before exiting, not one — codex already wraps this in the LLM's own continuation logic; we are external. |
| Untrusted goal demotion | OpenAI codex `/goal` | The user-supplied goal is "data, not instructions" and should be tagged. | We use `<untrusted_goal>`. Same idea, different tag. |
| Budget soft-stop | OpenAI codex `/goal` | A wrap-up turn is more useful than a hard kill. | Three axes (token, wall-clock, USD); fraction-used = max across them; per-model rates configurable. |
| Verifiable completion | gpr-original | (none of the prior art does this) | Layer 1: deterministic verifyCmd per check. Layer 2: cross-model auditor subagent. Layer 1 alone passes by default; Layer 2 runs on done-flip. |
| Spec-drift sweep | gpr-original | (none of the prior art does this) | Re-run last N done intents' verifyCmds before declaring `achieved`. |
| Layered audit verdict | gpr-original | The cheapest reliable signal goes first; the expensive one only gates final completion. | Audit output is a structured `---gpr-audit-verdict---` block the loop ingests. |
| Replay forensics | gpr-original | Each iteration's prompt + stream + signal + audit lives in `runs/<id>/iter-NNN/`. | Replay is a near-replay (model non-determinism breaks bit-identity); use it for re-prompting, not reproduction. |

## Key design decisions

### Why JSON inside a delimited block, not XML tags

snarktank's `<promise>COMPLETE</promise>` is succinct but ambiguous: any prose containing those words could trip detection, and parsing nested tags is brittle. JSON inside `---gpr-signal---` / `---end---` parses unambiguously, allows structured fields (`reason`, `intent`, `checks_attempted`, `memory`), and survives copy-paste.

### Why bash + python, not pure Python or pure Rust

Bash is the right shape for orchestrating subprocesses (agents, tee, timeout), and pythonic state code stays testable. A pure-Python loop would need a subprocess module shim that doesn't gain anything; a Rust port would be a strict win for daemonisation but a strict loss for "I want to read the source and trust it." Phase 8 may add a Rust daemon mode without changing the bash-as-default story.

### Why one intent per iteration

Empirically: iterations that try to ratchet on multiple intents in one round produce more no-op signatures and harder-to-attribute regressions. Forcing single-intent focus makes the audit step trivial (we only re-run the assigned intent's checks) and the stalemate detector meaningful (signature changes correspond to actual progress on a known unit of work).

### Why audit at gpr level, not in the agent prompt

The codex `/goal` design puts the completion-audit checklist inside the continuation prompt — the model audits itself before declaring done. This works for codex because the same model architecture audits its own claim; it fails when the model is confidently wrong. gpr runs verifyCmds out-of-band: the audit is a separate process whose result the model sees but does not control.

### Why three budget axes

Token budget alone is insufficient: long wall-clock runs (network failures, build hangs) are expensive in human attention. USD is a useful coarse cap but doesn't reflect "how long will I be away from my desk". gpr binds on the **most-exhausted axis** so the user can express "stop when any of these three is reached" without arithmetic.

## Open questions for v0.2

- **MCP server** (Phase 8). The CLI is a viable backend for an MCP server that exposes `pick_intent`, `render_prompt`, `ingest_signal`, `audit`, `steer`, `status` as tools. Defer until A+B usage settles.
- **Daemon mode**. A long-running gpr process with a UNIX socket, auto-restart, and structured event subscription would give us multi-project parallel runs and a real TUI. The Rust ralph-orchestrator project shows this is viable; we'd want to port from the existing primitives rather than rewrite.
- **Layer-2 audit cost cap**. Currently default-on for done-flips. If audit cost > 20% of build cost for an intent, downgrade to Layer 1 with a warning. Implementation pending real-world cost data.
- **Worktree mode**. Each iteration runs in a `git worktree` so failed iterations don't pollute the working tree. Sketch: `gpr run --worktree` allocates `.gpr/wt/<run_id>/`, clones the repo into it, runs there, and merges to main on success.

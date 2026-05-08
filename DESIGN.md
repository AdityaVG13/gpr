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
| Verifiable completion | gpr-original | (none of the prior art does this) | Layer 1: deterministic verifyCmd per check. Layer 2: cross-model auditor subagent. Layer 1 alone passes by default; Layer 2 runs on done-flip when `--deep-audit`. |
| Spec-drift sweep | gpr-original | (none of the prior art does this) | Re-run last N done intents' verifyCmds before declaring `achieved`. Wired into `loop_reverse_audit` at end-of-run. |
| Layered audit verdict | gpr-original | The cheapest reliable signal goes first; the expensive one only gates final completion. | Audit output is a structured `---gpr-audit-verdict---` block the loop ingests. |
| Replay forensics | gpr-original | Each iteration's prompt + stream + signal + audit lives in `runs/<id>/iter-NNN/`. | Replay is a near-replay (model non-determinism breaks bit-identity); use it for re-prompting, not reproduction. |
| Beat-by-beat spec interview | mattpocock/skills `grill-with-docs` | The shape: ask one question at a time, refuse hand-waving, build up CONTEXT.md inline as decisions crystallise. | Cleanroom rewrite as `gpr-grill` with nine beats specific to PRD construction (persona, goal lock, success metric, tech stack, anti-goals, decomposition, checks, budget, confidence audit). Refusal rules tuned for `verifyCmd` quality. |
| Confidence-audit loop | gpr-original (motivated by user prompt "are you 100% confident?") | (none of the prior art does this) | An adversarial scrutiniser agent inspects the draft Plan for eight categories of loophole, emits a structured verdict, and the loop iterates until `confident: true` or the user waives. |
| Persona priming | Cognitive-priming research synthesis (ExpertPrompting + RLHF instruction-bias literature) | Senior-dev role activation lifts mid-tier model output into expert registers; constraints belong at the *end* of the prompt because of recency bias in long-context reasoning. | Four registered personas (`principal_engineer`, `senior_architect`, `rapid_prototyper`, `research_partner`) selected per-Plan in Beat 0. Continuation prompt restructured with PERSONA at top, RULES + FINAL CONSTRAINT at bottom. Auditor prompts (Layer-2, reverse, confidence) each get their own suspicious / fresh-eyed prime. |
| Conventional commits with scope + conceptual bullets | mdrxy `staged-pr` skill (gist) | The discipline: scoped Conventional Commits, conceptual bullets organised by concept (not by file), explicit anti-pattern list (no "this PR…", no "going forward", no "leverages" without specifics), noise filter (skip lockfiles, generated code, dependency bumps). | Cleanroom rewrite as `gpr commit-intent` and `gpr pr-description` with their own prompts and structured `---gpr-commit---` / `---gpr-pr---` parser blocks. Title length capped at 100 chars in the parser to catch runaway models early. |
| Interactive single-file spec viewer | gpr-original (research-driven) | The shape: a static HTML file with editorial typography that *also* supports keyboard nav, deep linking, filtering, copy-to-clipboard, theme toggle, current-section highlight. | Sticky TOC with completion glyphs (`○ ◐ ●`) computed from check proofs; URL-hash deep linking (`#intent-I003`); filter chips with localStorage persistence per-Plan; keyboard nav (`j`/`k`/`/`/`?`); inline copy buttons on every `verifyCmd`; three themes (paper / sepia / dark); print stylesheet that expands all collapsed sections. Vanilla JS, no framework, ~400 LOC. |

## Key design decisions

### Why JSON inside a delimited block, not XML tags

snarktank's `<promise>COMPLETE</promise>` is succinct but ambiguous: any prose containing those words could trip detection, and parsing nested tags is brittle. JSON inside `---gpr-signal---` / `---end---` parses unambiguously, allows structured fields (`reason`, `intent`, `checks_attempted`, `memory`), and survives copy-paste. The same pattern extends to four other structured channels: `---gpr-audit-verdict---` (Layer-2), `---gpr-reverse-audit---` (end-of-run), `---gpr-confidence-audit---` (Plan validation), `---gpr-commit---` and `---gpr-pr---` (commit/PR generators).

### Why bash + python, not pure Python or pure Rust

Bash is the right shape for orchestrating subprocesses (agents, tee, timeout), and pythonic state code stays testable. A pure-Python loop would need a subprocess module shim that doesn't gain anything; a Rust port would be a strict win for daemonisation but a strict loss for "I want to read the source and trust it." Phase 8 may add a Rust daemon mode without changing the bash-as-default story.

### Why one intent per iteration

Empirically: iterations that try to ratchet on multiple intents in one round produce more no-op signatures and harder-to-attribute regressions. Forcing single-intent focus makes the audit step trivial (we only re-run the assigned intent's checks) and the stalemate detector meaningful (signature changes correspond to actual progress on a known unit of work).

### Why audit at gpr level, not in the agent prompt

The codex `/goal` design puts the completion-audit checklist inside the continuation prompt — the model audits itself before declaring done. This works for codex because the same model architecture audits its own claim; it fails when the model is confidently wrong. gpr runs verifyCmds out-of-band: the audit is a separate process whose result the model sees but does not control. The Layer-2 audit goes one step further and asks a *different* model whether the Layer-1 verifyCmds were actually load-bearing or whether they could be gamed.

### Why three budget axes

Token budget alone is insufficient: long wall-clock runs (network failures, build hangs) are expensive in human attention. USD is a useful coarse cap but doesn't reflect "how long will I be away from my desk". gpr binds on the **most-exhausted axis** so the user can express "stop when any of these three is reached" without arithmetic.

### Why personas and why at the top

Cognitive-priming research shows that role assignment shifts a model's output register toward the statistical sub-distribution associated with that role's training data. ExpertPrompting work suggests mid-tier models can reach ~96% of frontier capability on technical tasks when primed as expert architects. The cost is a few hundred tokens per prompt, dwarfed by the quality lift. The persona block goes at the very top of the continuation prompt to be the first thing the model conditions on; the hard constraints go at the very *bottom* because Gemini-class models in long-context reasoning loops anchor harder on the last block of the prompt than the first.

### Why the confidence audit loops

A draft Plan is not a contract. The user prompt that motivated this feature was: "Are you 100% confident in this strategy? If not, find all possible loopholes, suggest proper fixes, and run this loop until you are factually 100% confident." That maps directly to the eight-category scrutiny pass and the iterate-until-confident loop in `gpr confidence-audit`. The cost (one extra agent invocation per Plan) is paid once per Plan, not once per iteration; the value is avoiding wasted runs against a Plan with gameable verifyCmds or DAG cycles.

## Open questions for v0.2

- **MCP server** (Phase 8). The CLI is a viable backend for an MCP server that exposes `pick_intent`, `render_prompt`, `ingest_signal`, `audit`, `steer`, `status` as tools. Defer until A+B usage settles.
- **Daemon mode**. A long-running gpr process with a UNIX socket, auto-restart, and structured event subscription would give us multi-project parallel runs and a real TUI. The Rust ralph-orchestrator project shows this is viable; we'd want to port from the existing primitives rather than rewrite.
- **Layer-2 audit cost cap**. Currently opt-in via `--deep-audit`. If audit cost > 20% of build cost for an intent, downgrade to Layer 1 with a warning. Implementation pending real-world cost data.
- **Worktree mode**. Each iteration runs in a `git worktree` so failed iterations don't pollute the working tree. Sketch: `gpr run --worktree` allocates `.gpr/wt/<run_id>/`, clones the repo into it, runs there, and merges to main on success.
- **Confidence-audit auto-revise**. The loop currently surfaces loopholes for the user to apply manually. A future version applies the proposed `fix:` strings to Plan.json automatically under fcntl and re-runs the audit, exiting only when confident or after N attempts.
- **Server mode for the HTML viewer**. The current viewer is a static file. A `gpr serve` mode would add live event polling (Server-Sent Events), inline edit endpoints for Plan.json under fcntl, and multi-user presence. Roadmap.

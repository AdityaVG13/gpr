# gpr — Goal-driven PRD Ratchet

Audit-verified iterative agent loop. Hand it a goal and a Plan; it ratchets toward done with evidence at every step.

## What it is

A robust loop runner that drives an LLM coding agent (Claude Code, Codex, OpenCode, Gemini) through a structured Plan toward a stated objective — with hard guarantees that the loop only marks work `done` when real artifacts pass real checks.

## Why

The naive "ralph loop" pattern (`while true: claude -p prompt.md`) has known failure modes: the model self-reports completion, context grows until compaction garbles it, runs hang silently, and any disturbance loses state. `gpr` fixes each:

| Failure | gpr fix |
|---------|---------|
| Model lies about completion | Layer-1 `verifyCmd` per check + Layer-2 cross-model auditor subagent |
| Context compaction garbles state | Clean session each round; externalized memory in `Spine.md` |
| Silent hang | Per-iter wall-clock timeout + retry with exp backoff |
| No-op spin | Zero-tool-call detector + N-iter stalemate kill-switch with case-split stall notes |
| State lost on crash | fcntl-locked `Plan.json` + `STALE_SECONDS` reset + crash forensics in `runs/` |
| No human-in-loop | `Steer.md` mid-flight interrupt; `gpr steer "..."` writes to it |
| Budget runaway | Token + wall-clock + USD soft-stop with wrap-up turn |
| Architectural rescope | `RESCOPE` signal triggers planner subagent → `proposed_plan.json` for human review |
| Spec drift | Per-iter evidence sweep on last-N closed checks; regressions reopen |
| Prompt injection | User goal wrapped in `<untrusted_goal>` tag in continuation prompt |

## Status

**Alpha.** API and signal grammar are stabilizing. Used internally; opening to public feedback.

## Install

```bash
git clone https://github.com/AdityaVG13/GPR ~/.local/share/gpr
ln -sf ~/.local/share/gpr/bin/gpr ~/.local/bin/gpr
gpr doctor
```

Requires: Python 3.10+, bash 5+, at least one of: `claude`, `codex`, `opencode`, `gemini` on `$PATH`.

## Quickstart

```bash
cd my-project
gpr init --objective "Build a TODO REST API with auth"
$EDITOR .gpr/Plan.json     # add intents and checks
gpr run --agent claude --max-cost-usd 5
```

Mid-run, redirect:

```bash
gpr steer "Switch from sqlite to postgres"
```

When done:

```bash
gpr status
gpr audit --deep    # cross-model verify
```

## Concepts

- **Goal** — a single sentence stating what success looks like.
- **Intent** — a discrete unit of work toward the goal (what other tools call a "story" or "task"). Has a status: `open | in_progress | done | paused`.
- **Check** — an acceptance criterion attached to an intent. Has a `verifyCmd` that gpr runs to confirm the check actually holds.
- **Proof** — recorded evidence that a check passed: command exit, file fingerprint, screenshot, etc.
- **Signal** — structured trailer block emitted by the agent at the end of each iteration. Tells gpr what just happened: `done`, `blocked`, `decide`, `rescope`, `task-progress`, `memory-update`.
- **Spine.md** — externalized memory; the model rewrites it as needed; survives clean-context rounds.
- **Pinned.md** — read-only invariants the model is told never to overwrite.
- **Steer.md** — human-editable interrupt file; agent reads first every iteration.

## Signal grammar

At the end of every iteration, the agent emits one trailer block:

```
---gpr-signal---
status: done | blocked | decide | rescope | progress
reason: <human text>          # for blocked / decide / rescope
intent: <ID>                  # which intent this iteration touched
checks_attempted: [<AC-ID>, ...]
memory:
  mode: append | rewrite      # default: append
  content: |
    <new spine entry>
---end---
```

`gpr` parses, validates, then runs Layer-1 audit on `checks_attempted` before flipping any intent to `done`. Models cannot self-promote intents to `done` — only the audit can.

## Stop conditions

| Exit code | Status | Meaning |
|----------:|--------|---------|
| 0 | `achieved` | All intents `done`, all quality gates green, reverse-audit clean |
| 2 | `blocked` | Agent emitted `blocked` signal; left for human |
| 3 | `decide` | Agent emitted `decide` signal; question written to `Steer.md` |
| 4 | `budget_limited` | Budget exhausted; final wrap-up turn ran |
| 5 | `unmet_zero_progress` | Two consecutive iters with no meaningful tool calls |
| 6 | `unmet_stalemate` | N iters with no payload-hash + checkbox movement |
| 7 | `rescope` | Agent proposed a plan rewrite; awaiting human review |
| 8 | `unmet_disk_full` | <1GB free at iter start |
| 9 | `crashed` | Loop or child process died; state preserved in `crashed/` |

## Comparison

|  | snarktank/ralph | iannuttall/ralph | PageAI/ralph-loop | codex `/goal` | **gpr** |
|---|---:|---:|---:|---:|---:|
| Verifiable completion | ❌ | ❌ | ❌ | ✅ (self-audit) | ✅ (cross-model) |
| Anti-spin | ❌ | ❌ | ❌ | ✅ | ✅ |
| Compaction-immune | ❌ | ❌ | ⚠ | ✅ | ✅ |
| Crash-resumable | ⚠ | ✅ | ⚠ | ✅ | ✅ |
| Human-in-loop | ❌ | ❌ | ✅ | ❌ | ✅ |
| Budget-governed | ❌ | ❌ | ❌ | ✅ | ✅ |
| Multi-agent | ⚠ | ✅ | ✅ | ❌ | ✅ |
| Spec-drift sweep | ❌ | ❌ | ❌ | ❌ | ✅ |
| Replay forensics | ❌ | ❌ | ❌ | ❌ | ✅ |

## Cleanroom

`gpr` was designed after surveying the prior art (snarktank/ralph, iannuttall/ralph, PageAI-Pro/ralph-loop, mikeyobrien/ralph-orchestrator, francescoalemanno/dex, breezewish/CodexPotter, openai/codex `/goal`). All concepts re-derived independently; no code or prompt text was copied. Specific design ancestry credited in [DESIGN.md](DESIGN.md).

## License

Apache 2.0. See [LICENSE](LICENSE).

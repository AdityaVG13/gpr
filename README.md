# gpr

**Goal-driven PRD Ratchet.** An agent loop that only marks work done when real artifacts pass real checks.

```bash
gpr init --objective "Build a TODO REST API with auth"
$EDITOR .gpr/Plan.json
gpr run --agent claude --max-cost-usd 5
```

That's the whole UX. From there gpr drives Claude (or Codex, OpenCode, Gemini) through your Plan, intent by intent, until either every check has evidence on disk or the loop hits a stop condition you defined: a budget, a stalemate, a blocked dependency, a human steer.

---

## Why this exists

The naive ralph loop — `while true: claude -p prompt.md` — has five well-known failure modes. gpr fixes each one structurally, not by hoping the model behaves.

| Failure mode | What goes wrong | gpr's fix |
|---|---|---|
| Self-reported completion | Model says it's done; it isn't | Layer-1 `verifyCmd` per check + Layer-2 cross-model auditor |
| Context compaction | Mid-run context grows past the window; state is lost | Clean session every iteration; memory externalised in `Spine.md` |
| Silent hangs | Agent CLI freezes; loop blocks | Per-iteration wall-clock timeout with retry and exponential backoff |
| No-op iterations | Agent emits prose, no real changes | Two-layer detector: zero meaningful tool calls, plus payload-hash + checkbox stalemate |
| Lost human control | Need to kill and restart to redirect | `gpr steer "..."` writes to `Steer.md`; the agent reads it first every round |

There's also a budget governor (token + wall-clock + USD with soft-stop wrap-up), a spec-drift sweep that re-runs old verifyCmds against the current state, and a `RESCOPE` signal for when the agent decides the plan itself is wrong.

---

## Two ways to invoke

**Mode A — CLI.** `gpr run` drives the loop as an external process. Best for autonomous overnight runs, headless servers, CI.

**Mode B — Claude Code skill.** `/gpr` runs one iteration inside your current Claude TUI session. The CLI is the canonical state machine; the skill borrows your active session as the worker. Same state on disk, two front doors.

```bash
# install Mode B
~/Developer/gpr/install/install.sh
# then in any Claude Code session inside a gpr-initialised project:
/gpr            # runs one iteration, then yields
/gpr-status     # progress + budget burn
/gpr-steer ...  # write a human steer
```

Mode C (MCP server, accessible from Codex / Cursor / any MCP client) is on the roadmap once usage patterns settle.

---

## How it works

### Concepts

- **Goal** — one sentence describing what success looks like.
- **Intent** — a discrete unit of work toward the goal. Statuses: `open`, `in_progress`, `done`, `paused`. Intents can declare `dependsOn` to form a DAG; gpr enforces topological order.
- **Check** — an acceptance criterion attached to an intent, with a `verifyCmd` gpr runs to confirm the check actually holds.
- **Proof** — recorded evidence that a check passed: command exit, file fingerprint, screenshot, manual sign-off.
- **Signal** — structured trailer block emitted by the agent at the end of each iteration. Tells gpr what happened: `done`, `progress`, `blocked`, `decide`, or `rescope`.
- **Spine.md** — externalised memory; the agent rewrites it as decisions crystallise; survives clean-context rounds.
- **Pinned.md** — read-only invariants; the agent is told never to overwrite this file.
- **Steer.md** — human-editable interrupt; the agent reads it first every iteration.

### One iteration

```
1. Read Steer.md         (if non-empty, do that work and clear it)
2. Pick next intent      (continue an in-progress one if any; else priority+deps)
3. Render the prompt     (goal in <untrusted_goal> tag, intent block, pinned, spine, errors, budget, signal grammar)
4. Spawn the agent       (clean session, per-iter timeout, stream parsed for tokens)
5. Parse the signal      (refuse to mark done without an explicit signal)
6. Run audit             (Layer 1 verifyCmd; on failure, revert to open + log)
7. Update signature      (payload-hash + checkbox count for stalemate detector)
8. Decide stop condition (achieved | blocked | decide | rescope | budget_limited | stalemate | zero_progress)
```

### Signal grammar

```
---gpr-signal---
{"status":"done","intent":"I001","checks_attempted":["C1","C2"],
 "memory":{"mode":"append","content":"Decided on JWT over sessions because ..."}}
---end---
```

`status` ∈ `{done, progress, blocked, decide, rescope}`. `done` only flips an intent if the audit passes — the agent cannot self-promote.

### Stop conditions

| Exit | Status | Meaning |
|---:|---|---|
| 0 | `achieved` | All intents done, quality gates green, reverse audit clean |
| 2 | `blocked` | Agent emitted `blocked`; left for human |
| 3 | `decide` | Agent emitted `decide`; question written to `Steer.md` |
| 4 | `budget_limited` | Budget exhausted; final wrap-up turn ran |
| 5 | `unmet_zero_progress` | Two consecutive iterations with no meaningful tool calls |
| 6 | `unmet_stalemate` | Four iterations with no signature change |
| 7 | `rescope` | Agent proposed a plan rewrite; awaiting human review |
| 8 | `unmet_disk_full` | Less than 1GB free at iteration start |

---

## Compared to prior art

|  | snarktank/ralph | iannuttall/ralph | PageAI/ralph-loop | codex `/goal` | gpr |
|---|---:|---:|---:|---:|---:|
| Verifiable completion | regex only | regex only | regex only | model self-audit | cross-model audit |
| Anti-spin guard | no | no | no | yes | yes |
| Compaction-immune | no | no | partial | yes | yes |
| Crash-resumable | partial | yes | partial | yes | yes |
| Human-in-loop | no | no | yes | no | yes |
| Budget-governed | no | no | no | yes | yes |
| Spec-drift sweep | no | no | no | no | yes |
| Multi-agent | partial | yes | yes | no | yes |
| Replay forensics | no | no | no | no | yes |

---

## Install

```bash
git clone https://github.com/AdityaVG13/GPR ~/.local/share/gpr
ln -sf ~/.local/share/gpr/bin/gpr ~/.local/bin/gpr
gpr doctor
```

Requirements: Python 3.10+, bash 5+, git, jq, plus at least one of: `claude`, `codex`, `opencode`, `gemini` on `$PATH`. Run `gpr doctor` to confirm.

For the Claude skill:

```bash
~/.local/share/gpr/install/install.sh
```

This copies `SKILL.md` to `~/.claude/skills/gpr/` and registers the `/gpr`, `/gpr-status`, `/gpr-steer` slash commands.

---

## Reference

- [SKILL.md](install/skill/SKILL.md) — exact instructions Claude follows for one iteration
- [DESIGN.md](DESIGN.md) — design rationale and credit to prior art
- [CONTRIBUTING.md](CONTRIBUTING.md) — how to add an agent backend, write a check, or propose a feature
- [CHANGELOG.md](CHANGELOG.md) — release notes

---

## Cleanroom statement

gpr was designed after surveying snarktank/ralph, iannuttall/ralph, PageAI-Pro/ralph-loop, mikeyobrien/ralph-orchestrator, francescoalemanno/dex, breezewish/CodexPotter, and the OpenAI codex `/goal` implementation. All concepts were re-derived independently; no prompt text or source code was copied from any of these projects. The `<untrusted_goal>` framing, the `Steer.md` interrupt file, the case-split stall notes, the payload-hash signature detector, and the cross-model Layer-2 auditor each draw on prior art for inspiration but were rewritten from first principles. Specific design ancestry is credited in [DESIGN.md](DESIGN.md).

---

## License

[Apache 2.0](LICENSE).

Copyright 2026 Aditya and contributors.

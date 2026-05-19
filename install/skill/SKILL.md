---
name: gpr
description: Run one iteration of the gpr (Goal-driven PRD Ratchet) audit-verified loop in the CURRENT Claude session, OR hand the loop off to the `gpr run` CLI driver via `/gpr loop`, OR fold an external Plan into the project via a filepath argument. Trigger when user types /gpr, /gpr next, /gpr ratchet, /gpr loop, /gpr run, /gpr <path-to-plan-file>, "run gpr iteration", "run the loop", or asks to drive an existing Plan.json toward done. Do NOT trigger if no Plan exists for the active slug AND no filepath / goal was given — instruct the user to run `gpr init --objective "..."` (or `/gpr-grill`) first. Single-iteration is the default; only the explicit `loop`/`run` subform delegates to the CLI driver.
---

# gpr — one iteration (default), CLI-driven loop, or external-plan import

You are executing **exactly one** iteration of a gpr loop. The gpr CLI is the source of truth for state; you are the worker. After this iteration finishes, yield control to the user — do not auto-continue.

## Routing — filepath import, single iteration, autonomous loop

Inspect the invocation arguments in this order:

1. **Filepath import.** If the first argument looks like a path to a Plan file (`./plan.json`, `~/Drafts/strategy.json`, an absolute path, or any token ending in `.json` / `.md` that resolves on disk), fold it into the project first:

   ```bash
   gpr import "<path>" --activate
   ```

   Capture the slug printed on stdout. Then **continue with single-iteration mode** against that slug — the rest of this file applies, but `--plan <slug>` is appended to every `gpr ...` call. This is how the user folds a hand-written Plan into the .gpr ecosystem.

2. **`/gpr loop`, `/gpr run`, `/gpr auto`**, or user phrases like "run the loop", "run gpr until done" → **autonomous-loop mode**. Jump to the "Autonomous loop" section at the bottom of this file and do NOT execute the six single-iteration steps.

3. **`/gpr`, `/gpr next`, `/gpr ratchet`** (no argument or just `next`/`ratchet`) → **single-iteration mode**. Continue to "Preflight" below. This is the default.

If unsure, ask the user once: "Single iteration (`/gpr`) or hands-off loop (`/gpr loop`)?" Default to single-iteration if the user does not answer.

## Multi-plan — which plan are we ratcheting on?

gpr supports many concurrent named plans under `.gpr/plans/<slug>/`. The active plan is resolved at command time from:

1. `--plan <slug>` argument on the gpr command,
2. `$GPR_PLAN` env var,
3. `.gpr/active` file (one slug per line),
4. fallback `default`.

If the user passes a slug explicitly (`/gpr --plan auth`, `/gpr loop --plan auth`), forward it on every `gpr ...` call. Otherwise the active plan applies automatically; no special handling needed. `gpr plan list` shows what's available; `gpr plan use <slug>` switches the default.

## Preflight (run once, fail fast)

Run `gpr doctor` via Bash. If `gpr` is not on PATH, instruct the user to install it from https://github.com/AdityaVG13/GPR and stop. If the active plan has no `Plan.json` (`gpr status` returns an error), tell the user to either:

- run `gpr init --objective "..."` (or `/gpr-grill`) to scaffold a new Plan, or
- run `gpr import <path>` (or just `/gpr <path>`) if they have an existing Plan file to fold in.

and stop.

## The six steps

### 1. Pick the intent

```bash
gpr next-intent --json
```

Parse the JSON. If `ok: false` and `reason: no_open_intents`, run `gpr status` and report to the user: either the goal is achieved (all intents done) or it's blocked on dependencies. **Stop.**

If `ok: true`, capture `intent.id` and `intent.title`. The CLI has already marked it `in_progress` with a fcntl lock.

### 2. Render the prompt

```bash
gpr render-prompt
```

This prints the full continuation prompt for THIS iteration. **Read it end-to-end before acting.** It contains the goal, the intent, the checks, pinned invariants, prior errors, the spine (externalized memory), and the signal grammar. The rules in that prompt override any default instinct.

### 3. Read the priority files

The rendered prompt instructs you to read these in order — do it. Paths are scoped to the active plan (`.gpr/plans/<slug>/`):

- `.gpr/plans/<slug>/Steer.md` — if non-empty, the human is redirecting you. Do that work first, then `> .gpr/plans/<slug>/Steer.md` to clear it, and emit a `progress` signal. **Skip the rest of this iteration.**
- `.gpr/plans/<slug>/Pinned.md` — read-only invariants. Never overwrite this file.
- `.gpr/plans/<slug>/Spine.md` — externalized memory; what prior iterations decided.
- `.gpr/plans/<slug>/errors.log` — recent failures to avoid.

(The rendered prompt embeds these inline, so you usually don't need to re-read them as separate files.)

### 4. Do the work — one intent only

Use your normal tools (Read, Write, Edit, Bash) to advance THE assigned intent. Don't touch other intents. Don't refactor unrelated code. Before you decide the intent is done:

- For each Check on this intent, point to a concrete artifact (file path, command output, test name) that proves it passes.
- Re-check that you didn't break any already-done intent's checks.
- Mentally re-run the global qualityGates — would they pass right now?

### 5. Emit the signal

The signal must be the **last thing** in your response, on its own line, exactly:

```
---gpr-signal---
{"status":"<one of: done|blocked|decide|rescope|progress>","reason":"<required for blocked/decide/rescope>","intent":"<the intent id>","checks_attempted":["<check ids you tried>"],"memory":{"mode":"append","content":"<short spine entry>"}}
---end---
```

- `done` — you believe the intent is complete. The audit will run verifyCmds; if any fails the intent reverts to open and your `done` is rejected.
- `progress` — work continues; intent stays in_progress for the next iteration.
- `blocked` — you cannot proceed (need creds, missing dep, ambiguous spec). Loop pauses.
- `decide` — you need a human decision. Question is written to Steer.md.
- `rescope` — the plan itself looks wrong. Trigger human review.

### 6. Ingest the signal

After printing the signal block, run:

```bash
gpr ingest-signal --stdin --json <<'EOF'
---gpr-signal---
{...the same JSON you emitted...}
---end---
EOF
```

This parses your signal, runs the Layer-1 audit if `status: done`, and persists state. Read the JSON it prints — if `audit.all_pass` is false, the intent was reverted to open. Tell the user.

Then run `gpr status` to summarize progress, and yield.

## Hard rules

- Exactly **one** iteration per `/gpr` invocation (default mode). Do not call `gpr next-intent` twice.
- Do not modify `.gpr/plans/<slug>/Plan.json` directly. Use `gpr` subcommands.
- Do not skip the audit by editing the plan to mark an intent done. The audit is the contract.
- If you are uncertain whether the intent is done, emit `progress`, not `done`. The cost of a wasted iteration is small; the cost of a falsely-done intent is large (regressions land in `done` proofs).

## Autonomous loop — `/gpr loop`

Use this branch only when the invocation matched `/gpr loop`, `/gpr run`, `/gpr auto`, or an equivalent user phrase. The goal: hand off to the `gpr run` CLI driver, which is deterministic across agents (Claude, Codex, OpenCode, Gemini) and immune to per-model loop drift. You do NOT drive iterations yourself in this mode.

### Why the CLI driver, not a self-driven loop

Model-driven loops drift — different agents interpret "keep going" differently and may skip the audit, re-pick the same intent, or stall. `gpr run` is a single binary that:

- picks the next intent with `gpr next-intent`,
- spawns the build agent with the rendered prompt,
- parses the signal block,
- runs Layer-1 audit,
- persists state,
- repeats until done / blocked / budget-cap / max-iters.

That loop is identical for every agent. Prefer it over driving iterations from inside Claude.

### Preflight (loop mode)

1. Run `gpr doctor` via Bash. Fail fast if `gpr` is missing or `.gpr/Plan.json` is absent (in that case tell the user to run `/gpr-grill` first).
2. Render the Plan and surface the clickable link so the user can monitor progress while the loop runs:

   ```bash
   gpr render
   realpath .gpr/Plan.html
   ```

   Print `file:///abs/path/to/.gpr/Plan.html` on its own line so the terminal auto-linkifies it. Suggest the user open it in a browser — `gpr run` updates Plan.json after every iteration, and the user can re-render or pass `--watch` for live updates.

3. Read the Plan budget block (`gpr get budget.maxCostUsd`, `gpr get budget.tokens`, `gpr get budget.wallClockSeconds`) and surface the caps to the user. The loop soft-stops at 95% of whichever hits first.

### Confirm before launching

Looping spends real budget. Before running `gpr run`, show the user:

- the current intent count and how many are still open (`gpr status`),
- the budget caps,
- the agent that will be used (default `claude`, or whatever the user names).

Then ask: "Launch `gpr run --agent <X> --max-cost-usd <Y>`? This drives iterations until done, blocked, or budget hits."

Only proceed on explicit yes.

### Launch

Run the CLI driver via Bash. Sensible default:

```bash
gpr run --agent claude
```

Override flags only when the user asks:

- `--agent <NAME>` — any CLI on PATH works. Built-in adapters: `claude`, `codex`, `opencode`, `gemini`, `echo`. **Any other name** (e.g. `grok`, `llm`, `aider`, the next CLI that ships next week) gets an automatic stdin-passthrough adapter — just install the binary and `--agent <name>` Just Works. `gpr agent list` shows what's registered; `gpr agent add <name> --cmd ... --prompt-mode ...` registers a custom adapter once and reuses it.
- `--model <ID>` to pin a specific model (e.g. `claude-opus-4-7`, `gpt-5-codex`, `grok-2`). The flag forwards to CLIs whose adapter declares a `model_flag`; otherwise it's recorded for cost accounting only — pass the model via the CLI's own config or `GPR_AGENT_EXTRA_ARGS`.
- `--plan <slug>` to target a specific plan when multiple exist under `.gpr/plans/`. Defaults to the active plan.
- `--cmd "..." --prompt-mode stdin|argv_last|argv_named` to invoke any binary one-shot via `--agent custom`. Example: `gpr run --agent custom --cmd "ollama run llama3"`.
- `--max-iters N` to cap iterations.
- `--max-cost-usd USD` to cap spend (overrides Plan.budget for this run).
- `--deep-audit` to add Layer-2 model-driven audit on top of Layer-1 verifyCmds.

If the user has MCP servers, hook configs, or allowed-tools lists they want the spawned agent to inherit, set `GPR_AGENT_EXTRA_ARGS` first. Example:

```bash
GPR_AGENT_EXTRA_ARGS='--allowedTools "Bash(rtk *)"' gpr run --agent claude
```

`gpr run` streams progress to stdout and re-renders `.gpr/Plan.html` between iterations. The user can refresh the open browser tab to watch.

### After the loop returns

`gpr run` exits with one of:

- **all intents done** — run `gpr status` and `gpr pr-description` and report.
- **blocked** — print the blocking reason, point at `.gpr/errors.log` and `.gpr/Steer.md`, and suggest `/gpr-steer "..."` to redirect.
- **budget hit** — report which cap tripped; ask the user whether to bump it and resume with another `/gpr loop`.

Do NOT silently re-invoke `gpr run` after it exits. The loop has terminated; yield to the user.

### Hard rules (loop mode)

- Never bypass `gpr run` by writing your own iteration loop in Bash (`while true; do gpr next-intent; done` etc.). The CLI's signal parsing, audit, and lock handling are non-trivial.
- Never bump budget caps without the user's explicit yes.
- Never run `gpr run` if `.gpr/Plan.json` has not passed `gpr confidence-audit`. If the Plan is unaudited, recommend `/gpr-grill` first.

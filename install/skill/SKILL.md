---
name: gpr
description: Run one iteration of the gpr (Goal-driven PRD Ratchet) audit-verified loop in the CURRENT Claude session. Trigger when user types /gpr, /gpr next, /gpr ratchet, "run gpr iteration", or asks to drive an existing .gpr/Plan.json toward done from inside Claude. Do NOT trigger if .gpr/Plan.json does not exist — instruct the user to run `gpr init --objective "..."` first. Do NOT loop; one iteration per invocation, then yield.
---

# gpr — one iteration in current session

You are executing **exactly one** iteration of a gpr loop. The gpr CLI is the source of truth for state; you are the worker. After this iteration finishes, yield control to the user — do not auto-continue.

## Preflight (run once, fail fast)

Run `gpr doctor` via Bash. If `gpr` is not on PATH, instruct the user to install it from https://github.com/AdityaVG13/GPR and stop. If `.gpr/Plan.json` does not exist in the current working directory, tell the user to run `gpr init --objective "..."` and stop.

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

The rendered prompt instructs you to read these in order — do it:

- `.gpr/Steer.md` — if non-empty, the human is redirecting you. Do that work first, then `> .gpr/Steer.md` to clear it, and emit a `progress` signal. **Skip the rest of this iteration.**
- `.gpr/Pinned.md` — read-only invariants. Never overwrite this file.
- `.gpr/Spine.md` — externalized memory; what prior iterations decided.
- `.gpr/errors.log` — recent failures to avoid.

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

- Exactly **one** iteration per `/gpr` invocation. Do not call `gpr next-intent` twice.
- Do not modify `.gpr/Plan.json` directly. Use `gpr` subcommands.
- Do not skip the audit by editing the plan to mark an intent done. The audit is the contract.
- If you are uncertain whether the intent is done, emit `progress`, not `done`. The cost of a wasted iteration is small; the cost of a falsely-done intent is large (regressions land in `done` proofs).

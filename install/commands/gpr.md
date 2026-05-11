---
description: Run a gpr iteration (or `/gpr loop` for the hands-off CLI loop). With a goal, bootstrap if needed.
---

The user's input after `/gpr` is captured in `$ARGUMENTS`.

Decision tree:

1. **If `.gpr/Plan.json` exists AND `$ARGUMENTS` starts with `loop`, `run`, or `auto`:**
   - Activate the `gpr` skill (defined in `~/.claude/skills/gpr/SKILL.md`).
   - Take the **"Autonomous loop — `/gpr loop`"** branch at the bottom of that skill.
   - Hand off to the `gpr run` CLI driver after confirming the budget with the user. Do NOT drive iterations yourself.
   - Any extra words after `loop`/`run` (e.g. `/gpr loop --max-cost-usd 10 --agent codex`) are CLI flags to forward to `gpr run`.

2. **If `.gpr/Plan.json` exists AND `$ARGUMENTS` is empty / `next` / `ratchet`:**
   - Activate the `gpr` skill.
   - Run exactly one iteration in single-iteration mode. Yield to the user when done.

3. **If `.gpr/Plan.json` does NOT exist AND `$ARGUMENTS` is non-empty (and does not start with `loop`/`run`/`auto`):**
   - Treat `$ARGUMENTS` as the user's goal sentence.
   - Run `gpr init --objective "$ARGUMENTS"` via Bash.
   - Then activate the `gpr-grill` skill to interactively decompose the goal into intents and checks.
   - When the skill finishes, render the Plan and print the clickable `file://` link, then ask whether to start single-step (`/gpr`) or the hands-off loop (`/gpr loop`).

4. **If `.gpr/Plan.json` does NOT exist AND `$ARGUMENTS` is empty:**
   - Activate the `gpr-grill` skill from the start.
   - The skill will ask the user what they want to ratchet on, capture the goal, init, and decompose.

5. **If `.gpr/Plan.json` does NOT exist AND `$ARGUMENTS` starts with `loop`/`run`/`auto`:**
   - Refuse: tell the user there is no Plan to loop on, and recommend `/gpr-grill` (or `/gpr <goal>`) first.

Single-iteration mode runs exactly one round per `/gpr` invocation, then yields. Only `/gpr loop` delegates to the CLI driver that runs until done/blocked/budget.

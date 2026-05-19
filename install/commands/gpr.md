---
description: Run a gpr iteration (or `/gpr loop` for the hands-off CLI loop). With a goal, bootstrap; with a filepath, fold an existing Plan in.
---

The user's input after `/gpr` is captured in `$ARGUMENTS`.

Decision tree, evaluated top-down:

1. **If the first token of `$ARGUMENTS` is a path to a Plan file** (starts with `./`, `../`, `/`, `~`, `~/`, OR ends with `.json` / `.md` AND resolves on disk):
   - Treat this as a Plan import. Run via Bash:
     ```bash
     gpr import "<path>" --activate
     ```
   - Parse the slug from stdout. Then activate the `gpr` skill and run exactly **one** iteration in single-iteration mode against that slug (`--plan <slug>` on every `gpr` call inside the skill).
   - Any extra words after the path are forwarded to `gpr run` if the second word is `loop`/`run`/`auto` (autonomous mode); otherwise they are ignored.

2. **If `$ARGUMENTS` starts with `loop`, `run`, or `auto`:**
   - Activate the `gpr` skill (defined in `~/.claude/skills/gpr/SKILL.md`).
   - Take the **"Autonomous loop — `/gpr loop`"** branch at the bottom of that skill.
   - Hand off to the `gpr run` CLI driver after confirming the budget with the user. Do NOT drive iterations yourself.
   - Any extra words after `loop`/`run` (e.g. `/gpr loop --max-cost-usd 10 --agent codex --plan auth`) are CLI flags to forward to `gpr run`.
   - If no Plan exists for the active slug, refuse and recommend `/gpr-grill` (or `/gpr <goal>`) first.

3. **If a Plan exists for the active slug AND `$ARGUMENTS` is empty / `next` / `ratchet`:**
   - Activate the `gpr` skill.
   - Run exactly one iteration in single-iteration mode. Yield to the user when done.
   - "Active slug" comes from `$GPR_PLAN`, `.gpr/active`, or defaults to `default`. `gpr status` errors cleanly if there is no Plan.

4. **If no Plan exists AND `$ARGUMENTS` is non-empty (and isn't a path or `loop`/`run`/`auto`):**
   - Treat `$ARGUMENTS` as the user's goal sentence.
   - Run `gpr init --objective "$ARGUMENTS"` via Bash.
   - Then activate the `gpr-grill` skill to interactively decompose the goal into intents and checks.
   - When the skill finishes, render the Plan and print the clickable `file://` link, then ask whether to start single-step (`/gpr`) or the hands-off loop (`/gpr loop`).

5. **If no Plan exists AND `$ARGUMENTS` is empty:**
   - Activate the `gpr-grill` skill from the start.
   - The skill will ask the user what they want to ratchet on, capture the goal, init, and decompose.

Single-iteration mode runs exactly one round per `/gpr` invocation, then yields. Only `/gpr loop` delegates to the CLI driver that runs until done/blocked/budget. Filepath import always activates the imported plan but otherwise behaves like a normal single-iteration call.

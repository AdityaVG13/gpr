---
description: Run a gpr iteration in this session. With args, treat as a goal and bootstrap if needed.
---

The user's input after `/gpr` is captured in `$ARGUMENTS`.

Decision tree:

1. **If `.gpr/Plan.json` exists in the current working directory:**
   - Activate the `gpr` skill (defined in `~/.claude/skills/gpr/SKILL.md`).
   - Run exactly one iteration. Yield to the user when done.
   - Ignore `$ARGUMENTS` — the goal is already locked into the Plan.

2. **If `.gpr/Plan.json` does NOT exist AND `$ARGUMENTS` is non-empty:**
   - Treat `$ARGUMENTS` as the user's goal sentence.
   - Run `gpr init --objective "$ARGUMENTS"` via Bash.
   - Then activate the `gpr-grill` skill to interactively decompose the goal into intents and checks.
   - When the skill finishes, ask the user whether to start the loop now (`/gpr` again) or review the Plan first.

3. **If `.gpr/Plan.json` does NOT exist AND `$ARGUMENTS` is empty:**
   - Activate the `gpr-grill` skill from the start.
   - The skill will ask the user what they want to ratchet on, capture the goal, init, and decompose.

Do NOT run multiple iterations in a single `/gpr` invocation. One round per command, then yield.

---
description: Interactively turn a fuzzy goal into a Plan.json gpr can drive.
---

Activate the `gpr-grill` skill (defined in `~/.claude/skills/gpr-grill/SKILL.md`). Walk the user through the seven beats: goal lock, success metric, tech stack, anti-goals, intent decomposition, per-intent checks, budget. Produce `.gpr/Plan.json` and `.gpr/Pinned.md`. Run `gpr lint` and report. Yield without starting the loop — the user runs `/gpr` next when ready.

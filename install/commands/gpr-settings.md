---
description: Browse and edit gpr config (run defaults, viewer style, budget caps, env hints).
---

Activate the `gpr-settings` skill (defined in `~/.claude/skills/gpr-settings/SKILL.md`).

The skill wraps `gpr config` — the deterministic CLI surface for run defaults (`run.agent`, `run.max_iters`, `run.deep_audit`, …) and viewer preferences (`viewer.style`, `viewer.theme`, …). It also surfaces the runtime env vars (`GPR_AGENT_EXTRA_ARGS`, `GPR_NO_NOTIFY`, `GPR_BUDGET_MAX_COST_USD`) and points the user at `.gpr/Plan.json` for per-project budget caps.

`$ARGUMENTS` is forwarded as a hint:
- empty → present the full settings menu
- `list` / `show` → just dump current config and exit
- `<key>` (e.g. `run.agent`) → jump straight to that key
- `reset` → walk the user through reset confirmation

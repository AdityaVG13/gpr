---
name: gpr-settings
description: Interactive editor for gpr config — run defaults (agent, model, max-iters, deep-audit), viewer style/theme, plus env-var hints and Plan.json budget pointers. Trigger when user types /gpr-settings, /gpr settings, "show gpr config", "change gpr defaults", "edit gpr settings", or asks to inspect or change anything gpr-related that is not a Plan intent. Wraps `gpr config` deterministically — never edits Plan.json directly.
---

# gpr-settings — interactive config editor

Three things live under "gpr settings", and the user can confuse them. Surface all three, then drill into whichever the user picks:

1. **`gpr config`** — defaults that apply across runs. Two scopes:
   - `user` — `~/.config/gpr/config.json`. Applies to every project.
   - `project` — `.gpr/viewer-config.json` (despite the name, covers `run.*` keys too). Overrides user scope for this repo only.
2. **Env vars** — runtime overrides. Set in the shell that launches `gpr run`. Highest precedence.
3. **`.gpr/Plan.json`** — per-project Plan fields (`budget`, `qualityGates`, `persona`). Edit via `/gpr-grill` (revise mode) or your `$EDITOR`. **This skill does NOT edit Plan.json** — that's grill territory.

## Routing

Inspect `$ARGUMENTS`:

- empty → present the full menu (step 1 below).
- `list` / `show` → run `gpr config list` and `gpr config list --scope project`, render both, then yield. Skip the menu.
- a known key like `run.agent`, `viewer.theme`, etc. → jump to "Set one key" with that key preselected.
- `reset` → jump to "Reset" branch.
- `env` → jump to "Env vars" branch.

## Step 1 — show the current state

Run both:

```bash
gpr config list --scope user --json
gpr config list --scope project --json
```

Parse the JSON. Render a single compact table for the user:

```
KEY                     USER          PROJECT       DEFAULT
run.agent               claude        —             claude
run.audit_agent         —             —             None
run.deep_audit          False         —             False
run.max_iters           50            —             50
viewer.style            editorial     —             editorial
viewer.theme            paper         —             paper
…
```

Mark non-default values with a `*` so the user can see what's customized.

Below the table, surface the env vars that override at runtime:

- `GPR_AGENT_EXTRA_ARGS` — appended to the spawned agent command. Use for `--allowedTools`, `--model`, MCP server flags. Quoted; shell-split.
- `GPR_NO_NOTIFY=1` — disable desktop notifications (`osascript` / `notify-send` / `powershell.exe toast`).
- `GPR_BUDGET_MAX_COST_USD=USD` — runtime cap; overrides `Plan.budget.maxCostUsd` for this run.
- `GPR_HOME` — override gpr install dir (rarely needed).

And point at the Plan:

> "Per-project caps (`budget.tokens`, `budget.wallClockSeconds`, `budget.maxCostUsd`), `qualityGates`, `persona` live in `.gpr/Plan.json`. Edit those via `/gpr-grill` (revise mode) or `$EDITOR .gpr/Plan.json` — not here."

## Step 2 — ask what to change

> "What would you like to do?
> 1. Set a key (e.g. `run.agent = codex`)
> 2. Unset a key (revert to default)
> 3. Reset a whole scope (clear user OR project config)
> 4. Show env-var examples
> 5. Quit"

One option per turn. If the user names a key directly, skip to step 3.

## Step 3 — Set one key

Ask the user three things in one go:

1. Key — auto-complete from `gpr config keys` output. Reject unknown keys with the keys list.
2. Value — type-check against the default's type (bool, int, string, enum). For enums (`viewer.style`, `viewer.theme`), enumerate valid values.
3. Scope — `user` (global) or `project` (this repo only).

Then run:

```bash
gpr config set <key> <value> --scope <user|project>
```

Re-run `gpr config get <key> --scope <scope>` to confirm. Show the user the before/after.

## Step 4 — Unset / Reset

- **Unset one key** — `gpr config unset <key> --scope <scope>`. Confirms the key falls back to the next-precedence value.
- **Reset a scope** — `gpr config reset --scope <user|project>`. **Destructive.** Show the user the keys that will be cleared first; require explicit yes.

## Step 5 — Env-var examples

If the user picks the env-vars branch, print a few concrete invocations:

```bash
# Inherit MCP/allowed-tools into the spawned agent
GPR_AGENT_EXTRA_ARGS='--allowedTools "Bash(rtk *)"' gpr run --agent claude

# Cheap dry run, no notifications
GPR_NO_NOTIFY=1 gpr run --agent echo --max-iters 1

# Hard-cap a run below the Plan's budget
GPR_BUDGET_MAX_COST_USD=2 gpr run --agent claude
```

Then yield — env vars are set in the user's shell, not by us.

## Hard rules

- Never edit `~/.config/gpr/config.json` or `.gpr/viewer-config.json` directly with `Write`. Always go through `gpr config set/unset/reset`.
- Never edit `.gpr/Plan.json` from this skill. Direct the user to `/gpr-grill` or `$EDITOR`.
- Validate enum values against `gpr config keys` output before calling `set` — a bad value will be rejected by the CLI but the user experience is cleaner if we catch it first.
- Show the before/after for every change. The user should never have to run `gpr config get` themselves to confirm.

## Smoke test

A minimal happy path the skill should be able to walk end-to-end:

1. `/gpr-settings`
2. User picks "Set a key" → `viewer.theme` → `dark` → `user` scope.
3. Skill runs `gpr config set viewer.theme dark --scope user`.
4. Skill confirms with `gpr config get viewer.theme --scope user` → prints `'dark'`.
5. User runs `gpr render` in any project → HTML reflects the new theme.

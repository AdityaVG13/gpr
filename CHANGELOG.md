# Changelog

## v0.1.7 — 2026-05-11

Skill UX polish + discoverability. No core loop changes.

- **`/gpr loop` — hand off to the autonomous `gpr run` CLI driver.** The single-iteration `/gpr` flow stays the default, but `/gpr loop` (also `/gpr run`, `/gpr auto`) routes to `gpr run` instead of asking Claude to self-drive iterations. Rationale: model-driven loops drift across agents (Claude / Codex / OpenCode / Gemini); the CLI binary is identical for every agent and never skips audit, mis-picks intents, or stalls. The skill surfaces budget caps and requires explicit yes before launch. Trailing words on the slash command (`/gpr loop --max-cost-usd 10 --agent codex`) forward to `gpr run` flags.
- **Clickable PRD link after `/gpr-grill`.** Once Plan.json is written, the grill unconditionally runs `gpr render` and prints the absolute `.gpr/Plan.html` path on its own line as `file:///…`. Modern terminals (iTerm2, Warp, VS Code, Ghostty, Kitty) auto-linkify bare `file://` URLs — markdown link syntax intentionally avoided because some terminals don't linkify it. Replaces the previous "want me to run `gpr render --open`?" prompt.
- **New `/gpr-settings` slash command + skill.** Wraps `gpr config` deterministically. Surfaces the three settings layers users often conflate: `gpr config` keys (run defaults, viewer style/theme) across user/project scope; runtime env vars (`GPR_AGENT_EXTRA_ARGS`, `GPR_NO_NOTIFY`, `GPR_BUDGET_MAX_COST_USD`, `GPR_HOME`); and `.gpr/Plan.json` fields (budget, qualityGates, persona — pointed at `/gpr-grill`, not edited from this skill). `$ARGUMENTS` routing: empty → menu; `list` / `show` → dump and exit; `<key>` → jump to set; `reset` → destructive-reset branch with explicit confirm; `env` → env-var examples. Validates enum values against `gpr config keys` before calling set so the user sees a useful error.
- **README discoverability bump.** Cross-platform support was already shipping (CI exercises ubuntu / macos / windows on every PR since v0.1.4) but was buried in a `<details>` block. New **Platforms** badge in the header row; one-line "Runs on macOS, Linux, and Windows" sentence above the quickstart so it's visible without a click; Windows section trimmed to the two supported paths (WSL + Git Bash) with native PowerShell pointed at the issue tracker. `/gpr-settings` added to the slash-commands line.
- **CI: `actions/checkout` bumped v4 → v6** (Dependabot). No workflow-shape changes.

## v0.1.6 — 2026-05-08

Loop ingest fix.

- **Fix: signal ingest silently dropped on `claude --output-format stream-json`.** The continuation prompt's structured trailer block (`---gpr-signal---` … `---end---`) lives inside the `result` field of the final `{"type":"result"}` line, with embedded newlines JSON-escaped (`\n`). The channel regexes require real newlines, so every iteration's ingest failed → the intent stayed `in_progress` → `mark_done` / `apply_memory` / `revert_to_open` never fired → cumulative cost crossed the cap and the loop exited `budget_limited` after iter 1, looking like a crash. `lib/state/channels.py` now normalises stream-json input at the dispatch boundary by joining `result` strings and `assistant` `text` content with real newlines before handing the text to the channel parser. Plaintext output from codex / opencode / gemini / echo passes through unchanged (no JSON-line shape, nothing to unwrap). Covers all six channels via the single `channels.parse()` seam — no per-parser duplication.
- **Tests:** `tests/test_channels.py` covers the new normaliser (stream-json `result`, assistant `text` content arrays, plaintext pass-through, audit-verdict over stream-json, no-block-still-raises). 82 tests pass.

## v0.1.5 — 2026-05-08

Loop reliability + agent-control surface.

- **Fix: macOS `wall=0s` stalemate.** `_agent_run_generic` unconditionally invoked `timeout "$secs" claude …`, but macOS doesn't ship GNU coreutils — `timeout` resolved to "command not found", every iteration exited rc=127 in 0s with no signal block, and the loop tripped the stalemate kill-switch after 4 iters. The dispatcher now resolves `timeout` (Linux) → `gtimeout` (Homebrew) → no outer cap (per-agent CLI keeps its own limits). `gpr doctor` reports `timeout`/`gtimeout` so the missing dep is visible.
- **Fix: dangling `--append-system-prompt` on claude argv.** A trailing flag with no value swallowed the rendered prompt as the system-prompt addition, leaving the actual user prompt empty. Even when `timeout` was present this was a latent failure mode. Removed; the continuation prompt template already carries everything the agent needs.
- **`gpr run --model ID`** — first-class flag forces the agent's underlying model (e.g. `--model claude-opus-4-7`). `--print`-mode CLIs spawn fresh processes and don't inherit the parent session's model; without an override the loop ran at the agent's default. `agents.sh` injects `--model <id>` into claude/codex argv when set; cost accounting already used the same id, so the price-lookup stays consistent with what actually ran. Other agents (opencode, gemini) — pass model selection via `GPR_AGENT_EXTRA_ARGS`.
- **`GPR_AGENT_EXTRA_ARGS`** — pass-through env appended to every agent invocation, shell-split. Lets users opt their MCP servers, allowed-tools list, hooks-config, etc. into the loop without forking the dispatcher. Documented in `gpr run --help`. Example: `GPR_AGENT_EXTRA_ARGS='--allowedTools "Bash(rtk *)"' gpr run --agent claude`.
- **`gpr-grill` skill — Plan.json overwrite guard.** A preflight check forces an explicit Revise / Rewrite / Abort choice when `.gpr/Plan.json` already exists. Rewrite backs up to `.gpr/Plan.json.bak.<timestamp>` before any Write. New "never overwrite Plan.json without confirmation" rule overrides the one-question-per-turn flow when triggered. Adds an express-path "fast" / "quick" / "express" mode that batches beats 0–4 into a single proposal turn for users who want speed over depth. End-of-grill offers `gpr render --open` to view the Plan in a browser before kicking off the loop.

## v0.1.4 — 2026-05-08

Cross-platform support, community files, dependency automation.

- Linux + Windows now first-class platforms. Desktop notifications add a Windows toast path via `powershell.exe` (System.Windows.Forms balloon); WSL detected via `/proc/version` and falls through to `powershell.exe` if `notify-send` is missing. macOS + Linux unchanged.
- `gpr doctor` now prints platform info (system / release / machine / Python version) before the dependency check matrix.
- CI matrix expands to ubuntu-latest + macos-latest + windows-latest, Python 3.10 / 3.11 / 3.12 (9 combos for pytest). e2e dry-run runs on all three under Git Bash for Windows. shellcheck job gains `lib/commit.sh`.
- `pyproject.toml` adds `Operating System :: Microsoft :: Windows` classifier.
- README quickstart gains a collapsed platform-specific install block. Native PowerShell / cmd explicitly unsupported; WSL or Git Bash required on Windows.
- New `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1).
- New `.github/FUNDING.yml` — Ko-fi link surfaces as the Sponsor button.
- New `.github/dependabot.yml` — monthly updates for GitHub Actions and pip dev dependencies, scoped commit messages.
- New `.github/CODEOWNERS` — default review routing.
- README Roadmap section lists v0.2 priorities (MCP server, audit pipeline hoist, worktree mode, confidence-audit auto-revise, server mode, Layer-2 cost cap).

## v0.1.3 — 2026-05-08

Architecture pass — five deepening refactors per Matt Pocock's `improve-codebase-architecture` skill applied to the v0.1.2 surface.

- New `gpr get <jsonpath>` subcommand walks a dotted path with `[N]` array indexing through Plan.json or `--stdin`. Replaces 21 inline `python3 -c "import sys,json; print(json.load(sys.stdin)['x'])"` boilerplate calls in bash with direct `jq -r '.path'` (jq is already a doctor requirement). One typed accessor seam; bash callers stay thin.
- `lib/agents.sh` collapses five 90%-identical `agent_<name>` functions into one generic dispatcher backed by a single `_agent_argv` case statement. Adding a new agent that fits the "prompt as last positional" contract is a single case branch. Bash 3.2 compatible.
- `lib/loop.sh` `loop_iteration` decomposed into twelve named stages (`iter_disk_check`, `iter_steer_log`, `iter_pick_intent`, `iter_render_prompt`, `iter_invoke_agent`, `iter_record_budget`, `iter_ingest_signal`, `iter_layer2_audit`, `iter_signature`, `iter_classify_signal`, `iter_check_stalemate`, `iter_check_budget_hardstop`). Each has a contract documented at the top of the file: which iter-dir files it reads/writes, which globals it sets, what return codes mean. Stages are sourceable + invocable from a bash repl for unit-style testing.
- New `lib/state/channels.py` registers all six prompt-output protocols (signal, audit_verdict, reverse_audit, confidence_audit, commit, pr) as a single `Channel` dataclass each. `cli.py` ingest handlers now dispatch through `channels.parse(name, text)`. Adding a seventh channel becomes one CHANNELS entry, not a new parser file plus a new argparse handler.
- `lib/commit.sh` `cmd_commit_intent`, `cmd_pr_description`, `cmd_confidence_audit` collapse into thin callers around a new `_run_prompt_channel` helper that owns the render → agent_run → ingest pipeline once.
- Notify guard: `GPR_AGENT=echo` runs are dry-runs and never trigger desktop notifications. `GPR_NO_NOTIFY=1` for operators who never want them. (Apologies for the stale stalemate notification.)
- Shellcheck CI now passes warning-level. Unused `max_cost` wired through `GPR_BUDGET_MAX_COST_USD`; nameref usage on `_agent_run_generic` annotated; unused steer_text removed; SC2155 declare-and-assign-separately fixed; SC2218 source-before-call fixed.
- 76 tests still green; no behavior changes — pure deepening.

The sixth review candidate (audit pipeline hoist) is documented as a brain-dump in the gitignored `docs/internal/audit-pipeline.md` for v0.2 work alongside the MCP server.

## v0.1.2 — 2026-05-08

- Interactive PRD viewer rebuilt around Alpine.js with a three-column layout (sticky TOC rail + paper card + marginalia). New: command palette (`⌘K`), keyboard navigation (`J`/`K`/`/`/`?`/`S`/`D`), per-intent reading-progress rings, hash-on-hover anchors with copy-link toast, scroll-triggered fade-up, click-to-zoom Mermaid graph via `svg-pan-zoom`, story mode that strips chrome to a single 720px column, four selectable styles (editorial / terminal / notebook / brutalist), four themes (paper / sepia / dark / arctic), three font sizes, opt-in inline-edit mode that downloads a unified-diff patch, diff overlay against the latest snapshot, six concept demos under `docs/examples/`.
- New `gpr config get|set|list|unset|reset|keys` subcommand backed by `~/.config/gpr/config.json` (user) + `.gpr/viewer-config.json` (project) + env-var overrides. Persistent viewer + run defaults.
- New `gpr render --watch` re-renders on every state-file change; `--auto-refresh N` embeds a meta-refresh tag for hands-off live previews while a run is going. `--style`, `--theme`, `--no-spotlight` per-render overrides.
- New `gpr-grill` skill: nine-beat cleanroom interactive Plan interview (persona, goal lock, success metric, tech stack, anti-goals, decomposition, checks, budget, confidence audit). Refuses hand-waving and weak `verifyCmd`s.
- New `gpr confidence-audit`: scrutiniser agent inspects a draft Plan for eight loophole categories before the loop runs. Loops until `confident: true` or the user waives a remaining loophole into Pinned.md.
- `gpr run --deep-audit` wires the Layer-2 cross-model auditor on every done-flip after Layer-1 passes. Reverse audit runs at end-of-run to catch spec drift; reopens regressed intents or writes goal gaps to Steer.md.
- New `gpr commit-intent <ID>` and `gpr pr-description` apply the staged-pr discipline (Conventional Commits with scope, conceptual bullets organised by concept, no filler verbs) to gpr's own outputs.
- New `gpr trace`, `gpr audit --reverse`, `gpr revert-intent`.
- Persona priming on every prompt: four registered personas (`principal_engineer`, `senior_architect`, `rapid_prototyper`, `research_partner`) selected per-Plan. Continuation prompt restructured with PERSONA at top, RULES + FINAL CONSTRAINT at the bottom (Gemini recency-bias defence). Auditor prompts each get a tailored suspicious / fresh-eyed prime.
- `--max-cost-usd` flag now wired through `GPR_BUDGET_MAX_COST_USD`; `lib/state/budget.py` honours env-var overrides for all three axes.
- Security hardening: `SECURITY.md` documents the threat model (`shell=True` is by-design, agent gets full FS access, env vars inherited, prompt injection mitigated not eliminated). `.gitignore` covers `.env*` / keys / credentials. `errors.log` redacted before injection. Lint catches `\|\| true` failure-swallowing and oversize fields.
- Hardcoded developer paths removed: `lib/loop.sh` derives `GPR_LIB` via `BASH_SOURCE`, `docs/demo.tape` uses `$GPR_HOME`. CI shellcheck now passes warning-level.
- 76 tests (up from 60). New tests cover plan/signal/audit/stalemate/budget/lock/redact/verdict parsers + e2e dry-run.

## v0.1.1 — 2026-05-08

- `gpr run --deep-audit` wires the Layer-2 cross-model auditor in. Done-flips that pass Layer-1 are now scrutinised by a second agent (defaults to the build agent; `--audit-agent X` overrides) before the intent stays done.
- Reverse audit runs automatically at end-of-run. If it returns regressions or goal gaps, the loop reopens the affected intents (or writes the gaps to `Steer.md`) instead of declaring `achieved`.
- `/gpr <goal>` now bootstraps the run. With no Plan and a goal sentence, it inits and hands off to `gpr-grill` for decomposition. With no Plan and no args, it jumps straight to `gpr-grill`.
- New `gpr-grill` skill: cleanroom interactive spec gathering. Seven beats — goal lock, success metric, tech stack, anti-goals, intent decomposition, per-intent checks, budget — each with refusal rules for hand-waving and weak `verifyCmd`s. Output is a complete `.gpr/Plan.json` and `.gpr/Pinned.md`.
- `gpr render` writes a self-contained `.gpr/Plan.html` dashboard: Mermaid intent DAG, per-check evidence glyphs, budget bar, rolling event table. Tailwind + Mermaid via CDN, no build step.
- `gpr commit-intent <ID>` and `gpr pr-description` apply the staged-pr discipline to the gpr backend itself: conventional-commits titles with scope, conceptual bullets organised by concept, no filler verbs, no file-by-file walkthroughs. `--apply` on commit-intent runs `git commit`.
- README has a visual-first rewrite with an embedded vhs demo recording and freeze-rendered status / help screenshots.

## v0.1.0 — 2026-05-07

Initial public alpha.

- Plan + Check + Proof + Signal data model with fcntl-locked atomic state file.
- Continuation prompt rendered per-iteration with goal demotion, pinned invariants, spine memory, recent errors, and signal grammar.
- Five-status signal grammar: done, progress, blocked, decide, rescope.
- Layer-1 audit: per-check verifyCmd with retry and timeout. Layer-2 cross-model auditor prompt shipped; auto-invocation pending.
- Stalemate detector: payload-hash + checkbox-count signature with case-split stall recovery notes.
- Three-axis budget governor (token, wall-clock, USD) with soft-stop wrap-up turn.
- Five backends: claude, codex, opencode, gemini, plus a deterministic echo agent for dry-runs.
- Claude Code skill (`/gpr`) and slash commands `/gpr-status`, `/gpr-steer`.
- 60-test pytest suite plus end-to-end dry-run script.

Known limitations:

- Layer-2 auditor is wired into prompts/ but not auto-invoked yet; run `gpr audit --intent <id>` manually for now.
- Reverse audit (spec-drift sweep at run end) is implemented in `lib/state/audit.py` but not yet hooked into `gpr run`.
- Worktree mode is on the roadmap; v0.1 runs against the working tree directly.
- MCP server is deferred to v0.2.

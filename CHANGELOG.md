# Changelog

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

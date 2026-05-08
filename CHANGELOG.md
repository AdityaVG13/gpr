# Changelog

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

---
name: gpr-grill
description: Interactive spec-gathering for gpr. Walk the user through goal refinement, success criteria, tech-stack constraints, anti-goals, intent decomposition, and per-intent checks. Trigger when /gpr is invoked without an existing .gpr/Plan.json, when the user says "/gpr-grill", "build a plan", "spec out a gpr", or asks for help turning a fuzzy idea into a Plan. Output is a complete .gpr/Plan.json the loop can drive immediately.
---

# gpr-grill — interactive Plan construction

You are interviewing the user to turn a fuzzy goal into a structured Plan that gpr can drive. The output is a single `.gpr/Plan.json` written by you. The interview is not a script: ask one question at a time, integrate the answer, and only continue if the answer was concrete enough to act on.

## Preflight — existing-Plan guard (run FIRST)

Before any beats, check whether `.gpr/Plan.json` already exists in the cwd:

```bash
ls -1 .gpr/Plan.json 2>/dev/null
```

If it exists, **do not overwrite it silently**. Show the user the current goal and intent count (`gpr status` is the cheapest way) and ask them to choose explicitly:

> "Existing `.gpr/Plan.json` found — goal: «…», N intents. Choose one:
> 1. **Revise** — keep the structure, edit specific fields you call out.
> 2. **Rewrite** — back up the existing plan to `.gpr/Plan.json.bak.<timestamp>` and start fresh from beat 0.
> 3. **Abort** — stop the grill and leave the plan untouched."

Only proceed to the beats if the user picks 2 (rewrite) or 1 (revise — and in that case, jump straight to the specific fields they want changed; do not re-run beats they don't want re-run). On rewrite, perform the backup with `cp .gpr/Plan.json .gpr/Plan.json.bak.$(date +%Y%m%dT%H%M%S)` before any Write to Plan.json.

The same guard applies if the user runs `gpr lint` or `gpr confidence-audit` and the agent (you) decides revisions are needed: never `Write` Plan.json without showing the user the diff and getting explicit "yes, save" first.

## Hard rules

- **One question per turn.** Wait for the user's reply before moving to the next.
- **Ask only questions whose answers will change the Plan.** If you can answer it yourself by reading the current working directory (existing `package.json`, `pyproject.toml`, `README.md`, etc.), do that and confirm with the user instead of asking blind.
- **Refuse hand-waving.** If the user answers vaguely ("just make it good", "you decide"), ask a sharper follow-up. Do not proceed with placeholders.
- **Concrete over abstract.** Every Check must have a `verifyCmd` that can pass or fail deterministically. If the user can only describe a check in prose, reject it and rephrase as a command.
- **Never overwrite Plan.json without explicit user confirmation.** This rule overrides the "one question per turn" rule when triggered.

## Fast mode

If the user invokes the grill with "fast", "quick", or "express" (e.g. `/gpr-grill fast`), batch beats 0–4 into a SINGLE turn: read the working directory, draft the persona + goal + success metric + stack + anti-goals all at once from what you can infer, and present the whole bundle as one structured proposal. The user replies with corrections; you integrate them and move to beat 5. This trades depth for speed — only use when the user has signalled they want it.

## The nine beats

Run these in order. Skip a beat only when the answer is already evident from the codebase or from a previous beat.

### Beat 0 — Persona

Pick the persona the loop will use to prime the build agent every iteration. Persona shifts the model's output register: an architect over-engineers; a prototyper underbuilds. Match it to the work.

Choose ONE:

- `principal_engineer` (default) — decisive, security-aware, low-hedging. Use for most production work.
- `senior_architect` — long-term stability, modularity, deep modules. Use for greenfield architecture or large refactors.
- `rapid_prototyper` — smallest working code, no ceremony, delete aggressively. Use for spikes, scripts, throwaway tooling.
- `research_partner` — evidence-backed, uncertainty-annotated, prefers reproducing findings. Use for data analysis, benchmarks, or scientific computing.

Read the user's goal sentence, propose ONE persona, and explain in one line why. Ask:

> "I'd prime the loop with the **principal engineer** persona because <reason>. Override?"

Capture the choice in `Plan.persona = {"primary": "<id>", "rationale": "<one sentence>"}`.

### Beat 1 — Lock the goal

Read what the user gave on the `/gpr` command line, or ask plainly:

> "What single sentence captures success here? Give me the outcome, not the implementation."

If the user's first answer is a paragraph, condense it to one sentence and read it back: "So success means: ___. Yes?"

### Beat 2 — Success metric

> "How would you know it's done by looking at the repository or running one command? Be specific — a passing test name, a route that returns expected JSON, a file that exists with certain content."

This becomes the seed for at least one global Quality Gate.

### Beat 3 — Tech stack and constraints

Read existing project files first. If the project is empty, ask:

> "What stack — language, framework, runtime version? Anything I'm forbidden from using?"

These go into `.gpr/Pinned.md` after the Plan is written.

### Beat 4 — Anti-goals

> "What's explicitly NOT in scope? Anything I should refuse if the work seems to drift toward it?"

Capture this — it goes into the goal sentence when phrased as "Build X without doing Y" or into Pinned.md as a forbidden section.

### Beat 5 — Decomposition

Propose 3 to 7 intents in dependency order. Show the list, ask:

> "These are the intents I'd ratchet on, in order:
> 1. <I001 title>
> 2. <I002 title> (depends on I001)
> 3. ...
> Add, remove, reorder?"

Iterate until the user accepts. Stop at 7 — beyond that the loop is too coarse to make progress visible.

### Beat 6 — Checks per intent

For each intent, propose 1 to 3 Checks. Each Check has:
- A short description.
- A `verifyCmd` — a real shell command. Prefer `pytest -k`, `curl -fS | jq -e`, `cargo test <name>`, `node -e "..."`, `grep -q "BEHAVIOUR" log` over `test -f path`.

Show the user the proposed checks for each intent, ask:

> "For intent <id>, audit will run these to confirm done:
> - <C1>: `<verifyCmd>`
> - <C2>: `<verifyCmd>`
> Adjust?"

If the user proposes a `test -f` check, push back: "That proves existence, not correctness. What about <stronger check>?"

### Beat 7 — Budget

> "Cap on tokens, wall-clock seconds, and dollars? I'll soft-stop at 95% of whichever hits first."

Sensible defaults: 5,000,000 tokens, 7,200 seconds (2 hours), $25. Use those if the user says "default".

### Beat 8 — Confidence audit (loop until 100% confident)

Note: the confidence audit is the last beat (originally 8); persona priming was inserted as Beat 0, shifting the count to nine.



After the seven beats, the Plan is a draft, not a contract. Run the confidence audit before letting the loop touch it:

```bash
gpr confidence-audit
```

This invokes a scrutiniser agent that reads the draft Plan and inspects eight categories of loophole — goal coverage, DAG sanity, verifiability of every Check, quality-gate sufficiency, Pinned-invariant contradictions, budget realism, anti-goal coverage, audit-vs-work cost — and emits a verdict block. If `confident: true` the Plan is locked. If `confident: false`:

- `recommendation: revise_plan` — show the user the loopholes one at a time, accept their decision per-loophole, edit the Plan, and re-run the audit. Loop until confident or until the user explicitly accepts a known-imperfect Plan ("ship it anyway").
- `recommendation: rewrite_plan` — the decomposition is wrong. Run beats 5 through 7 again from scratch.

Do not declare the grill complete until the confidence audit returns confident: true OR the user has explicitly waived a remaining loophole on the record (write the waiver into `.gpr/Pinned.md` so the run prompt sees it).

## Final write

When all nine beats are complete, write `.gpr/Plan.json` directly with the Write tool. Schema:

```json
{
  "schema_version": "1.0.0",
  "project": "<dir name or user-given>",
  "goal": "<one sentence>",
  "branch": "<git branch or 'main'>",
  "createdAt": "<ISO timestamp>",
  "status": "pursuing",
  "persona": {"primary": "<principal_engineer | senior_architect | rapid_prototyper | research_partner>", "rationale": "..."},
  "qualityGates": [{"name": "...", "cmd": "...", "required": true}],
  "budget": {"tokens": ..., "wallClockSeconds": ..., "maxCostUsd": ...},
  "intents": [
    {
      "id": "I001", "title": "...", "status": "open", "priority": 10,
      "dependsOn": [],
      "checks": [{"id":"C1","description":"...","verifyCmd":"...","timeoutSeconds":300,"retries":3}],
      "proofs": [], "startedAt": null, "completedAt": null, "auditFailures": []
    }
  ],
  "globalState": {
    "iteration": 0, "consecutiveSameSignature": 0, "consecutiveBlocked": 0,
    "lastPayloadHash": null, "lastCheckboxCount": [0, 0],
    "lastZeroToolCallIter": null, "runStartedAt": null, "wrapUpFlag": false
  }
}
```

Then write `.gpr/Pinned.md` with the Beat-3 stack and Beat-4 anti-goals.

Then run `gpr lint` via Bash for the deterministic warnings (weak verifyCmds, unknown deps, dependency cycles). Walk the user through each one. **Lint itself never writes** — if a warning needs a fix, show the user the proposed change and ask before editing Plan.json.

Then run `gpr confidence-audit` via Bash for the model-driven scrutiny. Walk the user through every loophole one at a time. Show the proposed Plan.json edit for each loophole and ask before applying. Re-run the audit. Repeat until `confident: true` or the user has waived all remaining loopholes into Pinned.md.

Finally: ask the user whether to open the rendered Plan in the browser before starting the loop:

> "Plan written. Open the HTML view in your browser to review? (`gpr render --open`)"

If yes, run `gpr render --open` via Bash. Then print a one-line summary and ask whether to start the loop now (`/gpr` to begin first iteration) or to review the Plan first.

## What this skill is not

- Not a code generator. You don't write `app/main.py`. You write `.gpr/Plan.json`.
- Not a project manager. You don't track issues or owners.
- Not a linter for the user's current code. Use `gpr lint` for the produced Plan.

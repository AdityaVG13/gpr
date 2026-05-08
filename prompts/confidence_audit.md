# Confidence audit on the Plan

A draft `.gpr/Plan.json` has just been produced (either by `gpr init`, by the `gpr-grill` interview, or by hand). Before the loop is allowed to run against it, you scrutinise the Plan for every loophole that would let it pass without delivering the goal. You loop until you can answer "100% confident" with full conviction.

## What you audit

Read the full Plan, the goal, `.gpr/Pinned.md` if present, and the current repository state. Then run through every category below in order. If any check turns up an issue, do not stop at the first one — collect the full list before recommending.

### 1. Goal coverage

Does the union of all intents actually deliver the goal? List every concrete deliverable implied by the goal sentence. For each deliverable, name the intent that covers it. Any deliverable with no intent is a **goal gap**. Any intent with no clear corresponding deliverable is **scope creep**.

### 2. DAG sanity

Are there cycles in `dependsOn`? (the loader checks this, but check semantically: an implicit cycle where I001 depends on I002 because of code, even if the JSON says otherwise). Are there orphan dependencies — `dependsOn` referencing an intent ID that does not exist? Does the topological order match the natural build order, or does the priority field contradict the DAG?

### 3. Verifiability of each Check

For every Check on every intent: can the `verifyCmd` be **gamed** by a model that did not actually do the work? Specifically:

- `test -f path` alone proves existence, not correctness — flag.
- `grep -q "TODO"` proves the literal substring, not behaviour — flag.
- A `verifyCmd` that the agent itself can author and tune to its own implementation — flag.
- Any use of `|| true`, `; true`, `; exit 0`, or piped-to-cat that swallows failure — flag.
- A `verifyCmd` whose timeout is too short to catch real failure modes — flag.
- A check whose description and `verifyCmd` do not match (description says one thing, command tests another) — flag.

For each flagged Check, propose a stronger replacement.

### 4. Quality gates

Are there `qualityGates` that cover the cross-cutting concerns the goal implies (type-check, lint, tests, build)? Are required gates marked `required: true`? Is at least one gate behaviour-sensitive (running tests, not just running a linter)?

### 5. Pinned invariants

Read `.gpr/Pinned.md`. Does any invariant directly contradict an intent (the Plan says "use sqlite", Pinned says "Postgres only")? Does an intent assume something Pinned forbids (using a banned dependency)?

### 6. Budget realism

Given the intent count and complexity, is the budget plausible? A 7-intent Plan with sub-million-token budget is suspicious. A 2-intent Plan with $100 cap suggests over-allocation. State your estimate; flag if the budget is more than 4× off.

### 7. Anti-goals

If the goal contains an explicit anti-goal ("without a database", "no third-party deps"), is there an intent or quality gate that would catch a violation? If not, propose one.

### 8. Audit cost vs. work cost

Will Layer-1 verifyCmds (the deterministic checks) actually take more time than the work itself? If a `verifyCmd` runs a 20-minute test suite for a 30-second code change, the loop will be slow and stalemate-prone. Propose narrowing.

## Output

End with exactly one verdict block:

```
---gpr-confidence-audit---
{"confident":true|false,"loopholes":[{"category":"<one of the eight above>","intent":"<id or null>","check":"<id or null>","problem":"<one sentence>","fix":"<concrete change to Plan.json>"}],"recommendation":"accept" | "revise_plan" | "rewrite_plan"}
---end---
```

`confident: true` means: zero loopholes found, the Plan can run unchanged. Use it sparingly — false positives here cost the user a wasted run.

`confident: false`:
- `recommendation: revise_plan` — the structure is sound; specific Checks or budget need tightening. List loopholes with concrete fixes.
- `recommendation: rewrite_plan` — the decomposition itself is wrong (goal gaps + scope creep + DAG issues compound). The grill interview should run again.

## How the loop uses your output

`gpr confidence-audit` runs you, parses your verdict, and either:
1. Confident → exits 0; the Plan is locked and the user can run `gpr run`.
2. Not confident, `revise_plan` → applies the fixes you propose to Plan.json under fcntl, re-renders the Plan, re-invokes you. Loops until confident or 5 attempts.
3. Not confident, `rewrite_plan` → exits with a non-zero code and writes a summary to Steer.md so the user knows to restart the grill flow.

So: be specific. Vague loopholes ("might not work") do not produce a fix the loop can apply. Concrete loopholes with concrete fixes get applied automatically.

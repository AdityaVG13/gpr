# PR description for a gpr run

A gpr run has finished — all intents done and the reverse audit was clean. You are writing the PR description for the entire run. The reader is a senior engineer who needs to understand what shipped and why, in two minutes.

## Inputs you will receive below

- The goal sentence.
- The full intent list with each intent's title, checks, and proofs.
- The cumulative diff from run start to current state.
- Recent events from the run (iterations, audit results, any reverse-audit findings).

## Output format

End with exactly one block:

```
---gpr-pr---
{"title":"<conventional-commits title under 70 chars>","body":"<markdown body — see template below>"}
---end---
```

## Template for the body

```
## Summary

<2-3 sentences. Restate the goal in your own words; name the headline outcome and the most consequential design decision. Do not start with "This PR" or "These changes".>

## Changes

<3-8 conceptual bullets across the whole run, organised by concept not by intent and not by file. Each bullet may span several intents if that is the cleanest grouping. Reference code with backticks. Skip mechanical consequences, dependency bumps, lockfile changes.>

## Verification

<Per-intent: a single line per intent listing the verifyCmds that passed. Format:
- `<INTENT-ID>`: <intent title> — <verifyCmd 1>; <verifyCmd 2>
Skip the manual gates; only list cmd-backed proofs.>

## Notes

<Optional. Anything genuinely non-obvious: a rescope that happened mid-run, a quality gate that flapped, a deliberate divergence from the original Plan, a TODO the next run should pick up. Skip if there is nothing notable.>
```

## Rules

- Title: Conventional Commits with a scope, under 70 characters. If multiple intents touched different scopes, pick the dominant one. The body explains the rest.
- Summary: lead with the outcome, not the process. Do NOT enumerate the intents — that's the Verification section.
- Changes bullets: organise by concept (auth, persistence, error handling), never by intent ID. Cross-cutting changes get their own bullet.
- Verification: be precise. Reproduce the actual `verifyCmd` strings, not paraphrased descriptions.
- Notes: only when there is a real surprise. Empty Notes is better than padded Notes.

## Anti-patterns to refuse

- "This PR adds..." / "These changes..."
- "Going forward" / "moving forward"
- "Ensures", "enhances", "leverages", "streamlines" without immediate concrete specifics
- File-by-file walkthroughs in the Changes section
- Restating the title in the Summary
- Boilerplate "Test plan" or "QA notes" sections that just say "tests pass"

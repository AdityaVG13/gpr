# Security policy

## Reporting a vulnerability

Please report security issues privately by opening a [private security advisory](https://github.com/AdityaVG13/GPR/security/advisories/new) on the repository, or by email to `adityavgcode@gmail.com`. Do not file public issues for vulnerabilities.

We aim to respond within 72 hours and patch confirmed issues within two weeks for critical severity, four weeks for high severity, and at maintainer discretion for medium/low.

## Threat model

gpr is a local CLI tool that drives an LLM coding agent through a Plan. Its threat model assumes the operator runs it on their own machine against repos they own and trust the contents of. The model is **not** a multi-tenant service.

### Trust boundaries

| Surface | Trust assumption |
|---|---|
| `.gpr/Plan.json` | Trusted. The operator wrote it (or accepted it from `gpr-grill`). gpr does not sandbox `verifyCmd` execution. |
| `.gpr/Pinned.md`, `.gpr/Spine.md`, `.gpr/Steer.md` | Trusted. Read into the continuation prompt verbatim. The operator is responsible for what they put in these files. |
| Goal text supplied to `gpr init --objective "..."` | **Untrusted.** Wrapped in `<untrusted_goal>` tags in the continuation prompt to demote prompt-injection attempts. |
| Agent stdout (Claude / Codex / OpenCode / Gemini) | Treated as untrusted. Only the structured `---gpr-signal---` JSON block is parsed; everything else is logged and ignored for state mutation. |
| `.gpr/runs/<id>/iter-NNN/` artifacts | Local-only. Not redacted by default. The operator should add `.gpr/` to project `.gitignore` if they don't want artifacts committed. |
| `errors.log` | Redacted on write via `lib/state/redact.py` for known secret patterns (GitHub PAT, AWS keys, JWT, Anthropic / OpenAI keys, generic `KEY=VALUE` shapes). Best-effort, not exhaustive. |

### Known accepted risks

1. **`verifyCmd` runs under `shell=True`.** This is by design — Plan.json `verifyCmd` is a shell command authored by the operator. Anyone who can write to your `.gpr/Plan.json` can execute arbitrary shell. Treat Plan.json with the same care as a Makefile or package.json scripts. **Do not run gpr against a Plan.json from an untrusted source without reviewing it.**

2. **The build agent has full filesystem and shell access.** Claude Code, Codex, and OpenCode are invoked with their permission-prompt bypass flags (`--dangerously-skip-permissions`, `--dangerously-bypass-approvals-and-sandbox`, `--no-confirm`). The agent can read, write, and execute on the project directory and beyond. Run gpr in a clean repo or a container if this is unacceptable. A future `--sandbox` flag is on the roadmap.

3. **Subprocesses inherit the parent environment.** `verifyCmd` and the agent invocation both inherit `os.environ`, including any secrets in the operator's shell. This is necessary for `verifyCmd` to work (often needs `DATABASE_URL`, `API_KEY`, etc) but means an attacker-controlled command sees them.

4. **The HTML render embeds run state.** `gpr render` writes `Plan.html` containing intent titles, check descriptions, audit failure JSON, and recent events. If those contain accidental secrets, the HTML will too. Don't share `Plan.html` publicly without inspection.

5. **Prompt injection is mitigated, not eliminated.** `<untrusted_goal>` and `<untrusted_objective>`-style tags reduce the chance a malicious goal sentence overrides system rules, but don't eliminate it. A persistent attacker who controls the goal *and* can patch the agent's tool output stream can still influence behaviour. The Layer-2 cross-model auditor is the structural defence.

### Hardening recommendations for operators

- Run `gpr` inside a containerised dev environment (Docker, devcontainer, nix-shell) when ratcheting on a Plan you didn't write end-to-end.
- Add `.gpr/` to your project's `.gitignore` to keep run artifacts out of version control.
- Set per-Plan budget caps (`tokens`, `wallClockSeconds`, `maxCostUsd`) so a runaway agent stops.
- Use `--audit-agent` to run the Layer-2 auditor under a different (preferably cheaper) model — independent verification is the highest-leverage defence against the build agent gaming `verifyCmd`s.
- Review `.gpr/Plan.json` warnings from `gpr lint` before every `gpr run`. Weak `verifyCmd`s (`test -f`, `grep TODO`) are flagged.

### Cryptography and authentication

gpr does not implement authentication or encryption. Plan.json and all state files are stored unencrypted. The CLI does not call out to any service except the LLM provider configured by the operator (via the agent CLI's own credentials).

## Dependencies

Runtime: Python ≥3.10 stdlib only. Bash ≥5. `git`, `jq`. Plus one of: `claude`, `codex`, `opencode`, `gemini` on `$PATH`.

Dev: `pytest`. CI uses `actions/checkout`, `actions/setup-python`, `ludeeus/action-shellcheck`. No pinned-by-hash actions in v0.1; on the roadmap.

The HTML render loads three CDN resources at runtime: `cdn.tailwindcss.com`, `fonts.googleapis.com`, `cdn.jsdelivr.net/npm/mermaid@10`. Operators uncomfortable with CDN execution in the rendered file should not open it in a browser, or should run it through a CSP-enforced wrapper.

## License

Apache 2.0. The license includes an explicit warranty disclaimer (Section 7) and limitation of liability (Section 8). gpr is provided as-is.

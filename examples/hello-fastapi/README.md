# Example: hello-fastapi

A three-intent Plan that scaffolds a FastAPI hello-world, implements `GET /hello`, and writes a passing pytest suite. Each intent has checks with real verifyCmds — they will fail until the code actually works.

## Run it

```bash
mkdir -p ~/projects/hello-fastapi && cd ~/projects/hello-fastapi
git init && git commit --allow-empty -m "init"

# Bootstrap state
mkdir -p .gpr
cp ~/.local/share/gpr/examples/hello-fastapi/Plan.json .gpr/Plan.json

# Install python + fastapi for the audit to be able to import-check
uv venv && source .venv/bin/activate
uv pip install fastapi pytest httpx

# Drive
gpr run --agent claude --max-cost-usd 2
```

## What to expect

Iteration 1 picks `I001` (project scaffold), creates `pyproject.toml`, `app/main.py`, `tests/test_main.py`. The Layer-1 audit verifies `test -f` plus the dependency grep before flipping `I001` to done.

Iteration 2 picks `I002` (the endpoint). It writes the `/hello` route. Audit imports the app via `TestClient`, confirms 200 + JSON shape.

Iteration 3 picks `I003` (the test suite). The audit re-runs pytest and only flips `I003` if every test passes.

If any audit fails, the intent reverts to `open` and the failure is appended to `errors.log`. The next iteration reads the tail of `errors.log` first and is told "do not repeat these failure modes".

The whole run typically completes in 3–6 iterations on Claude with reasonable models.

## Tweak it

The example uses real `verifyCmd`s so you can study what good audits look like. Try:

- Weakening `I002/C2` to just `test -f app/main.py`. Run `gpr lint` — it warns. Run gpr — the agent can satisfy the weak check without writing the endpoint.
- Adding a fourth intent that depends on `I003` (e.g., "deploy to Render"). The DAG ordering is preserved automatically.
- Setting `maxCostUsd` to `0.10` and watching the budget wrap-up turn fire after a couple of iterations.

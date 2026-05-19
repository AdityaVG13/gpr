#!/usr/bin/env bash
# End-to-end smoke test using the echo agent. Exercises every CLI surface.
# Pass: exit 0. Fail: exit non-zero with a clear message.
set -euo pipefail

GPR_HOME="${GPR_HOME:-$(cd "$(dirname "$0")/.." && pwd)}"
GPR="$GPR_HOME/bin/gpr"
TMP="$(mktemp -d /tmp/gpr-e2e-XXXXXX)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

echo "[e2e] working in $TMP"
cd "$TMP"
git init -q -b main

echo "[e2e] init"
"$GPR" init --objective "Smoke goal" >/dev/null

# Replace the example intent with one whose check passes.
PLAN_PATH=".gpr/plans/default/Plan.json"
python3 <<PY
import json
p = json.load(open("$PLAN_PATH"))
p["intents"] = [{
  "id": "I001", "title": "smoke", "status": "open", "priority": 1,
  "dependsOn": [], "checks": [
    {"id":"C1","description":"x","verifyCmd":"true","timeoutSeconds":5,"retries":1}
  ], "proofs": [], "startedAt": None, "completedAt": None, "auditFailures": []
}]
p["budget"] = {"tokens": 100000, "wallClockSeconds": 300, "maxCostUsd": 0.5}
json.dump(p, open("$PLAN_PATH","w"), indent=2)
PY

echo "[e2e] status"
"$GPR" status >/dev/null

echo "[e2e] lint"
set +e
"$GPR" lint >/dev/null
lint_rc=$?
set -e
if (( lint_rc != 0 )); then
  echo "[e2e] (expected) lint reported warnings"
fi

echo "[e2e] doctor"
set +e
"$GPR" doctor >/dev/null
set -e

echo "[e2e] steer"
"$GPR" steer "test-steer" >/dev/null
[[ -s .gpr/plans/default/Steer.md ]] || { echo "FAIL: Steer.md not written"; exit 1; }

echo "[e2e] echo agent run (expects stalemate after 4 progress iterations)"
set +e
"$GPR" run --agent echo --max-iters 6 >/dev/null
rc=$?
set -e
# Stalemate is exit 6.
if (( rc != 6 && rc != 5 )); then
  echo "FAIL: expected rc=5 or 6 from stalemate, got $rc"
  exit 1
fi

echo "[e2e] artifacts present"
[[ -d .gpr/plans/default/runs ]] || { echo "FAIL: no runs dir"; exit 1; }
runs=( .gpr/plans/default/runs/*/iter-* )
(( ${#runs[@]} >= 2 )) || { echo "FAIL: expected ≥2 iter dirs, got ${#runs[@]}"; exit 1; }
[[ -s "${runs[0]}/prompt.md" ]] || { echo "FAIL: no prompt.md in iter dir"; exit 1; }
[[ -s "${runs[0]}/signal.json" ]] || { echo "FAIL: no signal.json"; exit 1; }

echo "[e2e] multi-plan: import + parallel layout"
"$GPR" init --plan auth --objective "Auth subsystem" >/dev/null
[[ -f .gpr/plans/auth/Plan.json ]] || { echo "FAIL: auth plan not created"; exit 1; }
"$GPR" plan list >/dev/null
"$GPR" plan use auth >/dev/null
active=$("$GPR" plan current)
[[ "$active" == "auth" ]] || { echo "FAIL: plan current = $active, expected auth"; exit 1; }

echo "[e2e] import from a hand-written Plan.json"
cat > /tmp/external-plan-$$.json <<EOF
{
  "goal": "imported plan goal",
  "intents": [
    {"id":"X1","title":"hi","checks":[{"id":"C","description":"x","verifyCmd":"true"}]}
  ]
}
EOF
"$GPR" import "/tmp/external-plan-$$.json" --name imported >/dev/null
[[ -f .gpr/plans/imported/Plan.json ]] || { echo "FAIL: import did not create plan"; exit 1; }
rm -f "/tmp/external-plan-$$.json"

echo "[e2e] agent registry: list shows built-ins"
"$GPR" agent list | grep -q claude || { echo "FAIL: claude not in adapter list"; exit 1; }

echo "[e2e] PASS"

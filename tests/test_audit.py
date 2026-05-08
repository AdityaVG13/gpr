"""Audit: verifyCmd execution, retries, timeout, manual gate.

Tests use `sys.executable -c "..."` for verifyCmds so they're
cross-platform — `true` / `false` / `sleep` aren't on Windows cmd.exe.
"""

from __future__ import annotations

import sys

from lib.state import audit as audit_mod
from lib.state import plan as plan_mod

# Portable test commands. shell=True will dispatch through cmd.exe on
# Windows / sh on POSIX; both can run "<python> -c '...'".
PASS_CMD = f'"{sys.executable}" -c "pass"'
FAIL_CMD = f'"{sys.executable}" -c "import sys; sys.exit(1)"'
SLEEP_CMD = f'"{sys.executable}" -c "import time; time.sleep(5)"'


def test_passing_check(tmp_project):
    ch = {"id": "C1", "description": "x", "verifyCmd": PASS_CMD,
          "timeoutSeconds": 10, "retries": 1}
    r = audit_mod.run_check(ch, tmp_project)
    assert r["result"] == "pass"


def test_failing_check_retried(tmp_project):
    ch = {"id": "C2", "description": "x", "verifyCmd": FAIL_CMD,
          "timeoutSeconds": 10, "retries": 3}
    r = audit_mod.run_check(ch, tmp_project)
    assert r["result"] == "fail"
    assert len(r["attempts"]) == 3


def test_timeout_classified_as_fail(tmp_project):
    ch = {"id": "C3", "description": "x", "verifyCmd": SLEEP_CMD,
          "timeoutSeconds": 1, "retries": 1}
    r = audit_mod.run_check(ch, tmp_project)
    assert r["result"] == "fail"
    assert r["attempts"][0]["timed_out"] is True


def test_manual_gate_no_verifycmd(tmp_project):
    ch = {"id": "M", "description": "x", "verifyCmd": None,
          "timeoutSeconds": 5, "retries": 1}
    r = audit_mod.run_check(ch, tmp_project)
    assert r["result"] == "manual"


def test_audit_intent_aggregate(tmp_project):
    p = plan_mod.init(tmp_project, "demo", "g", "main")
    it = plan_mod.empty_intent("I", "x")
    it["checks"] = [
        plan_mod.empty_check("C1", "pass", PASS_CMD),
        plan_mod.empty_check("C2", "fail", FAIL_CMD),
    ]
    it["checks"][0]["retries"] = 1
    it["checks"][1]["retries"] = 1
    plan_mod.add_intent(p, it)
    r = audit_mod.audit_intent(p, "I", tmp_project)
    assert r["pass"] == 1
    assert r["fail"] == 1
    assert r["all_pass"] is False


def test_audit_all_pass_yields_proofs(tmp_project):
    p = plan_mod.init(tmp_project, "demo", "g", "main")
    it = plan_mod.empty_intent("I", "x")
    it["checks"] = [plan_mod.empty_check("C1", "pass", PASS_CMD)]
    it["checks"][0]["retries"] = 1
    plan_mod.add_intent(p, it)
    audit = audit_mod.audit_intent(p, "I", tmp_project)
    proofs = audit_mod.proofs_from_audit(audit)
    assert len(proofs) == 1
    assert proofs[0]["checkId"] == "C1"
    assert proofs[0]["type"] == "cmd_exit_0"


def test_evidence_sweep_finds_regression(tmp_project):
    p = plan_mod.init(tmp_project, "demo", "g", "main")
    it = plan_mod.empty_intent("I", "x")
    it["checks"] = [plan_mod.empty_check("C1", "no", FAIL_CMD)]
    it["checks"][0]["retries"] = 1
    it["status"] = "done"
    it["completedAt"] = "2026-05-07T00:00:00Z"
    p["intents"].append(it)
    sweep = audit_mod.evidence_sweep(p, tmp_project, last_n=5)
    assert len(sweep["regressions"]) == 1
    assert sweep["regressions"][0]["intent"] == "I"

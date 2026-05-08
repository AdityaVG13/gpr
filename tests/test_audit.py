"""Audit: verifyCmd execution, retries, timeout, manual gate."""

from __future__ import annotations

from lib.state import audit as audit_mod
from lib.state import plan as plan_mod


def test_passing_check(tmp_project):
    ch = {"id": "C1", "description": "x", "verifyCmd": "true",
          "timeoutSeconds": 5, "retries": 1}
    r = audit_mod.run_check(ch, tmp_project)
    assert r["result"] == "pass"


def test_failing_check_retried(tmp_project):
    ch = {"id": "C2", "description": "x", "verifyCmd": "false",
          "timeoutSeconds": 5, "retries": 3}
    r = audit_mod.run_check(ch, tmp_project)
    assert r["result"] == "fail"
    assert len(r["attempts"]) == 3


def test_timeout_classified_as_fail(tmp_project):
    ch = {"id": "C3", "description": "x", "verifyCmd": "sleep 5",
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
        plan_mod.empty_check("C1", "pass", "true"),
        plan_mod.empty_check("C2", "fail", "false"),
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
    it["checks"] = [plan_mod.empty_check("C1", "pass", "true")]
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
    it["checks"] = [plan_mod.empty_check("C1", "no", "false")]
    it["checks"][0]["retries"] = 1
    it["status"] = "done"
    it["completedAt"] = "2026-05-07T00:00:00Z"
    p["intents"].append(it)
    sweep = audit_mod.evidence_sweep(p, tmp_project, last_n=5)
    assert len(sweep["regressions"]) == 1
    assert sweep["regressions"][0]["intent"] == "I"

"""Layer-1 audit: run each Check's verifyCmd, record pass/fail with evidence.

Layer-2 (cross-model auditor subagent) is invoked separately by the loop
driver — see prompts/audit_check.md. This file only handles deterministic
verifyCmd execution.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from . import plan as plan_mod

TAIL_BYTES = 4096
RETRY_BASE_SECONDS = 1.0
RETRY_BACKOFF = 2.0


class AuditError(RuntimeError):
    pass


def _tail(b: bytes, n: int = TAIL_BYTES) -> str:
    if not b:
        return ""
    if len(b) <= n:
        return b.decode("utf-8", "replace")
    return "...[truncated]...\n" + b[-n:].decode("utf-8", "replace")


def _run_once(
    cmd: str, cwd: str | Path, timeout: int, env: dict[str, str] | None = None
) -> dict[str, Any]:
    start = time.monotonic()
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            timeout=timeout,
            env=proc_env,
            check=False,
        )
        return {
            "rc": result.returncode,
            "stdout": _tail(result.stdout),
            "stderr": _tail(result.stderr),
            "timed_out": False,
            "wall_seconds": round(time.monotonic() - start, 3),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "rc": -1,
            "stdout": _tail(exc.stdout or b""),
            "stderr": _tail(exc.stderr or b""),
            "timed_out": True,
            "wall_seconds": round(time.monotonic() - start, 3),
        }


def run_check(
    check: dict[str, Any], cwd: str | Path, env: dict[str, str] | None = None
) -> dict[str, Any]:
    """Run one Check with retries. Returns audit detail."""
    verify_cmd = check.get("verifyCmd")
    if not verify_cmd:
        return {
            "checkId": check["id"],
            "result": "manual",
            "reason": "no verifyCmd; manual gate",
            "attempts": [],
        }
    timeout = int(check.get("timeoutSeconds", 300))
    retries = max(1, int(check.get("retries", 3)))
    attempts: list[dict[str, Any]] = []
    for i in range(retries):
        outcome = _run_once(verify_cmd, cwd, timeout, env)
        attempts.append(outcome)
        if outcome["rc"] == 0 and not outcome["timed_out"]:
            return {
                "checkId": check["id"],
                "result": "pass",
                "attempts": attempts,
            }
        if i + 1 < retries:
            time.sleep(RETRY_BASE_SECONDS * (RETRY_BACKOFF ** i))
    return {
        "checkId": check["id"],
        "result": "fail",
        "attempts": attempts,
    }


def audit_intent(
    plan: dict[str, Any],
    intent_id: str,
    cwd: str | Path,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run all Checks on an intent. Returns aggregate audit result."""
    intent = plan_mod.find_intent(plan, intent_id)
    if intent is None:
        raise AuditError(f"unknown intent {intent_id}")
    detail = [run_check(ch, cwd, env) for ch in intent["checks"]]
    pass_count = sum(1 for d in detail if d["result"] == "pass")
    fail_count = sum(1 for d in detail if d["result"] == "fail")
    manual_count = sum(1 for d in detail if d["result"] == "manual")
    all_pass = fail_count == 0 and (pass_count + manual_count) == len(detail)
    return {
        "intent": intent_id,
        "all_pass": all_pass,
        "pass": pass_count,
        "fail": fail_count,
        "manual": manual_count,
        "details": detail,
    }


def audit_quality_gates(
    plan: dict[str, Any], cwd: str | Path, env: dict[str, str] | None = None
) -> dict[str, Any]:
    """Run global quality gates."""
    gates = plan.get("qualityGates", [])
    detail: list[dict[str, Any]] = []
    for g in gates:
        synthetic = {
            "id": g["name"],
            "verifyCmd": g["cmd"],
            "timeoutSeconds": g.get("timeoutSeconds", 600),
            "retries": g.get("retries", 1),
        }
        result = run_check(synthetic, cwd, env)
        result["required"] = g.get("required", True)
        detail.append(result)
    failed_required = [
        d for d in detail if d.get("required") and d["result"] == "fail"
    ]
    return {
        "all_pass": not failed_required,
        "details": detail,
    }


def evidence_sweep(
    plan: dict[str, Any],
    cwd: str | Path,
    last_n: int = 5,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Re-run verifyCmds for the last N intents that flipped to done.

    Detects spec drift: a previously-done check now fails because
    a later iteration broke an invariant.
    """
    done = [it for it in plan["intents"] if it["status"] == "done"]
    done.sort(key=lambda it: it.get("completedAt") or "", reverse=True)
    targets = done[:last_n]
    regressions: list[dict[str, Any]] = []
    for it in targets:
        for ch in it["checks"]:
            res = run_check(ch, cwd, env)
            if res["result"] == "fail":
                regressions.append({"intent": it["id"], "check": ch["id"], "detail": res})
    return {"regressions": regressions, "checked": len(targets)}


def proofs_from_audit(audit: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a passing audit into Proof entries to attach to the intent."""
    proofs: list[dict[str, Any]] = []
    for d in audit["details"]:
        if d["result"] == "pass":
            last = d["attempts"][-1] if d["attempts"] else {}
            proofs.append(
                {
                    "checkId": d["checkId"],
                    "type": "cmd_exit_0",
                    "wallSeconds": last.get("wall_seconds"),
                    "verifiedAt": plan_mod.utc_now(),
                }
            )
        elif d["result"] == "manual":
            proofs.append(
                {
                    "checkId": d["checkId"],
                    "type": "manual",
                    "verifiedAt": plan_mod.utc_now(),
                }
            )
    return proofs

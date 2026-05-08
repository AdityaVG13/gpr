"""Plan: source-of-truth state file. CRUD with atomic writes + DAG checks."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .lock import file_lock

SCHEMA_VERSION = "1.1.0"

PERSONAS = {
    "principal_engineer": (
        "You are a Principal Engineer. You favour decisive, security-aware "
        "design choices over consensus-driven ones. You reject hedging, refuse "
        "speculative complexity, and treat technical debt as a real cost. When "
        "two paths exist, you pick one and state why. Output is dense, "
        "imperative, low-noise."
    ),
    "senior_architect": (
        "You are a Senior Software Architect. You optimise for long-term "
        "stability, modularity, and clear seams between components. Every "
        "abstraction must earn its keep. You prefer deep modules with small "
        "interfaces over shallow ones. You think about who maintains this "
        "code in two years."
    ),
    "rapid_prototyper": (
        "You are a Rapid Prototyper. The goal is the smallest amount of "
        "working code that proves the next bit of the goal. No framework "
        "ceremony. No over-abstraction. Boring tools, fast iterations, "
        "delete code aggressively. Polish later."
    ),
    "research_partner": (
        "You are a Research Partner. You ground every claim in evidence — "
        "real test output, real file contents, real command results. You "
        "annotate uncertainty explicitly. You prefer reproducing a finding "
        "to asserting it."
    ),
}
DEFAULT_PERSONA = "principal_engineer"
STALE_SECONDS_DEFAULT = 600
INTENT_STATUSES = {"open", "in_progress", "done", "paused"}
PLAN_STATUSES = {
    "pursuing",
    "paused",
    "achieved",
    "unmet_blocked",
    "unmet_decide",
    "unmet_stalemate",
    "unmet_zero_progress",
    "unmet_disk_full",
    "unmet_dag_cycle",
    "unmet_steered_abort",
    "unmet_no_intents",
    "budget_limited",
    "rescope_pending",
    "crashed",
}


class PlanError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gpr_dir(project_root: str | Path) -> Path:
    return Path(project_root) / ".gpr"


def plan_path(project_root: str | Path) -> Path:
    return _gpr_dir(project_root) / "Plan.json"


def lock_path(project_root: str | Path) -> Path:
    return _gpr_dir(project_root) / "locks" / "plan.lock"


def empty_plan(project: str, goal: str, branch: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "project": project,
        "goal": goal,
        "branch": branch,
        "createdAt": utc_now(),
        "status": "pursuing",
        "persona": {
            "primary": DEFAULT_PERSONA,
            "rationale": "default — decision-oriented, low-hedging baseline",
        },
        "qualityGates": [],
        "budget": {"tokens": None, "wallClockSeconds": None, "maxCostUsd": None},
        "intents": [],
        "globalState": {
            "iteration": 0,
            "consecutiveSameSignature": 0,
            "consecutiveBlocked": 0,
            "lastPayloadHash": None,
            "lastCheckboxCount": [0, 0],
            "lastZeroToolCallIter": None,
            "runStartedAt": None,
            "wrapUpFlag": False,
        },
    }


def empty_intent(intent_id: str, title: str, priority: int = 50) -> dict[str, Any]:
    return {
        "id": intent_id,
        "title": title,
        "status": "open",
        "priority": priority,
        "dependsOn": [],
        "checks": [],
        "proofs": [],
        "startedAt": None,
        "completedAt": None,
        "auditFailures": [],
    }


def empty_check(check_id: str, description: str, verify_cmd: str | None) -> dict[str, Any]:
    return {
        "id": check_id,
        "description": description,
        "verifyCmd": verify_cmd,
        "timeoutSeconds": 300,
        "retries": 3,
    }


def load(project_root: str | Path) -> dict[str, Any]:
    p = plan_path(project_root)
    if not p.exists():
        raise PlanError(f"no Plan.json at {p}; run `gpr init`")
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError as exc:
        raise PlanError(f"corrupt Plan.json: {exc}") from exc


def save(project_root: str | Path, plan: dict[str, Any]) -> None:
    """Atomic write: tmp + rename."""
    p = plan_path(project_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, p)


def init(
    project_root: str | Path, project: str, goal: str, branch: str
) -> dict[str, Any]:
    p = plan_path(project_root)
    if p.exists():
        raise PlanError(f"Plan.json already exists at {p}")
    plan = empty_plan(project, goal, branch)
    with file_lock(lock_path(project_root)):
        save(project_root, plan)
    return plan


def find_intent(plan: dict[str, Any], intent_id: str) -> dict[str, Any] | None:
    for it in plan["intents"]:
        if it["id"] == intent_id:
            return it
    return None


def add_intent(plan: dict[str, Any], intent: dict[str, Any]) -> None:
    if find_intent(plan, intent["id"]):
        raise PlanError(f"intent {intent['id']} already exists")
    plan["intents"].append(intent)


def dag_cycle(plan: dict[str, Any]) -> list[str] | None:
    """Return a cycle as a list of intent ids if one exists, else None."""
    color: dict[str, int] = {}  # 0=white, 1=gray, 2=black
    parent: dict[str, str | None] = {}
    cycle: list[str] = []

    def visit(node: str) -> bool:
        color[node] = 1
        intent = find_intent(plan, node)
        if intent is None:
            color[node] = 2
            return False
        for dep in intent["dependsOn"]:
            c = color.get(dep, 0)
            if c == 1:
                cur = node
                cycle.append(dep)
                while cur != dep and cur is not None:
                    cycle.append(cur)
                    cur = parent.get(cur)
                cycle.append(dep)
                cycle.reverse()
                return True
            if c == 0:
                parent[dep] = node
                if visit(dep):
                    return True
        color[node] = 2
        return False

    for it in plan["intents"]:
        if color.get(it["id"], 0) == 0:
            parent[it["id"]] = None
            if visit(it["id"]):
                return cycle
    return None


def select_next_intent(plan: dict[str, Any]) -> dict[str, Any] | None:
    """Highest-priority open intent whose dependsOn are all done. Lower priority int = sooner."""
    done_ids = {it["id"] for it in plan["intents"] if it["status"] == "done"}
    candidates = [
        it
        for it in plan["intents"]
        if it["status"] == "open" and all(d in done_ids for d in it["dependsOn"])
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda it: (it["priority"], it["id"]))
    return candidates[0]


def reset_stale_in_progress(
    plan: dict[str, Any], stale_seconds: int = STALE_SECONDS_DEFAULT
) -> list[str]:
    """Reset any in_progress intent older than threshold back to open. Returns reset ids."""
    reset: list[str] = []
    cutoff = time.time() - stale_seconds
    for it in plan["intents"]:
        if it["status"] != "in_progress":
            continue
        started = it.get("startedAt")
        if not started:
            continue
        try:
            t = datetime.strptime(started, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            continue
        if t.timestamp() < cutoff:
            it["status"] = "open"
            it["startedAt"] = None
            reset.append(it["id"])
    return reset


def mark_in_progress(plan: dict[str, Any], intent_id: str) -> dict[str, Any]:
    it = find_intent(plan, intent_id)
    if it is None:
        raise PlanError(f"unknown intent {intent_id}")
    if it["status"] != "open":
        raise PlanError(f"intent {intent_id} is {it['status']}, not open")
    it["status"] = "in_progress"
    it["startedAt"] = utc_now()
    return it


def mark_done(plan: dict[str, Any], intent_id: str, proofs: list[dict]) -> dict[str, Any]:
    it = find_intent(plan, intent_id)
    if it is None:
        raise PlanError(f"unknown intent {intent_id}")
    if plan["globalState"].get("wrapUpFlag"):
        raise PlanError("cannot mark done during wrap-up turn")
    it["status"] = "done"
    it["completedAt"] = utc_now()
    it["proofs"].extend(proofs)
    return it


def revert_to_open(plan: dict[str, Any], intent_id: str, failure: dict) -> dict[str, Any]:
    it = find_intent(plan, intent_id)
    if it is None:
        raise PlanError(f"unknown intent {intent_id}")
    it["status"] = "open"
    it["startedAt"] = None
    it["auditFailures"].append({**failure, "at": utc_now()})
    return it


MAX_GOAL_LEN = 2000
MAX_INTENT_TITLE_LEN = 200
MAX_CHECK_DESC_LEN = 500
MAX_VERIFYCMD_LEN = 8192


def lint(plan: dict[str, Any]) -> list[str]:
    """Return human-readable warnings about Plan quality. Empty == clean."""
    warnings: list[str] = []
    if len(plan.get("goal", "")) > MAX_GOAL_LEN:
        warnings.append(f"goal exceeds {MAX_GOAL_LEN} chars")
    ids = [it["id"] for it in plan["intents"]]
    if len(ids) != len(set(ids)):
        warnings.append("duplicate intent ids")
    for it in plan["intents"]:
        if len(it.get("title", "")) > MAX_INTENT_TITLE_LEN:
            warnings.append(f"{it['id']}: title exceeds {MAX_INTENT_TITLE_LEN} chars")
        if it["status"] not in INTENT_STATUSES:
            warnings.append(f"{it['id']}: unknown status {it['status']!r}")
        for dep in it["dependsOn"]:
            if dep not in ids:
                warnings.append(f"{it['id']}: dependsOn unknown intent {dep!r}")
            if dep == it["id"]:
                warnings.append(f"{it['id']}: depends on itself")
        for ch in it["checks"]:
            if len(ch.get("description", "")) > MAX_CHECK_DESC_LEN:
                warnings.append(
                    f"{it['id']}/{ch['id']}: description exceeds {MAX_CHECK_DESC_LEN} chars"
                )
            vc = ch.get("verifyCmd")
            if vc and len(vc) > MAX_VERIFYCMD_LEN:
                warnings.append(
                    f"{it['id']}/{ch['id']}: verifyCmd exceeds {MAX_VERIFYCMD_LEN} chars"
                )
            if not vc:
                warnings.append(f"{it['id']}/{ch['id']}: no verifyCmd (manual gate)")
                continue
            stripped = vc.strip()
            weak = (
                stripped.startswith("test -f ")
                and " && " not in stripped
                and " | " not in stripped
            )
            if weak:
                warnings.append(
                    f"{it['id']}/{ch['id']}: weak verifyCmd "
                    f"({stripped!r}) — file existence does not prove correctness"
                )
            if stripped in ("true", ":", "echo PASS", "exit 0"):
                warnings.append(
                    f"{it['id']}/{ch['id']}: trivial verifyCmd ({stripped!r}) — "
                    "always passes"
                )
            if "|| true" in stripped or "; true" in stripped or stripped.endswith("|| :"):
                warnings.append(
                    f"{it['id']}/{ch['id']}: verifyCmd swallows failure with '|| true' "
                    "or similar — the audit will pass even when the command fails"
                )
    cycle = dag_cycle(plan)
    if cycle:
        warnings.append(f"dependency cycle: {' -> '.join(cycle)}")
    return warnings


def all_done(plan: dict[str, Any]) -> bool:
    return bool(plan["intents"]) and all(
        it["status"] == "done" for it in plan["intents"]
    )


def persona_text(plan: dict[str, Any]) -> str:
    """Return the persona priming string for this Plan."""
    primary = plan.get("persona", {}).get("primary", DEFAULT_PERSONA)
    return PERSONAS.get(primary, PERSONAS[DEFAULT_PERSONA])

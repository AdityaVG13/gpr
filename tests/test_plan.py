"""Plan lifecycle: init, intent CRUD, DAG, selection, lint."""

from __future__ import annotations

import json

import pytest

from lib.state import plan as plan_mod


def test_init_creates_plan(tmp_project):
    p = plan_mod.init(tmp_project, "demo", "Build X", "main")
    assert p["project"] == "demo"
    assert p["goal"] == "Build X"
    assert p["status"] == "pursuing"
    assert plan_mod.plan_path(tmp_project).exists()


def test_init_refuses_when_exists(tmp_project):
    plan_mod.init(tmp_project, "demo", "Build X", "main")
    with pytest.raises(plan_mod.PlanError, match="already exists"):
        plan_mod.init(tmp_project, "demo", "Build Y", "main")


def test_load_save_roundtrip(tmp_project):
    p = plan_mod.init(tmp_project, "demo", "Build X", "main")
    plan_mod.add_intent(p, plan_mod.empty_intent("I1", "first", priority=10))
    plan_mod.save(tmp_project, p)
    p2 = plan_mod.load(tmp_project)
    assert p2["intents"][0]["id"] == "I1"


def test_add_intent_rejects_duplicate(tmp_project):
    p = plan_mod.init(tmp_project, "demo", "Build X", "main")
    plan_mod.add_intent(p, plan_mod.empty_intent("I1", "first"))
    with pytest.raises(plan_mod.PlanError, match="already exists"):
        plan_mod.add_intent(p, plan_mod.empty_intent("I1", "dup"))


def test_dag_cycle_detection(tmp_project):
    p = plan_mod.init(tmp_project, "demo", "Build X", "main")
    plan_mod.add_intent(p, plan_mod.empty_intent("A", "a"))
    plan_mod.add_intent(p, plan_mod.empty_intent("B", "b"))
    p["intents"][0]["dependsOn"] = ["B"]
    p["intents"][1]["dependsOn"] = ["A"]
    cycle = plan_mod.dag_cycle(p)
    assert cycle is not None
    assert set(cycle) >= {"A", "B"}


def test_dag_no_cycle(tmp_project):
    p = plan_mod.init(tmp_project, "demo", "Build X", "main")
    plan_mod.add_intent(p, plan_mod.empty_intent("A", "a"))
    plan_mod.add_intent(p, plan_mod.empty_intent("B", "b", priority=20))
    p["intents"][1]["dependsOn"] = ["A"]
    assert plan_mod.dag_cycle(p) is None


def test_select_next_priority(tmp_project):
    p = plan_mod.init(tmp_project, "demo", "Build X", "main")
    plan_mod.add_intent(p, plan_mod.empty_intent("A", "a", priority=10))
    plan_mod.add_intent(p, plan_mod.empty_intent("B", "b", priority=5))
    nxt = plan_mod.select_next_intent(p)
    assert nxt["id"] == "B"


def test_select_next_respects_deps(tmp_project):
    p = plan_mod.init(tmp_project, "demo", "Build X", "main")
    plan_mod.add_intent(p, plan_mod.empty_intent("A", "a", priority=10))
    plan_mod.add_intent(p, plan_mod.empty_intent("B", "b", priority=5))
    p["intents"][1]["dependsOn"] = ["A"]
    nxt = plan_mod.select_next_intent(p)
    assert nxt["id"] == "A"
    plan_mod.mark_in_progress(p, "A")
    plan_mod.mark_done(p, "A", proofs=[])
    nxt2 = plan_mod.select_next_intent(p)
    assert nxt2["id"] == "B"


def test_mark_done_refused_during_wrapup(tmp_project):
    p = plan_mod.init(tmp_project, "demo", "Build X", "main")
    plan_mod.add_intent(p, plan_mod.empty_intent("A", "a"))
    plan_mod.mark_in_progress(p, "A")
    p["globalState"]["wrapUpFlag"] = True
    with pytest.raises(plan_mod.PlanError, match="wrap-up"):
        plan_mod.mark_done(p, "A", proofs=[])


def test_lint_weak_verifycmd(tmp_project):
    p = plan_mod.init(tmp_project, "demo", "Build X", "main")
    it = plan_mod.empty_intent("I", "x")
    it["checks"] = [plan_mod.empty_check("C1", "y", "test -f foo.txt")]
    plan_mod.add_intent(p, it)
    warns = plan_mod.lint(p)
    assert any("weak verifyCmd" in w for w in warns)


def test_lint_trivial_verifycmd(tmp_project):
    p = plan_mod.init(tmp_project, "demo", "Build X", "main")
    it = plan_mod.empty_intent("I", "x")
    it["checks"] = [plan_mod.empty_check("C1", "y", "true")]
    plan_mod.add_intent(p, it)
    warns = plan_mod.lint(p)
    assert any("trivial verifyCmd" in w for w in warns)


def test_lint_swallowed_failure(tmp_project):
    p = plan_mod.init(tmp_project, "demo", "Build X", "main")
    it = plan_mod.empty_intent("I", "x")
    it["checks"] = [plan_mod.empty_check("C1", "y", "pytest -q || true")]
    plan_mod.add_intent(p, it)
    warns = plan_mod.lint(p)
    assert any("swallows failure" in w for w in warns)


def test_lint_oversize_goal(tmp_project):
    p = plan_mod.init(tmp_project, "demo", "x" * (plan_mod.MAX_GOAL_LEN + 100), "main")
    plan_mod.add_intent(p, plan_mod.empty_intent("I", "ok"))
    warns = plan_mod.lint(p)
    assert any("goal exceeds" in w for w in warns)


def test_lint_oversize_intent_title(tmp_project):
    p = plan_mod.init(tmp_project, "demo", "g", "main")
    it = plan_mod.empty_intent("I", "x" * (plan_mod.MAX_INTENT_TITLE_LEN + 50))
    plan_mod.add_intent(p, it)
    warns = plan_mod.lint(p)
    assert any("title exceeds" in w for w in warns)


def test_lint_unknown_dependency(tmp_project):
    p = plan_mod.init(tmp_project, "demo", "Build X", "main")
    it = plan_mod.empty_intent("A", "a")
    it["dependsOn"] = ["GHOST"]
    plan_mod.add_intent(p, it)
    warns = plan_mod.lint(p)
    assert any("unknown intent" in w for w in warns)


def test_reset_stale_in_progress(tmp_project, monkeypatch):
    import time
    p = plan_mod.init(tmp_project, "demo", "Build X", "main")
    plan_mod.add_intent(p, plan_mod.empty_intent("A", "a"))
    plan_mod.mark_in_progress(p, "A")
    p["intents"][0]["startedAt"] = "2020-01-01T00:00:00Z"
    reset = plan_mod.reset_stale_in_progress(p, stale_seconds=60)
    assert reset == ["A"]
    assert p["intents"][0]["status"] == "open"


def test_all_done(tmp_project):
    p = plan_mod.init(tmp_project, "demo", "Build X", "main")
    assert not plan_mod.all_done(p)
    plan_mod.add_intent(p, plan_mod.empty_intent("A", "a"))
    assert not plan_mod.all_done(p)
    plan_mod.mark_in_progress(p, "A")
    plan_mod.mark_done(p, "A", proofs=[])
    assert plan_mod.all_done(p)

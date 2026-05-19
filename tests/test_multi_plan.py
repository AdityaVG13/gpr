"""Multi-plan layout: slug pathing, list, switching, migration, lazy normalize."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.state import plan as plan_mod


def test_slugify_basic():
    assert plan_mod.slugify("Auth Subsystem") == "auth-subsystem"
    assert plan_mod.slugify("TODO REST API") == "todo-rest-api"
    assert plan_mod.slugify("") == "plan"
    assert plan_mod.slugify("   ") == "plan"
    assert plan_mod.slugify("a/b/c") == "a-b-c"
    assert plan_mod.slugify("../escape") == "escape"


def test_plan_path_includes_slug(tmp_project):
    p1 = plan_mod.plan_path(tmp_project, "default")
    p2 = plan_mod.plan_path(tmp_project, "auth")
    assert p1.parent.name == "default"
    assert p2.parent.name == "auth"
    assert p1 != p2


def test_init_under_slug_directory(tmp_project):
    plan_mod.init(tmp_project, "demo", "Build auth", "main", slug="auth")
    assert (tmp_project / ".gpr" / "plans" / "auth" / "Plan.json").exists()
    assert not (tmp_project / ".gpr" / "Plan.json").exists()


def test_parallel_plans_have_independent_locks(tmp_project):
    plan_mod.init(tmp_project, "demo", "a", "main", slug="auth")
    plan_mod.init(tmp_project, "demo", "b", "main", slug="todo")
    l1 = plan_mod.lock_path(tmp_project, "auth")
    l2 = plan_mod.lock_path(tmp_project, "todo")
    assert l1 != l2
    assert l1.parent.parent.name == "auth"
    assert l2.parent.parent.name == "todo"


def test_list_plans(tmp_project):
    assert plan_mod.list_plans(tmp_project) == []
    plan_mod.init(tmp_project, "demo", "g1", "main", slug="alpha")
    plan_mod.init(tmp_project, "demo", "g2", "main", slug="beta")
    assert plan_mod.list_plans(tmp_project) == ["alpha", "beta"]


def test_active_slug_roundtrip(tmp_project):
    assert plan_mod.read_active_slug(tmp_project) is None
    plan_mod.write_active_slug(tmp_project, "auth")
    assert plan_mod.read_active_slug(tmp_project) == "auth"


def test_migration_moves_legacy_layout(tmp_project):
    """Legacy .gpr/Plan.json must auto-move to .gpr/plans/default/."""
    gpr = tmp_project / ".gpr"
    gpr.mkdir()
    (gpr / "Plan.json").write_text('{"goal": "x", "intents": []}')
    (gpr / "Pinned.md").write_text("invariant")
    (gpr / "Spine.md").write_text("memory")
    (gpr / "Steer.md").write_text("")
    (gpr / "budget.json").write_text('{"tokensInput": 0}')
    runs = gpr / "runs"
    runs.mkdir()
    (runs / "r1").mkdir()
    (runs / "r1" / "evt.log").write_text("hello")

    moved = plan_mod.ensure_migration(tmp_project)

    assert moved is True
    new = tmp_project / ".gpr" / "plans" / "default"
    assert (new / "Plan.json").exists()
    assert (new / "Pinned.md").read_text() == "invariant"
    assert (new / "Spine.md").read_text() == "memory"
    assert (new / "budget.json").exists()
    assert (new / "runs" / "r1" / "evt.log").read_text() == "hello"
    # Legacy paths should be gone.
    assert not (tmp_project / ".gpr" / "Plan.json").exists()
    assert not (tmp_project / ".gpr" / "runs").exists()
    # active slug auto-written
    assert plan_mod.read_active_slug(tmp_project) == "default"


def test_migration_idempotent(tmp_project):
    plan_mod.init(tmp_project, "demo", "g", "main", slug="default")
    # Already in new layout — migration should be a no-op.
    assert plan_mod.ensure_migration(tmp_project) is False


def test_migration_does_not_clobber_existing_default(tmp_project):
    """If both legacy AND new layout coexist (rare), keep new layout."""
    plan_mod.init(tmp_project, "demo", "new", "main", slug="default")
    (tmp_project / ".gpr" / "Plan.json").write_text('{"goal":"old"}')
    moved = plan_mod.ensure_migration(tmp_project)
    assert moved is False
    # The new-layout Plan.json content is preserved.
    body = json.loads(
        (tmp_project / ".gpr" / "plans" / "default" / "Plan.json").read_text()
    )
    assert body["goal"] == "new"


def test_lazy_normalize_fills_missing_fields(tmp_project):
    """Hand-dropped Plan.json under .gpr/plans/<slug>/ gets normalized on load."""
    slug_dir = tmp_project / ".gpr" / "plans" / "extern"
    slug_dir.mkdir(parents=True)
    minimal = {
        "goal": "build it",
        "intents": [
            {"id": "X1", "title": "do it", "checks": [{"id": "C", "description": "x"}]}
        ],
    }
    (slug_dir / "Plan.json").write_text(json.dumps(minimal))

    loaded = plan_mod.load(tmp_project, "extern")

    assert loaded["goal"] == "build it"
    assert loaded["status"] == "pursuing"
    assert loaded["persona"]["primary"] == plan_mod.DEFAULT_PERSONA
    assert "globalState" in loaded
    assert loaded["intents"][0]["status"] == "open"
    assert loaded["intents"][0]["checks"][0]["timeoutSeconds"] == 300
    # File on disk is also updated.
    reread = json.loads((slug_dir / "Plan.json").read_text())
    assert reread["status"] == "pursuing"

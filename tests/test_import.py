"""External plan import: gpr schema, partial JSON, markdown fenced block."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GPR = REPO / "bin" / "gpr"


def _gpr(*args, cwd: Path, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    import os
    env = os.environ.copy()
    env["GPR_HOME"] = str(REPO)
    env["GPR_LIB"] = str(REPO / "lib")
    env["GPR_PROJECT_ROOT"] = str(cwd)
    env["PYTHONPATH"] = str(REPO) + ":" + env.get("PYTHONPATH", "")
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [str(GPR), *args], cwd=cwd, env=env, capture_output=True, text=True, check=False
    )


def test_import_full_plan_json(tmp_project):
    src = tmp_project / "external.json"
    src.write_text(
        json.dumps(
            {
                "schema_version": "1.1.0",
                "project": "ext",
                "goal": "import me",
                "branch": "main",
                "createdAt": "2025-01-01T00:00:00Z",
                "status": "pursuing",
                "qualityGates": [],
                "budget": {"tokens": None, "wallClockSeconds": None, "maxCostUsd": None},
                "intents": [
                    {
                        "id": "I1",
                        "title": "do",
                        "status": "open",
                        "priority": 10,
                        "dependsOn": [],
                        "checks": [
                            {"id": "C", "description": "x", "verifyCmd": "true"}
                        ],
                    }
                ],
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
        )
    )
    r = _gpr("import", str(src), "--name", "ext", "--json", cwd=tmp_project)
    assert r.returncode == 0, r.stderr
    j = json.loads(r.stdout)
    assert j["slug"] == "ext"
    assert (tmp_project / ".gpr" / "plans" / "ext" / "Plan.json").exists()


def test_import_partial_json_normalizes(tmp_project):
    src = tmp_project / "partial.json"
    src.write_text(json.dumps({"goal": "scrap", "intents": []}))
    r = _gpr("import", str(src), "--json", cwd=tmp_project)
    assert r.returncode == 0, r.stderr
    j = json.loads(r.stdout)
    loaded = json.loads(
        (tmp_project / ".gpr" / "plans" / j["slug"] / "Plan.json").read_text()
    )
    assert loaded["status"] == "pursuing"
    assert "persona" in loaded
    assert "globalState" in loaded


def test_import_markdown_fenced_block(tmp_project):
    src = tmp_project / "plan-doc.md"
    src.write_text(
        "# my plan\n\nSome prose.\n\n"
        "```json\n"
        + json.dumps({"goal": "from md", "intents": []})
        + "\n```\n\nmore prose.\n"
    )
    r = _gpr("import", str(src), "--name", "from-md", "--json", cwd=tmp_project)
    assert r.returncode == 0, r.stderr
    j = json.loads(r.stdout)
    assert j["slug"] == "from-md"
    body = json.loads(
        (tmp_project / ".gpr" / "plans" / "from-md" / "Plan.json").read_text()
    )
    assert body["goal"] == "from md"


def test_import_invalid_file_errors(tmp_project):
    src = tmp_project / "garbage.txt"
    src.write_text("just some text")
    r = _gpr("import", str(src), cwd=tmp_project)
    assert r.returncode != 0


def test_import_auto_suffix_on_conflict(tmp_project):
    src = tmp_project / "p.json"
    src.write_text(json.dumps({"goal": "first", "intents": []}))
    _gpr("import", str(src), "--name", "twin", "--json", cwd=tmp_project)
    r = _gpr("import", str(src), "--name", "twin", "--json", cwd=tmp_project)
    assert r.returncode == 0
    j = json.loads(r.stdout)
    assert j["slug"] == "twin-2"


def test_import_activates_when_requested(tmp_project):
    src = tmp_project / "p.json"
    src.write_text(json.dumps({"goal": "g", "intents": []}))
    _gpr("import", str(src), "--name", "myplan", "--activate", cwd=tmp_project)
    active = (tmp_project / ".gpr" / "active").read_text().strip()
    assert active == "myplan"


def test_plan_list_and_use(tmp_project):
    _gpr("init", "--objective", "alpha", "--plan", "alpha", cwd=tmp_project)
    _gpr("init", "--objective", "beta", "--plan", "beta", cwd=tmp_project)
    r = _gpr("plan", "list", "--json", cwd=tmp_project)
    assert r.returncode == 0, r.stderr
    j = json.loads(r.stdout)
    slugs = [p["slug"] for p in j["plans"]]
    assert "alpha" in slugs and "beta" in slugs
    _gpr("plan", "use", "beta", cwd=tmp_project)
    assert (tmp_project / ".gpr" / "active").read_text().strip() == "beta"

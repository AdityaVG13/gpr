"""Seed a Plan.json for the demo recording."""
import json
import sys
from pathlib import Path

p = json.load(open(".gpr/Plan.json"))
p["intents"] = [
    {
        "id": "I001",
        "title": "Scaffold + DB",
        "status": "done",
        "priority": 10,
        "dependsOn": [],
        "checks": [
            {
                "id": "C1",
                "description": "pyproject + alembic",
                "verifyCmd": "test -f pyproject.toml",
                "timeoutSeconds": 5,
                "retries": 1,
            }
        ],
        "proofs": [
            {
                "checkId": "C1",
                "type": "cmd_exit_0",
                "verifiedAt": "2026-05-08T00:00:00Z",
            }
        ],
        "startedAt": None,
        "completedAt": "2026-05-08T00:01:00Z",
        "auditFailures": [],
    },
    {
        "id": "I002",
        "title": "JWT auth flow",
        "status": "in_progress",
        "priority": 20,
        "dependsOn": ["I001"],
        "checks": [
            {
                "id": "C1",
                "description": "login issues JWT",
                "verifyCmd": "pytest -k test_login_jwt",
                "timeoutSeconds": 30,
                "retries": 2,
            }
        ],
        "proofs": [],
        "startedAt": "2026-05-08T00:01:00Z",
        "completedAt": None,
        "auditFailures": [],
    },
    {
        "id": "I003",
        "title": "CRUD endpoints",
        "status": "open",
        "priority": 30,
        "dependsOn": ["I002"],
        "checks": [
            {
                "id": "C1",
                "description": "GET /todos returns 200",
                "verifyCmd": "pytest -k test_get_todos",
                "timeoutSeconds": 30,
                "retries": 2,
            }
        ],
        "proofs": [],
        "startedAt": None,
        "completedAt": None,
        "auditFailures": [],
    },
]
p["budget"] = {"tokens": 1_000_000, "wallClockSeconds": 7200, "maxCostUsd": 25.0}
p["globalState"]["iteration"] = 4
p["qualityGates"] = [
    {"name": "tests", "cmd": "pytest -q", "required": True},
    {"name": "lint", "cmd": "ruff check .", "required": True},
]
json.dump(p, open(".gpr/Plan.json", "w"), indent=2)

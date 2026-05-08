"""JSONL append-only event bus, rotated per run."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def events_path(project_root: str | Path, run_id: str | None = None) -> Path:
    base = Path(project_root) / ".gpr"
    if run_id:
        return base / "runs" / run_id / "events.jsonl"
    return base / "events.jsonl"


def emit(
    project_root: str | Path,
    kind: str,
    payload: dict[str, Any],
    run_id: str | None = None,
) -> None:
    p = events_path(project_root, run_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    record = {"t": time.time(), "kind": kind, **payload}
    with open(p, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def tail(
    project_root: str | Path, n: int = 100, run_id: str | None = None
) -> list[dict[str, Any]]:
    p = events_path(project_root, run_id)
    if not p.exists():
        return []
    with open(p) as f:
        lines = f.readlines()
    out: list[dict[str, Any]] = []
    for line in lines[-n:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out

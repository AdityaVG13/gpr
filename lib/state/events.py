"""JSONL append-only event bus, scoped per plan and (optionally) per run."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

DEFAULT_SLUG = "default"


def events_path(
    project_root: str | Path,
    slug: str = DEFAULT_SLUG,
    run_id: str | None = None,
) -> Path:
    base = Path(project_root) / ".gpr" / "plans" / slug
    if run_id:
        return base / "runs" / run_id / "events.jsonl"
    return base / "events.jsonl"


def emit(
    project_root: str | Path,
    kind: str,
    payload: dict[str, Any],
    slug: str = DEFAULT_SLUG,
    run_id: str | None = None,
) -> None:
    p = events_path(project_root, slug, run_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    record = {"t": time.time(), "kind": kind, **payload}
    with open(p, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def tail(
    project_root: str | Path,
    n: int = 100,
    slug: str = DEFAULT_SLUG,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    p = events_path(project_root, slug, run_id)
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

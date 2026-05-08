"""Budget accounting: tokens, wall-clock, USD. Soft-stop wrap-up at 95%."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

WRAP_UP_FRACTION = 0.95
HARD_STOP_FRACTION = 1.0

DEFAULT_RATES_USD_PER_MTOK: dict[str, dict[str, float]] = {
    "claude-opus-4-7": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5": {"input": 0.80, "output": 4.0},
    "gpt-5-codex": {"input": 1.25, "output": 10.0},
    "default": {"input": 5.0, "output": 25.0},
}


def empty_budget_state() -> dict[str, Any]:
    return {
        "tokensInput": 0,
        "tokensOutput": 0,
        "wallClockSeconds": 0.0,
        "costUsd": 0.0,
        "perAgent": {},
        "wrapUpEntered": False,
        "lastUpdate": None,
    }


def budget_path(project_root: str | Path) -> Path:
    return Path(project_root) / ".gpr" / "budget.json"


def load(project_root: str | Path) -> dict[str, Any]:
    p = budget_path(project_root)
    if not p.exists():
        return empty_budget_state()
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return empty_budget_state()


def save(project_root: str | Path, state: dict[str, Any]) -> None:
    p = budget_path(project_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    tmp.replace(p)


def add_iteration(
    state: dict[str, Any],
    agent: str,
    model: str,
    tokens_input: int,
    tokens_output: int,
    wall_seconds: float,
) -> dict[str, Any]:
    state["tokensInput"] = state.get("tokensInput", 0) + tokens_input
    state["tokensOutput"] = state.get("tokensOutput", 0) + tokens_output
    state["wallClockSeconds"] = round(
        state.get("wallClockSeconds", 0.0) + wall_seconds, 3
    )
    rates = DEFAULT_RATES_USD_PER_MTOK.get(model) or DEFAULT_RATES_USD_PER_MTOK["default"]
    cost = (tokens_input / 1_000_000) * rates["input"] + (
        tokens_output / 1_000_000
    ) * rates["output"]
    state["costUsd"] = round(state.get("costUsd", 0.0) + cost, 6)
    per = state.setdefault("perAgent", {}).setdefault(
        agent, {"tokensInput": 0, "tokensOutput": 0, "wallClockSeconds": 0.0, "costUsd": 0.0, "iterations": 0}
    )
    per["tokensInput"] += tokens_input
    per["tokensOutput"] += tokens_output
    per["wallClockSeconds"] = round(per["wallClockSeconds"] + wall_seconds, 3)
    per["costUsd"] = round(per["costUsd"] + cost, 6)
    per["iterations"] += 1
    state["lastUpdate"] = time.time()
    return state


def status(plan: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Compare current spend against plan budget; return status dict.

    fraction_used is the max across all configured budget axes.
    """
    budget = plan.get("budget") or {}
    fractions: list[tuple[str, float]] = []
    if budget.get("tokens"):
        used = state["tokensInput"] + state["tokensOutput"]
        fractions.append(("tokens", used / budget["tokens"]))
    if budget.get("wallClockSeconds"):
        fractions.append(
            ("wallClockSeconds", state["wallClockSeconds"] / budget["wallClockSeconds"])
        )
    if budget.get("maxCostUsd"):
        fractions.append(("costUsd", state["costUsd"] / budget["maxCostUsd"]))
    if not fractions:
        return {"fraction_used": 0.0, "binding_axis": None, "wrap_up": False, "hard_stop": False}
    binding_axis, fraction = max(fractions, key=lambda kv: kv[1])
    return {
        "fraction_used": fraction,
        "binding_axis": binding_axis,
        "wrap_up": fraction >= WRAP_UP_FRACTION and fraction < HARD_STOP_FRACTION,
        "hard_stop": fraction >= HARD_STOP_FRACTION,
        "all_axes": dict(fractions),
    }


def parse_claude_stream_usage(stream_lines: list[str]) -> tuple[int, int]:
    """Sum input/output tokens from a Claude `--output-format stream-json` log."""
    in_total = 0
    out_total = 0
    for line in stream_lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        usage = obj.get("usage") or (obj.get("message") or {}).get("usage")
        if not isinstance(usage, dict):
            continue
        in_total += int(usage.get("input_tokens", 0) or 0)
        in_total += int(usage.get("cache_read_input_tokens", 0) or 0)
        in_total += int(usage.get("cache_creation_input_tokens", 0) or 0)
        out_total += int(usage.get("output_tokens", 0) or 0)
    return in_total, out_total


def parse_codex_usage(stream_lines: list[str]) -> tuple[int, int]:
    """Best-effort parse of codex --json output for token usage."""
    in_total = 0
    out_total = 0
    for line in stream_lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = obj.get("msg") or obj
        if msg.get("type") in ("token_count", "usage"):
            in_total += int(msg.get("input_tokens", 0) or 0)
            out_total += int(msg.get("output_tokens", 0) or 0)
    return in_total, out_total


PARSER_REGISTRY = {
    "claude": parse_claude_stream_usage,
    "codex": parse_codex_usage,
}


def parse_usage(agent: str, stream_lines: list[str]) -> tuple[int, int]:
    parser = PARSER_REGISTRY.get(agent)
    if parser is None:
        return (0, 0)
    return parser(stream_lines)

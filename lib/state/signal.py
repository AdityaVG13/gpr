"""Parse the structured trailer block emitted by the agent each iteration.

Format (cleanroom-original; not snarktank's <promise> tags):

    ---gpr-signal---
    {"status":"done","intent":"S001","checks_attempted":["AC1"],
     "memory":{"mode":"append","content":"..."}}
    ---end---

JSON between delimiters keeps parsing trivial and unambiguous.
"""

from __future__ import annotations

import json
import re
from typing import Any

SIGNAL_OPEN = "---gpr-signal---"
SIGNAL_CLOSE = "---end---"
VERDICT_OPEN = "---gpr-audit-verdict---"
REVERSE_OPEN = "---gpr-reverse-audit---"
VALID_STATUSES = {"done", "blocked", "decide", "rescope", "progress"}
VALID_MEMORY_MODES = {"append", "rewrite"}
VALID_VERDICTS = {"pass", "fail"}
VALID_RECOMMENDS = {"keep_done", "revert_to_open", "rescope"}
VALID_REVERSE_RECOMMENDS = {
    "declare_achieved",
    "reopen_intents",
    "add_intents",
    "rescope",
}

_PATTERN = re.compile(
    r"^[ \t]*" + re.escape(SIGNAL_OPEN) + r"[ \t]*\n(.*?)\n[ \t]*"
    + re.escape(SIGNAL_CLOSE) + r"[ \t]*$",
    re.MULTILINE | re.DOTALL,
)
_VERDICT_PATTERN = re.compile(
    r"^[ \t]*" + re.escape(VERDICT_OPEN) + r"[ \t]*\n(.*?)\n[ \t]*"
    + re.escape(SIGNAL_CLOSE) + r"[ \t]*$",
    re.MULTILINE | re.DOTALL,
)
_REVERSE_PATTERN = re.compile(
    r"^[ \t]*" + re.escape(REVERSE_OPEN) + r"[ \t]*\n(.*?)\n[ \t]*"
    + re.escape(SIGNAL_CLOSE) + r"[ \t]*$",
    re.MULTILINE | re.DOTALL,
)

REFUSAL_PATTERNS = [
    r"\bI can't help with that\b",
    r"\bI'm unable to assist\b",
    r"\bI cannot help\b",
    r"\bI won't be able to\b",
]


class SignalError(ValueError):
    pass


def extract_raw(text: str) -> str | None:
    """Return the JSON body of the LAST signal block in text, or None."""
    matches = list(_PATTERN.finditer(text))
    if not matches:
        return None
    return matches[-1].group(1).strip()


def parse(text: str) -> dict[str, Any]:
    """Extract and validate a signal from agent output. Raises SignalError on miss/invalid."""
    raw = extract_raw(text)
    if raw is None:
        if _looks_like_refusal(text):
            return {
                "status": "blocked",
                "reason": "agent_refusal",
                "intent": None,
                "checks_attempted": [],
                "memory": None,
                "_synthetic": True,
            }
        raise SignalError("no ---gpr-signal--- block found in output")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SignalError(f"invalid JSON in signal block: {exc}") from exc
    if not isinstance(data, dict):
        raise SignalError("signal must be a JSON object")
    return validate(data)


def validate(data: dict[str, Any]) -> dict[str, Any]:
    status = data.get("status")
    if status not in VALID_STATUSES:
        raise SignalError(
            f"status must be one of {sorted(VALID_STATUSES)}, got {status!r}"
        )

    if status in {"blocked", "decide", "rescope"} and not data.get("reason"):
        raise SignalError(f"status={status} requires non-empty reason")

    intent = data.get("intent")
    if status in {"done", "progress"} and not intent:
        raise SignalError(f"status={status} requires intent id")

    checks = data.get("checks_attempted") or []
    if not isinstance(checks, list) or not all(isinstance(c, str) for c in checks):
        raise SignalError("checks_attempted must be a list of strings")

    memory = data.get("memory")
    if memory is not None:
        if not isinstance(memory, dict):
            raise SignalError("memory must be an object")
        mode = memory.get("mode", "append")
        if mode not in VALID_MEMORY_MODES:
            raise SignalError(f"memory.mode must be one of {sorted(VALID_MEMORY_MODES)}")
        if not isinstance(memory.get("content", ""), str):
            raise SignalError("memory.content must be a string")
        if "reason" in memory and not isinstance(memory["reason"], str):
            raise SignalError("memory.reason must be a string")
        if mode == "rewrite" and not memory.get("reason"):
            raise SignalError("memory.mode=rewrite requires memory.reason")

    return {
        "status": status,
        "reason": data.get("reason", ""),
        "intent": intent,
        "checks_attempted": checks,
        "memory": memory,
        "_synthetic": False,
    }


def _looks_like_refusal(text: str) -> bool:
    tail = text[-2000:]
    return any(re.search(p, tail, re.IGNORECASE) for p in REFUSAL_PATTERNS)


def parse_audit_verdict(text: str) -> dict[str, Any]:
    """Parse a Layer-2 auditor's verdict block."""
    matches = list(_VERDICT_PATTERN.finditer(text))
    if not matches:
        raise SignalError("no ---gpr-audit-verdict--- block found")
    raw = matches[-1].group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SignalError(f"invalid JSON in verdict: {exc}") from exc
    if data.get("verdict") not in VALID_VERDICTS:
        raise SignalError(
            f"verdict must be one of {sorted(VALID_VERDICTS)}, got {data.get('verdict')!r}"
        )
    reasons = data.get("reasons") or []
    if not isinstance(reasons, list) or not all(isinstance(r, str) for r in reasons):
        raise SignalError("reasons must be a list of strings")
    if data.get("recommend") not in VALID_RECOMMENDS:
        raise SignalError(
            f"recommend must be one of {sorted(VALID_RECOMMENDS)}, got {data.get('recommend')!r}"
        )
    return {
        "verdict": data["verdict"],
        "reasons": reasons,
        "recommend": data["recommend"],
    }


def parse_reverse_audit(text: str) -> dict[str, Any]:
    """Parse a reverse-audit verdict block."""
    matches = list(_REVERSE_PATTERN.finditer(text))
    if not matches:
        raise SignalError("no ---gpr-reverse-audit--- block found")
    raw = matches[-1].group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SignalError(f"invalid JSON in reverse audit: {exc}") from exc
    if not isinstance(data.get("clean"), bool):
        raise SignalError("clean must be a boolean")
    regs = data.get("regressions") or []
    gaps = data.get("goal_gaps") or []
    if not isinstance(regs, list) or not isinstance(gaps, list):
        raise SignalError("regressions and goal_gaps must be lists")
    if data.get("recommendation") not in VALID_REVERSE_RECOMMENDS:
        raise SignalError(
            f"recommendation must be one of {sorted(VALID_REVERSE_RECOMMENDS)}"
        )
    return {
        "clean": data["clean"],
        "regressions": regs,
        "goal_gaps": gaps,
        "recommendation": data["recommendation"],
    }


def render_help() -> str:
    """The signal grammar, for inclusion in continuation prompts."""
    return (
        "Emit exactly one signal block at the end of your response.\n"
        f"Format:\n  {SIGNAL_OPEN}\n  <single-line JSON>\n  {SIGNAL_CLOSE}\n"
        "Schema:\n"
        '  status: "done" | "blocked" | "decide" | "rescope" | "progress"\n'
        "  reason: string (required for blocked/decide/rescope)\n"
        "  intent: string (required for done/progress)\n"
        "  checks_attempted: [string] (Check ids you tried to satisfy)\n"
        '  memory: {mode:"append"|"rewrite", content:string, reason:string?}\n'
        "Notes:\n"
        '  - "done" only signals you BELIEVE the intent is complete.\n'
        "    The audit will run verifyCmd for each Check before marking done.\n"
        "  - memory.mode=rewrite requires memory.reason explaining the rewrite.\n"
        "  - The signal block must be the LAST thing in your response."
    )

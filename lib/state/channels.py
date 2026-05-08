"""Channel registry for prompt-output protocols.

Every prompt the loop sends to an agent expects exactly one structured
trailer block back. Today there are six such protocols: the iteration
signal, the Layer-2 audit verdict, the reverse-audit verdict, the
confidence-audit verdict, the commit message, and the PR description.

Each protocol has the same shape — open delimiter, JSON body, close
delimiter — and only differs in: the open delimiter, the schema of the
JSON, and the on-success side-effect the loop applies.

This module is the single source of truth for the first two. The
side-effect step lives in cli.py's `cmd_ingest_*` handlers; channels
here just parse and validate.

Adding a seventh protocol is a single CHANNELS entry — no new parser
file, no new argparse handler.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from . import signal as signal_mod


def _normalize_agent_output(text: str) -> str:
    """Return plain agent text, transparently unwrapping `claude --output-format
    stream-json` line-delimited JSON.

    The agent's structured trailer block (`---gpr-signal---` …) lives inside the
    `result` field of the final `{"type":"result"}` message and inside the
    `text` fields of `{"type":"assistant"}` content arrays. In stream-json mode
    the embedded newlines are JSON-escaped (`\\n`), so the channel regexes —
    which require real newlines — never match. We pull the textual payload out
    of every JSON line we can recognise and concatenate it with real newlines.

    If `text` is not stream-json (no JSON lines, or no extractable text), it is
    returned unchanged so the existing parsers still see plaintext input.
    """
    pieces: list[str] = []
    matched_any = False
    for line in text.splitlines():
        s = line.strip()
        if not s or not (s.startswith("{") and s.endswith("}")):
            continue
        try:
            obj = json.loads(s)
        except (ValueError, TypeError):
            continue
        if not isinstance(obj, dict):
            continue
        if "type" not in obj:
            continue
        matched_any = True
        result = obj.get("result")
        if isinstance(result, str) and result:
            pieces.append(result)
            continue
        message = obj.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        t = part.get("text")
                        if isinstance(t, str) and t:
                            pieces.append(t)
    if not matched_any or not pieces:
        return text
    return "\n".join(pieces)


@dataclass(frozen=True)
class Channel:
    name: str
    open_delim: str
    close_delim: str
    parser: Callable[[str], Any]
    description: str


CHANNELS: dict[str, Channel] = {
    "signal": Channel(
        name="signal",
        open_delim=signal_mod.SIGNAL_OPEN,
        close_delim=signal_mod.SIGNAL_CLOSE,
        parser=signal_mod.parse,
        description="iteration signal — done/progress/blocked/decide/rescope",
    ),
    "audit_verdict": Channel(
        name="audit_verdict",
        open_delim=signal_mod.VERDICT_OPEN,
        close_delim=signal_mod.SIGNAL_CLOSE,
        parser=signal_mod.parse_audit_verdict,
        description="Layer-2 cross-model auditor verdict",
    ),
    "reverse_audit": Channel(
        name="reverse_audit",
        open_delim=signal_mod.REVERSE_OPEN,
        close_delim=signal_mod.SIGNAL_CLOSE,
        parser=signal_mod.parse_reverse_audit,
        description="end-of-run spec-drift sweep verdict",
    ),
    "confidence_audit": Channel(
        name="confidence_audit",
        open_delim="---gpr-confidence-audit---",
        close_delim=signal_mod.SIGNAL_CLOSE,
        parser=signal_mod.parse_confidence_audit,
        description="pre-run Plan-loophole scrutiny verdict",
    ),
    "commit": Channel(
        name="commit",
        open_delim="---gpr-commit---",
        close_delim=signal_mod.SIGNAL_CLOSE,
        parser=signal_mod.parse_commit_message,
        description="conventional-commits message for one intent's diff",
    ),
    "pr": Channel(
        name="pr",
        open_delim="---gpr-pr---",
        close_delim=signal_mod.SIGNAL_CLOSE,
        parser=signal_mod.parse_pr_description,
        description="end-of-run PR description",
    ),
}


def get(name: str) -> Channel:
    """Return the named Channel or raise KeyError."""
    if name not in CHANNELS:
        raise KeyError(
            f"unknown channel {name!r}; known: {sorted(CHANNELS.keys())}"
        )
    return CHANNELS[name]


def parse(name: str, text: str) -> Any:
    """Dispatch parsing to the named channel's parser. Raises SignalError on
    bad input or KeyError on unknown channel name."""
    return get(name).parser(_normalize_agent_output(text))


def list_channels() -> list[dict[str, str]]:
    """Catalogue for `gpr config keys` / docs / CLI introspection."""
    return [
        {
            "name": ch.name,
            "open": ch.open_delim,
            "close": ch.close_delim,
            "description": ch.description,
        }
        for ch in CHANNELS.values()
    ]

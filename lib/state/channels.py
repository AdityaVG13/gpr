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

from dataclasses import dataclass
from typing import Any, Callable

from . import signal as signal_mod


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
    return get(name).parser(text)


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

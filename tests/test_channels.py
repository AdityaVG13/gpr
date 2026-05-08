"""Channel dispatch + stream-json normalization."""

from __future__ import annotations

import json

import pytest

from lib.state import channels as channels_mod
from lib.state import signal as signal_mod


def test_parse_plain_signal():
    text = """\
---gpr-signal---
{"status":"done","intent":"I1","checks_attempted":["C1"]}
---end---
"""
    s = channels_mod.parse("signal", text)
    assert s["status"] == "done"
    assert s["intent"] == "I1"


def test_parse_signal_inside_claude_stream_json_result():
    """`claude --output-format stream-json` JSON-escapes the signal block's
    newlines inside the final result message; the channel dispatcher must
    unwrap it before the regex parser runs."""
    body = (
        "Some prose explaining the work.\n"
        "---gpr-signal---\n"
        '{"status":"done","intent":"B001","checks_attempted":["C1"]}\n'
        "---end---"
    )
    stream = "\n".join(
        [
            json.dumps({"type": "system", "subtype": "init"}),
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "thinking", "thinking": "..."},
                        ]
                    },
                }
            ),
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "result": body,
                    "stop_reason": "end_turn",
                }
            ),
        ]
    )
    s = channels_mod.parse("signal", stream)
    assert s["status"] == "done"
    assert s["intent"] == "B001"
    assert s["checks_attempted"] == ["C1"]


def test_parse_signal_from_assistant_text_blocks():
    """When no `result` line appears, fall back to assistant `text` content."""
    body = (
        "---gpr-signal---\n"
        '{"status":"progress","intent":"X1","memory":{"mode":"append","content":"x"}}\n'
        "---end---"
    )
    stream = "\n".join(
        [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": "preamble\n"},
                            {"type": "text", "text": body},
                        ]
                    },
                }
            ),
        ]
    )
    s = channels_mod.parse("signal", stream)
    assert s["status"] == "progress"
    assert s["intent"] == "X1"


def test_plain_text_without_json_passes_through():
    """Codex / opencode / gemini / echo emit plaintext; normalization must
    not corrupt their output."""
    text = (
        "{not json}\n"
        "---gpr-signal---\n"
        '{"status":"done","intent":"Z1","checks_attempted":[]}\n'
        "---end---\n"
    )
    s = channels_mod.parse("signal", text)
    assert s["status"] == "done"
    assert s["intent"] == "Z1"


def test_audit_verdict_through_stream_json():
    body = (
        "---gpr-audit-verdict---\n"
        '{"verdict":"pass","reasons":["ok"],"recommend":"keep_done"}\n'
        "---end---"
    )
    stream = json.dumps(
        {"type": "result", "subtype": "success", "result": body}
    )
    v = channels_mod.parse("audit_verdict", stream)
    assert v["verdict"] == "pass"
    assert v["recommend"] == "keep_done"


def test_no_block_in_stream_json_still_raises():
    stream = json.dumps(
        {"type": "result", "subtype": "success", "result": "all done, no block"}
    )
    with pytest.raises(signal_mod.SignalError, match="no .* block"):
        channels_mod.parse("signal", stream)

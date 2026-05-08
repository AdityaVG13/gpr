"""Signal block parsing + validation."""

from __future__ import annotations

import pytest

from lib.state import signal as signal_mod


def test_parse_done():
    text = """\
some prose
---gpr-signal---
{"status":"done","intent":"I1","checks_attempted":["C1"]}
---end---
"""
    s = signal_mod.parse(text)
    assert s["status"] == "done"
    assert s["intent"] == "I1"
    assert s["checks_attempted"] == ["C1"]


def test_parse_blocked_requires_reason():
    text = """\
---gpr-signal---
{"status":"blocked","intent":"I1"}
---end---
"""
    with pytest.raises(signal_mod.SignalError, match="reason"):
        signal_mod.parse(text)


def test_parse_done_requires_intent():
    text = """\
---gpr-signal---
{"status":"done","checks_attempted":[]}
---end---
"""
    with pytest.raises(signal_mod.SignalError, match="intent"):
        signal_mod.parse(text)


def test_parse_invalid_status():
    text = """\
---gpr-signal---
{"status":"garbage","intent":"I1"}
---end---
"""
    with pytest.raises(signal_mod.SignalError, match="status"):
        signal_mod.parse(text)


def test_parse_memory_rewrite_requires_reason():
    text = """\
---gpr-signal---
{"status":"progress","intent":"I1","memory":{"mode":"rewrite","content":""}}
---end---
"""
    with pytest.raises(signal_mod.SignalError, match="reason"):
        signal_mod.parse(text)


def test_parse_memory_append_no_reason_required():
    text = """\
---gpr-signal---
{"status":"progress","intent":"I1","memory":{"mode":"append","content":"learned X"}}
---end---
"""
    s = signal_mod.parse(text)
    assert s["memory"]["mode"] == "append"


def test_parse_no_block_raises():
    with pytest.raises(signal_mod.SignalError, match="no .* block"):
        signal_mod.parse("totally normal output, no signal here")


def test_refusal_detected_synthetically():
    s = signal_mod.parse("I cannot help with that request.")
    assert s["status"] == "blocked"
    assert s["_synthetic"] is True


def test_last_block_wins_on_multiple():
    text = """\
---gpr-signal---
{"status":"progress","intent":"I1"}
---end---

later thinking changed mind:

---gpr-signal---
{"status":"done","intent":"I1","checks_attempted":["C1"]}
---end---
"""
    s = signal_mod.parse(text)
    assert s["status"] == "done"


def test_invalid_json_raises():
    text = """\
---gpr-signal---
{this is not json
---end---
"""
    with pytest.raises(signal_mod.SignalError, match="invalid JSON"):
        signal_mod.parse(text)

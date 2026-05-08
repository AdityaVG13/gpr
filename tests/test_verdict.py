"""Layer-2 + reverse-audit verdict parsers."""

from __future__ import annotations

import pytest

from lib.state import signal as sm


def test_audit_verdict_pass():
    text = """\
analysis here
---gpr-audit-verdict---
{"verdict":"pass","reasons":[],"recommend":"keep_done"}
---end---
"""
    v = sm.parse_audit_verdict(text)
    assert v["verdict"] == "pass"
    assert v["recommend"] == "keep_done"


def test_audit_verdict_fail_with_reasons():
    text = """\
---gpr-audit-verdict---
{"verdict":"fail","reasons":["weak verifyCmd","intent/impl mismatch"],"recommend":"revert_to_open"}
---end---
"""
    v = sm.parse_audit_verdict(text)
    assert v["verdict"] == "fail"
    assert len(v["reasons"]) == 2


def test_audit_verdict_invalid_recommend():
    text = """\
---gpr-audit-verdict---
{"verdict":"pass","reasons":[],"recommend":"merge_now"}
---end---
"""
    with pytest.raises(sm.SignalError, match="recommend"):
        sm.parse_audit_verdict(text)


def test_audit_verdict_missing_block():
    with pytest.raises(sm.SignalError, match="no .* block"):
        sm.parse_audit_verdict("just prose, no verdict")


def test_reverse_audit_clean():
    text = """\
---gpr-reverse-audit---
{"clean":true,"regressions":[],"goal_gaps":[],"recommendation":"declare_achieved"}
---end---
"""
    v = sm.parse_reverse_audit(text)
    assert v["clean"] is True
    assert v["recommendation"] == "declare_achieved"


def test_reverse_audit_regressions():
    text = """\
---gpr-reverse-audit---
{"clean":false,"regressions":[{"intent":"I1","check":"C1","reason":"broken"}],"goal_gaps":[],"recommendation":"reopen_intents"}
---end---
"""
    v = sm.parse_reverse_audit(text)
    assert v["clean"] is False
    assert v["regressions"][0]["intent"] == "I1"


def test_reverse_audit_goal_gaps():
    text = """\
---gpr-reverse-audit---
{"clean":false,"regressions":[],"goal_gaps":["no auth flow built"],"recommendation":"add_intents"}
---end---
"""
    v = sm.parse_reverse_audit(text)
    assert v["recommendation"] == "add_intents"
    assert "auth" in v["goal_gaps"][0]

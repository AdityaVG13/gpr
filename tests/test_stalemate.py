"""Stalemate detection + case-split stall notes."""

from __future__ import annotations

from lib.state import stalemate as stm


def _empty_plan_state():
    return {
        "globalState": {
            "consecutiveSameSignature": 0,
            "lastPayloadHash": None,
            "lastCheckboxCount": [0, 0],
        }
    }


def test_first_iteration_initialises_counter():
    p = _empty_plan_state()
    stalled, _ = stm.update_signature(p, "h1", (0, 0))
    assert p["globalState"]["consecutiveSameSignature"] == 1
    assert not stalled


def test_progress_resets_counter():
    p = _empty_plan_state()
    stm.update_signature(p, "h1", (0, 0))
    stm.update_signature(p, "h1", (0, 0))
    stm.update_signature(p, "h2", (0, 0))
    assert p["globalState"]["consecutiveSameSignature"] == 1


def test_stalemate_at_threshold():
    p = _empty_plan_state()
    results = []
    for _ in range(stm.STALEMATE_THRESHOLD):
        stalled, _ = stm.update_signature(p, "samehash", (1, 5))
        results.append(stalled)
    assert results[-1] is True
    assert all(r is False for r in results[:-1])


def test_checkbox_change_breaks_stalemate():
    p = _empty_plan_state()
    for _ in range(3):
        stm.update_signature(p, "samehash", (1, 5))
    stalled, _ = stm.update_signature(p, "samehash", (0, 5))
    assert not stalled
    assert p["globalState"]["consecutiveSameSignature"] == 1


def test_stall_note_no_op():
    n = stm.stall_note(False, False, 4)
    assert "no-op" in n
    assert "smaller" in n.lower() or "smaller concrete subtask" in n


def test_stall_note_plan_without_code_is_strongest_warning():
    n = stm.stall_note(False, True, 4)
    assert "plan-without-code" in n
    assert "dangerous" in n.lower()


def test_stall_note_code_without_plan():
    n = stm.stall_note(True, False, 4)
    assert "code-without-plan-update" in n


def test_checkbox_count_parser(tmp_project):
    spine = tmp_project / "Spine.md"
    spine.write_text(
        "intro\n"
        "- [x] done\n"
        "- [ ] open\n"
        "  - [ ] nested open\n"
        "  - [X] nested done\n"
    )
    o, t = stm.checkbox_count(spine)
    assert (o, t) == (2, 4)


def test_checkbox_count_missing_file(tmp_project):
    o, t = stm.checkbox_count(tmp_project / "no-such.md")
    assert (o, t) == (0, 0)

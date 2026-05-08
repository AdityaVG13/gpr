"""Budget accumulation, parsing, soft/hard stops."""

from __future__ import annotations

from lib.state import budget as bm


def test_empty_status_no_budget():
    plan = {"budget": {}}
    state = bm.empty_budget_state()
    s = bm.status(plan, state)
    assert s["fraction_used"] == 0.0
    assert s["binding_axis"] is None


def test_token_axis_dominates():
    plan = {"budget": {"tokens": 100, "wallClockSeconds": 10000, "maxCostUsd": 1000.0}}
    state = bm.empty_budget_state()
    bm.add_iteration(state, "claude", "claude-opus-4-7",
                     tokens_input=50, tokens_output=50, wall_seconds=1.0)
    s = bm.status(plan, state)
    assert s["binding_axis"] == "tokens"
    assert s["fraction_used"] >= 1.0
    assert s["hard_stop"] is True


def test_wrap_up_window():
    plan = {"budget": {"tokens": 100}}
    state = bm.empty_budget_state()
    bm.add_iteration(state, "claude", "claude-opus-4-7", 96, 0, 0.0)
    s = bm.status(plan, state)
    assert s["wrap_up"] is True
    assert s["hard_stop"] is False


def test_cost_calculation_known_model():
    state = bm.empty_budget_state()
    bm.add_iteration(state, "claude", "claude-opus-4-7",
                     tokens_input=1_000_000, tokens_output=1_000_000,
                     wall_seconds=1.0)
    assert state["costUsd"] == 90.0  # 15 + 75


def test_cost_falls_back_to_default_for_unknown_model():
    state = bm.empty_budget_state()
    bm.add_iteration(state, "claude", "future-model-x",
                     tokens_input=1_000_000, tokens_output=0, wall_seconds=1.0)
    assert state["costUsd"] == 5.0


def test_per_agent_breakdown():
    state = bm.empty_budget_state()
    bm.add_iteration(state, "claude", "claude-opus-4-7", 100, 0, 1.0)
    bm.add_iteration(state, "claude", "claude-opus-4-7", 100, 0, 1.0)
    bm.add_iteration(state, "codex", "gpt-5-codex", 200, 0, 2.0)
    assert state["perAgent"]["claude"]["iterations"] == 2
    assert state["perAgent"]["codex"]["iterations"] == 1
    assert state["perAgent"]["claude"]["tokensInput"] == 200


def test_claude_stream_parser_sums_cache_tokens():
    lines = [
        '{"type":"system"}',
        '{"type":"assistant","message":{"usage":{"input_tokens":10,"cache_read_input_tokens":5,"cache_creation_input_tokens":3,"output_tokens":7}}}',
        '{"type":"result"}',
    ]
    i, o = bm.parse_claude_stream_usage(lines)
    assert i == 18
    assert o == 7


def test_codex_parser_handles_token_count_msg():
    lines = [
        '{"msg":{"type":"token_count","input_tokens":100,"output_tokens":50}}',
        '{"msg":{"type":"task_complete"}}',
    ]
    i, o = bm.parse_codex_usage(lines)
    assert (i, o) == (100, 50)


def test_unknown_agent_zero_tokens():
    i, o = bm.parse_usage("nonexistent-agent", ["whatever"])
    assert (i, o) == (0, 0)

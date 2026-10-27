import json
from datetime import date

import pytest

from core.base import Usage
from core.debate import (
    MAX_TOKEN_BUDGET,
    MIN_TOKEN_BUDGET,
    Debate,
    DebateConfig,
    format_usd,
    list_logs,
    save_log,
)
from core.mock_client import MockClient
from core.pricing import cost_usd, price_for
from tests.test_debate import GOOD_CRITIQUE, ScriptedClient


def clients(claude_model="claude-opus-5-5", gemini_model="gemini-3.8-flash"):
    claude = ScriptedClient("Claude", [], model=claude_model)
    gemini = ScriptedClient("Gemini", [GOOD_CRITIQUE] * 10, model=gemini_model)
    return {"Claude": claude, "Gemini": gemini}


# ---- pricing ---------------------------------------------------------------
def test_price_lookup_and_mock_prefix():
    assert price_for("claude-opus-5-5") == (4.00, 20.00)
    assert price_for("mock:claude-opus-5-5") == (4.00, 20.00)
    assert price_for("unknown-model") is None


def test_price_changes_on_effective_date():
    assert price_for("gemini-3.8-flash", date(2026, 12, 31)) == (0.75, 3.75)
    assert price_for("gemini-3.8-flash", date(2027, 1, 1)) == (1.50, 7.50)
    assert price_for("gemini-4-argon", date(2026, 12, 1)) == (4.00, 20.00)


def test_cost_usd():
    usage = Usage(input_tokens=1_000_000, output_tokens=100_000)
    assert cost_usd("claude-opus-5-5", usage) == pytest.approx(4.0 + 2.0)
    assert cost_usd("nope", usage) is None


def test_debate_cost_totals():
    debate = Debate(DebateConfig(task="x", rounds=1), clients())
    list(debate.run())
    # ScriptedClient reports 10 in / 5 out per call: Claude 2 calls, Gemini 1 call.
    claude = (20 * 4.00 + 10 * 20.00) / 1e6
    gemini = (10 * 0.75 + 5 * 3.75) / 1e6
    assert debate.cost_by_provider["Claude"] == pytest.approx(claude)
    assert debate.total_cost == pytest.approx(claude + gemini)


def test_unknown_model_cost_is_none():
    debate = Debate(DebateConfig(task="x", rounds=1), clients(claude_model="custom"))
    list(debate.run())
    assert debate.cost_by_provider["Claude"] is None
    assert debate.total_cost is None
    assert format_usd(None) == "chưa rõ giá"


def test_format_usd():
    assert format_usd(0.01234) == "~$0.0123"
    assert format_usd(12.5) == "~$12.50"


# ---- token budget ----------------------------------------------------------
@pytest.mark.parametrize("value,expected", [(0, MIN_TOKEN_BUDGET), (10**9, MAX_TOKEN_BUDGET)])
def test_budget_clamped(value, expected):
    assert DebateConfig(task="x", token_budget=value).token_budget == expected


def test_budget_hit_skips_to_synthesis():
    cs = clients()
    debate = Debate(DebateConfig(task="x", rounds=5, token_budget=MIN_TOKEN_BUDGET), cs)
    # Make each call look expensive so the budget is hit after round 1.
    for c in cs.values():
        original = c.stream

        def big(system, prompt, max_tokens, _orig=original, _c=c):
            yield from _orig(system, prompt, max_tokens)
            _c.last_usage = Usage(2000, 1000)

        c.stream = big
    list(debate.run())
    roles = [t.role for t in debate.turns]
    assert roles == ["proposer", "critic", "synthesizer"]
    assert debate.budget_hit and debate.status == "done" and debate.final_text


def test_budget_not_hit_runs_all_rounds():
    debate = Debate(DebateConfig(task="x", rounds=3), clients())
    list(debate.run())
    assert not debate.budget_hit and len(debate.turns) == 7


# ---- partial-turn token estimate --------------------------------------------
def test_stop_estimates_partial_usage():
    mock = {"Claude": MockClient("Claude", delay=0), "Gemini": MockClient("Gemini", delay=0)}
    debate = Debate(DebateConfig(task="x", rounds=2), mock)
    n = {"i": 0}

    def stop():
        n["i"] += 1
        return n["i"] > 5

    list(debate.run(should_stop=stop))
    turn = debate.turns[0]
    assert turn.usage_estimated and turn.usage.output_tokens > 0 and turn.usage.input_tokens > 0


def test_generator_close_marks_stopped_and_estimates():
    mock = {"Claude": MockClient("Claude", delay=0), "Gemini": MockClient("Gemini", delay=0)}
    debate = Debate(DebateConfig(task="x", rounds=2), mock)
    gen = debate.run()
    for _ in range(6):
        next(gen)
    gen.close()  # what happens when Streamlit interrupts the script
    assert debate.status == "stopped"
    assert debate.turns[0].usage_estimated and debate.total_usage.total > 0


# ---- history ---------------------------------------------------------------
def test_list_logs_newest_first(tmp_path):
    for task in ("Task một", "Task hai"):
        d = Debate(DebateConfig(task=task, rounds=1), clients())
        list(d.run())
        save_log(d, tmp_path)
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    sessions = list_logs(tmp_path)
    assert len(sessions) == 2
    assert all(s["status"] == "done" and s["tokens"] == 45 and s["cost"] for s in sessions)
    assert sessions[0]["json"].name > sessions[1]["json"].name
    assert sessions[0]["md"].exists()


def test_list_logs_missing_dir(tmp_path):
    assert list_logs(tmp_path / "nope") == []


def test_log_contains_cost_and_budget(tmp_path):
    d = Debate(DebateConfig(task="x", rounds=1), clients())
    list(d.run())
    json_path, md_path = save_log(d, tmp_path)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["cost_usd"]["Claude"] > 0 and data["budget_hit"] is False
    assert data["config"]["token_budget"] == d.config.token_budget
    assert "Chi phí ước tính" in md_path.read_text(encoding="utf-8")


def test_log_names_are_ascii(tmp_path):
    d = Debate(DebateConfig(task="Đặt tên tiệm bánh Ưu Đãi!", rounds=1), clients())
    list(d.run())
    json_path, md_path = save_log(d, tmp_path)
    assert json_path.name.isascii() and json_path.name.endswith("_dat-ten-tiem-banh-uu-dai.json")
    again, _ = save_log(d, tmp_path)
    assert again == json_path  # same session re-saved in place


def test_two_sessions_same_second_do_not_collide(tmp_path):
    a = Debate(DebateConfig(task="x", rounds=1), clients())
    b = Debate(DebateConfig(task="x", rounds=1), clients())
    b.started_at = a.started_at
    for d in (a, b):
        list(d.run())
    assert save_log(a, tmp_path)[0] != save_log(b, tmp_path)[0]


def test_exception_inside_stream_marks_stopped_and_estimates():
    """Streamlit raises StopException inside the running stream when "Dừng" is clicked."""

    class Interrupt(BaseException):
        pass

    class Interrupting(MockClient):
        def stream(self, system, prompt, max_tokens):
            yield "một phần câu trả lời "
            raise Interrupt

    mock = {"Claude": Interrupting("Claude", delay=0), "Gemini": MockClient("Gemini", delay=0)}
    debate = Debate(DebateConfig(task="x", rounds=2), mock)
    with pytest.raises(Interrupt):
        list(debate.run())
    assert debate.status == "stopped"
    assert debate.turns[0].usage_estimated and debate.turns[0].usage.output_tokens > 0


def test_close_right_after_turn_start_still_estimates():
    mock = {"Claude": MockClient("Claude", delay=0), "Gemini": MockClient("Gemini", delay=0)}
    debate = Debate(DebateConfig(task="x", rounds=2), mock)
    gen = debate.run()
    while next(gen)[0] != "turn_end":
        pass
    assert next(gen)[0] == "turn_start"
    gen.close()
    assert debate.status == "stopped"
    assert debate.turns[1].usage_estimated and debate.turns[1].usage.input_tokens > 0


def test_external_stop_settles_status_and_estimates():
    mock = {"Claude": MockClient("Claude", delay=0), "Gemini": MockClient("Gemini", delay=0)}
    debate = Debate(DebateConfig(task="x", rounds=2), mock)
    gen = debate.run()
    for _ in range(4):
        next(gen)
    debate.stop()  # UI callback, while the engine is still suspended mid-turn
    assert debate.status == "stopped"
    first = debate.turns[0]
    assert first.usage_estimated and first.usage.output_tokens > 0
    gen.close()
    assert debate.status == "stopped" and first.usage_estimated  # closing later changes nothing


def test_stop_after_done_keeps_done():
    mock = {"Claude": MockClient("Claude", delay=0), "Gemini": MockClient("Gemini", delay=0)}
    debate = Debate(DebateConfig(task="x", rounds=1), mock)
    list(debate.run())
    debate.stop()
    assert debate.status == "done" and not any(t.usage_estimated for t in debate.turns)

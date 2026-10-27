import json

import pytest

from core.base import LLMError, Usage
from core.debate import (
    CRITIC_SYSTEM,
    MAX_ROUNDS,
    MAX_TOKENS_CAP,
    Debate,
    DebateConfig,
    count_weaknesses,
    save_log,
)
from core.mock_client import MockClient


class ScriptedClient:
    """Returns queued replies and records every call."""

    def __init__(self, provider, replies, model="scripted"):
        self.provider = provider
        self.model = model
        self.replies = list(replies)
        self.calls = []
        self.last_usage = Usage()
        self.last_truncated = False

    def stream(self, system, prompt, max_tokens):
        self.calls.append({"system": system, "prompt": prompt, "max_tokens": max_tokens})
        text = self.replies.pop(0) if self.replies else "## Đề xuất\nok"
        yield from text.splitlines(keepends=True)
        self.last_usage = Usage(10, 5)


class FailingClient(ScriptedClient):
    def stream(self, system, prompt, max_tokens):
        raise LLMError("Gemini: API key không hợp lệ")
        yield  # pragma: no cover


GOOD_CRITIQUE = "## Điểm yếu\n1. a\n2. b\n## Gợi ý sửa\n- c"


def mock_clients():
    return {"Claude": MockClient("Claude", delay=0), "Gemini": MockClient("Gemini", delay=0)}


def run_all(debate, **kw):
    return list(debate.run(**kw))


def test_full_run_schedule_and_final():
    debate = Debate(DebateConfig(task="Lập kế hoạch học Python", rounds=3), mock_clients())
    run_all(debate)
    assert debate.status == "done"
    roles = [(t.round, t.role, t.speaker) for t in debate.turns]
    assert roles == [
        (1, "proposer", "Claude"),
        (1, "critic", "Gemini"),
        (2, "proposer", "Claude"),
        (2, "critic", "Gemini"),
        (3, "proposer", "Claude"),
        (3, "critic", "Gemini"),
        (3, "synthesizer", "Claude"),
    ]
    assert debate.final_text and "Kết quả cuối" in debate.final_text
    assert all(t.done for t in debate.turns)


def test_roles_swap_and_synthesizer_choice():
    cfg = DebateConfig(task="x", rounds=1, proposer="Gemini", synthesizer="Gemini")
    debate = Debate(cfg, mock_clients())
    run_all(debate)
    assert [(t.role, t.speaker) for t in debate.turns] == [
        ("proposer", "Gemini"),
        ("critic", "Claude"),
        ("synthesizer", "Gemini"),
    ]


@pytest.mark.parametrize("rounds,expected", [(0, 1), (1, 1), (5, 5), (99, MAX_ROUNDS)])
def test_rounds_hard_limit(rounds, expected):
    assert DebateConfig(task="x", rounds=rounds).rounds == expected


def test_max_tokens_hard_cap_reaches_clients():
    claude = ScriptedClient("Claude", [])
    gemini = ScriptedClient("Gemini", [GOOD_CRITIQUE])
    debate = Debate(
        DebateConfig(task="x", rounds=1, max_tokens=10**6), {"Claude": claude, "Gemini": gemini}
    )
    run_all(debate)
    assert {c["max_tokens"] for c in claude.calls + gemini.calls} == {MAX_TOKENS_CAP}


@pytest.mark.parametrize("task", ["", "   ", "x" * 9000])
def test_invalid_task_rejected(task):
    with pytest.raises(ValueError):
        DebateConfig(task=task)


def test_critic_gets_anti_agreement_prompt():
    claude = ScriptedClient("Claude", [])
    gemini = ScriptedClient("Gemini", [GOOD_CRITIQUE])
    run_all(Debate(DebateConfig(task="x", rounds=1), {"Claude": claude, "Gemini": gemini}))
    assert gemini.calls[0]["system"] == CRITIC_SYSTEM
    assert "ÍT NHẤT 2" in CRITIC_SYSTEM


def test_critic_reasked_when_too_few_weaknesses():
    claude = ScriptedClient("Claude", [])
    gemini = ScriptedClient("Gemini", ["Đề xuất rất tốt, đồng ý.", GOOD_CRITIQUE])
    debate = Debate(DebateConfig(task="x", rounds=1), {"Claude": claude, "Gemini": gemini})
    events = run_all(debate)
    critic = debate.turns[1]
    assert len(gemini.calls) == 2
    assert "LƯU Ý" in gemini.calls[1]["prompt"]
    assert critic.retried and critic.weakness_count == 2
    assert critic.text.startswith("## Điểm yếu")
    assert any(e[0] == "turn_reset" for e in events)
    assert critic.usage.total == 30  # both attempts are counted


def test_critic_retry_is_bounded():
    claude = ScriptedClient("Claude", [])
    gemini = ScriptedClient("Gemini", ["ok", "vẫn ok"])
    debate = Debate(DebateConfig(task="x", rounds=1), {"Claude": claude, "Gemini": gemini})
    run_all(debate)
    assert len(gemini.calls) == 2
    assert debate.turns[1].weakness_count == 0
    assert debate.status == "done"


def test_transcript_passed_to_next_turn():
    claude = ScriptedClient("Claude", ["## Đề xuất\nPLAN-A"])
    gemini = ScriptedClient("Gemini", [GOOD_CRITIQUE])
    run_all(Debate(DebateConfig(task="TASK-XYZ", rounds=1), {"Claude": claude, "Gemini": gemini}))
    assert "TASK-XYZ" in gemini.calls[0]["prompt"]
    assert "PLAN-A" in gemini.calls[0]["prompt"]
    assert "PLAN-A" in claude.calls[1]["prompt"] and "Điểm yếu" in claude.calls[1]["prompt"]


def test_stop_midway():
    debate = Debate(DebateConfig(task="x", rounds=3), mock_clients())
    seen = {"chunks": 0}

    def should_stop():
        seen["chunks"] += 1
        return seen["chunks"] > 5

    run_all(debate, should_stop=should_stop)
    assert debate.status == "stopped"
    assert debate.final_text is None
    assert len(debate.turns) == 1 and not debate.turns[0].done


def test_api_error_sets_error_status():
    clients = {"Claude": ScriptedClient("Claude", []), "Gemini": FailingClient("Gemini", [])}
    debate = Debate(DebateConfig(task="x", rounds=2), clients)
    run_all(debate)
    assert debate.status == "error"
    assert "API key" in debate.error
    assert debate.turns[0].done and not debate.turns[1].done


def test_usage_totals():
    clients = {
        "Claude": ScriptedClient("Claude", []),
        "Gemini": ScriptedClient("Gemini", [GOOD_CRITIQUE]),
    }
    debate = Debate(DebateConfig(task="x", rounds=1), clients)
    run_all(debate)
    assert debate.usage_by_provider["Claude"].total == 30  # proposer + synthesizer
    assert debate.usage_by_provider["Gemini"].total == 15
    assert debate.total_usage.total == 45


def test_missing_client_rejected():
    with pytest.raises(ValueError):
        Debate(DebateConfig(task="x"), {"Claude": MockClient("Claude")})


@pytest.mark.parametrize(
    "text,expected",
    [
        (GOOD_CRITIQUE, 2),
        ("## Điểm yếu\n1. a\n2. b\n3. c\n## Gợi ý sửa\n1. x\n2. y", 3),
        ("## Điểm yếu\n- a\n- b\n", 2),
        ("1. a\n2) b\n3. c", 3),
        ("Mọi thứ đều tốt.", 0),
        ("## Điểm yếu\nKhông có.", 0),
    ],
)
def test_count_weaknesses(text, expected):
    assert count_weaknesses(text) == expected


def test_save_log_writes_json_and_md(tmp_path):
    debate = Debate(DebateConfig(task="Viết email xin nghỉ phép", rounds=1), mock_clients())
    run_all(debate)
    json_path, md_path = save_log(debate, tmp_path)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["status"] == "done" and data["final"]
    assert len(data["turns"]) == 3
    assert "viết-email" in json_path.name
    md = md_path.read_text(encoding="utf-8")
    assert "Viết email xin nghỉ phép" in md and "Kết quả cuối" in md
    assert "Kết quả cuối" in debate.final_markdown()

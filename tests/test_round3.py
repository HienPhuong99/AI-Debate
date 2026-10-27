import json

import pytest

from core.debate import (
    CRITIC_SYSTEM,
    MAX_PERSONA_CHARS,
    PROPOSER_SYSTEM,
    Debate,
    DebateConfig,
    parse_score,
    save_log,
)
from core.mock_client import MockClient
from tests.test_debate import ScriptedClient


def critique(score):
    return f"## Điểm yếu\n1. a\n2. b\n## Gợi ý sửa\n- c\nĐiểm: {score}/10"


def scripted(scores):
    return {
        "Claude": ScriptedClient("Claude", [], model="claude-opus-5-5"),
        "Gemini": ScriptedClient("Gemini", [critique(s) for s in scores], model="gemini-3.8-flash"),
    }


def mock():
    return {"Claude": MockClient("Claude", delay=0), "Gemini": MockClient("Gemini", delay=0)}


# ---- scoring ---------------------------------------------------------------
@pytest.mark.parametrize(
    "text,expected",
    [
        ("Điểm: 7/10", 7.0),
        ("**Điểm:** 6.5 / 10", 6.5),
        ("điểm 8,5/10", 8.5),
        ("Điểm: 4/10\n...\nĐiểm: 9/10", 9.0),
        ("Điểm: 15/10", 10.0),
        ("không chấm", None),
    ],
)
def test_parse_score(text, expected):
    assert parse_score(text) == expected


def test_critic_prompt_requires_score():
    assert "Điểm: X/10" in CRITIC_SYSTEM


def test_scores_recorded_per_round():
    debate = Debate(DebateConfig(task="x", rounds=3), scripted([4, 6, 8]))
    list(debate.run())
    assert debate.scores == [(1, 4.0), (2, 6.0), (3, 8.0)]
    assert "· 6/10" in debate.turns[3].title
    assert debate.to_dict()["scores"][2] == {"round": 3, "score": 8.0}


# ---- early stop ------------------------------------------------------------
def test_early_stop_skips_to_synthesis():
    debate = Debate(DebateConfig(task="x", rounds=5, stop_score=8), scripted([6, 8, 9]))
    list(debate.run())
    assert [(t.round, t.role) for t in debate.turns] == [
        (1, "proposer"),
        (1, "critic"),
        (2, "proposer"),
        (2, "critic"),
        (5, "synthesizer"),
    ]
    assert debate.early_stopped and debate.status == "done" and debate.final_text
    assert "dừng sớm" in debate.to_markdown()


def test_early_stop_off_by_default():
    debate = Debate(DebateConfig(task="x", rounds=2), scripted([10, 10]))
    list(debate.run())
    assert not debate.early_stopped and len(debate.turns) == 5


def test_early_stop_on_last_round_is_not_flagged():
    debate = Debate(DebateConfig(task="x", rounds=1, stop_score=5), scripted([9]))
    list(debate.run())
    assert not debate.early_stopped


def test_mock_scores_rise_so_demo_can_stop_early():
    debate = Debate(DebateConfig(task="x", rounds=5, stop_score=8), mock())
    list(debate.run())
    assert debate.scores == [(1, 5.0), (2, 7.0), (3, 9.0)]
    assert debate.early_stopped


# ---- language & persona ----------------------------------------------------
def test_language_rule_in_system_prompt():
    cs = scripted([7])
    list(Debate(DebateConfig(task="x", rounds=1, language="en"), cs).run())
    assert all("Always answer in English" in c["system"] for c in cs["Claude"].calls)
    assert "Always answer in English" in cs["Gemini"].calls[0]["system"]


def test_invalid_language_rejected():
    with pytest.raises(ValueError):
        DebateConfig(task="x", language="fr")


def test_persona_only_for_its_role_and_keeps_rules():
    cs = scripted([7])
    cfg = DebateConfig(
        task="x", rounds=1, proposer_persona="kế toán trưởng", critic_persona="kiểm toán viên"
    )
    list(Debate(cfg, cs).run())
    proposer_sys, synth_sys = cs["Claude"].calls[0]["system"], cs["Claude"].calls[1]["system"]
    critic_sys = cs["Gemini"].calls[0]["system"]
    assert proposer_sys.startswith(PROPOSER_SYSTEM) and "kế toán trưởng" in proposer_sys
    assert critic_sys.startswith(CRITIC_SYSTEM) and "kiểm toán viên" in critic_sys
    assert "kế toán" not in synth_sys and "kiểm toán" not in synth_sys


def test_persona_too_long_rejected():
    with pytest.raises(ValueError):
        DebateConfig(task="x", critic_persona="a" * (MAX_PERSONA_CHARS + 1))


# ---- resume ----------------------------------------------------------------
def stopped_after(n_chunks, rounds=2):
    debate = Debate(DebateConfig(task="Kế hoạch học", rounds=rounds), mock())
    seen = {"n": 0}

    def stop():
        seen["n"] += 1
        return seen["n"] > n_chunks

    list(debate.run(should_stop=stop))
    assert debate.status == "stopped"
    return debate


def test_resume_in_memory_continues_without_rerunning_done_turns():
    debate = stopped_after(60)  # proposer round 1 done (~33 chunks), critic cut off
    done_before = [t for t in debate.turns if t.done]
    assert len(done_before) == 1 and not debate.turns[-1].done
    debate.prepare_resume()
    list(debate.run())
    assert debate.status == "done" and debate.final_text and debate.resumed == 1
    live = [(t.round, t.role) for t in debate.turns if not t.abandoned]
    assert live == [
        (1, "proposer"),
        (1, "critic"),
        (2, "proposer"),
        (2, "critic"),
        (2, "synthesizer"),
    ]
    assert sum(t.abandoned for t in debate.turns) == 1
    assert debate.turns[0] is done_before[0]  # kept, not regenerated


def test_resume_from_log_file(tmp_path):
    debate = stopped_after(60)
    json_path, _ = save_log(debate, tmp_path)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    restored = Debate.from_dict(data, mock(), log_stem=json_path.stem)
    assert [t.text for t in restored.turns] == [t.text for t in debate.turns]
    assert restored.total_usage.total == debate.total_usage.total
    restored.prepare_resume()
    list(restored.run())
    assert restored.status == "done" and restored.final_text
    again, _ = save_log(restored, tmp_path)
    assert again == json_path  # resumed session updates its own log
    assert json.loads(again.read_text(encoding="utf-8"))["resumed"] == 1


def test_resume_after_api_error():
    cs = {"Claude": MockClient("Claude", delay=0), "Gemini": MockClient("Gemini", delay=0)}

    class Broken(MockClient):
        def stream(self, system, prompt, max_tokens):
            from core.base import LLMError

            raise LLMError("Gemini: lỗi máy chủ 503")
            yield  # pragma: no cover

    cs["Gemini"] = Broken("Gemini", delay=0)
    debate = Debate(DebateConfig(task="x", rounds=1), cs)
    list(debate.run())
    assert debate.status == "error" and debate.can_resume
    debate.clients["Gemini"] = MockClient("Gemini", delay=0)  # e.g. key fixed in .env
    debate.prepare_resume()
    list(debate.run())
    assert debate.status == "done" and debate.error is None


def test_cannot_resume_finished_session():
    debate = Debate(DebateConfig(task="x", rounds=1), mock())
    list(debate.run())
    assert not debate.can_resume
    with pytest.raises(ValueError):
        debate.prepare_resume()


def test_old_logs_without_new_fields_still_load(tmp_path):
    debate = Debate(DebateConfig(task="x", rounds=1), mock())
    list(debate.run())
    data = debate.to_dict()
    for key in ("language", "proposer_persona", "critic_persona", "stop_score"):
        data["config"].pop(key)
    for turn in data["turns"]:
        turn.pop("score")
        turn.pop("abandoned")
    restored = Debate.from_dict(data, mock())
    assert restored.config.language == "auto" and restored.final_text == debate.final_text

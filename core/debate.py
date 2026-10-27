"""Debate engine: a proposer and a critic take turns, then one side writes the final result."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path

from core.base import LLMClient, LLMError, Usage
from core.pricing import cost_usd

# Hard limits so a run can never cost more than expected.
MIN_ROUNDS = 1
MAX_ROUNDS = 5
DEFAULT_ROUNDS = 3
MIN_MAX_TOKENS = 256
MAX_TOKENS_CAP = 4096
DEFAULT_MAX_TOKENS = 2048
MAX_TASK_CHARS = 8000
MIN_WEAKNESSES = 2
# Session-wide token budget (input + output across both models).
MIN_TOKEN_BUDGET = 5_000
MAX_TOKEN_BUDGET = 200_000
DEFAULT_TOKEN_BUDGET = 60_000

MAX_PERSONA_CHARS = 200
PROVIDERS = ("Claude", "Gemini")
LANGUAGES = {"auto": "Theo ngôn ngữ của task", "vi": "Tiếng Việt", "en": "English"}
LANGUAGE_RULES = {
    "auto": "Trả lời bằng ngôn ngữ của task, súc tích.",
    "vi": "Luôn trả lời bằng tiếng Việt, súc tích.",
    "en": "Always answer in English, concisely.",
}

PROPOSER_SYSTEM = """Bạn là bên ĐỀ XUẤT trong một cuộc thảo luận giữa hai AI để giải quyết task của người dùng.
- Vòng đầu: đưa ra giải pháp cụ thể, có thể làm theo được ngay.
- Các vòng sau: xét TỪNG điểm yếu mà bên kia vừa nêu. Điểm nào đúng thì sửa giải pháp; điểm nào sai thì bác bỏ kèm lý do cụ thể. Không được đồng ý chung chung cho xong, không xin lỗi rườm rà.
- Định dạng Markdown: "## Đề xuất" (bản đầy đủ hiện tại), và từ vòng 2 thêm "## Phản hồi phản biện" (mỗi điểm: chấp nhận/bác bỏ + lý do)."""

CRITIC_SYSTEM = f"""Bạn là bên PHẢN BIỆN trong một cuộc thảo luận giữa hai AI. Bạn CHỈ phản biện, không viết lại giải pháp thay bên đề xuất.
Quy tắc bắt buộc:
- Mỗi lượt phải chỉ ra ÍT NHẤT {MIN_WEAKNESSES} điểm yếu CỤ THỂ trong đề xuất mới nhất: chỉ rõ phần nào, vì sao sai/thiếu, hậu quả nếu giữ nguyên.
- Cấm khen chung chung, cấm kết luận kiểu "đề xuất đã ổn/không còn gì để góp ý". Nếu đề xuất đã tốt, vẫn phải tìm {MIN_WEAKNESSES} điểm yếu thật nhất (rủi ro, trường hợp biên, giả định chưa kiểm chứng, chi phí, khả năng thực thi).
- Không lặp lại điểm yếu đã được sửa thoả đáng; nếu bên đề xuất bác bỏ sai, nói rõ vì sao.
Định dạng Markdown bắt buộc:
## Điểm yếu
1. ...
2. ...
## Gợi ý sửa
- ...
Điểm: X/10
Dòng cuối "Điểm: X/10" là bắt buộc: chấm chất lượng đề xuất hiện tại (10 = dùng được ngay, không còn điểm yếu đáng kể). Chấm thẳng tay; điểm cao KHÔNG miễn yêu cầu nêu điểm yếu."""

SYNTH_SYSTEM = """Bạn là bên TỔNG HỢP. Dựa trên toàn bộ cuộc thảo luận, viết KẾT QUẢ CUỐI CÙNG hoàn chỉnh cho task của người dùng.
- Dùng đề xuất mới nhất làm nền, áp dụng các phản biện hợp lý, bỏ các phản biện đã bị bác bỏ có lý.
- Kết quả phải dùng được ngay, không kể lại quá trình tranh luận.
- Cuối cùng thêm mục ngắn "## Điểm còn tranh cãi / rủi ro" (nếu có).
- Định dạng Markdown."""

ROLE_LABELS = {"proposer": "Đề xuất", "critic": "Phản biện", "synthesizer": "Tổng hợp"}


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def parse_score(text: str) -> float | None:
    """The critic's 'Điểm: X/10' line (last one wins), clamped to 0..10."""
    matches = re.findall(r"Điểm\s*:?\s*\**\s*(\d+(?:[.,]\d+)?)\s*/\s*10", text, re.IGNORECASE)
    if not matches:
        return None
    return max(0.0, min(10.0, float(matches[-1].replace(",", "."))))


def count_weaknesses(text: str) -> int:
    """Count list items under the '## Điểm yếu' heading (or numbered items if there is none)."""
    match = re.search(r"^#+\s*Điểm yếu.*$", text, flags=re.IGNORECASE | re.MULTILINE)
    if match:
        section = text[match.end() :]
        next_heading = re.search(r"^#+\s", section, flags=re.MULTILINE)
        if next_heading:
            section = section[: next_heading.start()]
        pattern = r"^\s*(?:\d+[.)]|[-*•])\s+\S"
    else:
        section = text
        pattern = r"^\s*\d+[.)]\s+\S"
    return len(re.findall(pattern, section, flags=re.MULTILINE))


@dataclass
class DebateConfig:
    task: str
    rounds: int = DEFAULT_ROUNDS
    max_tokens: int = DEFAULT_MAX_TOKENS
    proposer: str = "Claude"
    synthesizer: str = "Claude"
    token_budget: int = DEFAULT_TOKEN_BUDGET
    language: str = "auto"
    proposer_persona: str = ""
    critic_persona: str = ""
    stop_score: int = 0  # 0 = off; else skip to synthesis once the critic scores >= this

    def __post_init__(self) -> None:
        self.task = (self.task or "").strip()
        if not self.task:
            raise ValueError("Task không được để trống.")
        if len(self.task) > MAX_TASK_CHARS:
            raise ValueError(f"Task quá dài (tối đa {MAX_TASK_CHARS} ký tự).")
        if self.proposer not in PROVIDERS or self.synthesizer not in PROVIDERS:
            raise ValueError("Bên đề xuất/tổng hợp phải là Claude hoặc Gemini.")
        self.rounds = clamp(self.rounds, MIN_ROUNDS, MAX_ROUNDS)
        self.max_tokens = clamp(self.max_tokens, MIN_MAX_TOKENS, MAX_TOKENS_CAP)
        self.token_budget = clamp(self.token_budget, MIN_TOKEN_BUDGET, MAX_TOKEN_BUDGET)
        if self.language not in LANGUAGES:
            raise ValueError(f"Ngôn ngữ không hỗ trợ: {self.language}")
        self.proposer_persona = (self.proposer_persona or "").strip()
        self.critic_persona = (self.critic_persona or "").strip()
        if max(len(self.proposer_persona), len(self.critic_persona)) > MAX_PERSONA_CHARS:
            raise ValueError(f"Vai chuyên môn tối đa {MAX_PERSONA_CHARS} ký tự.")
        self.stop_score = clamp(self.stop_score, 0, 10)

    @property
    def critic(self) -> str:
        return "Gemini" if self.proposer == "Claude" else "Claude"


@dataclass
class Turn:
    round: int
    role: str  # proposer | critic | synthesizer
    speaker: str  # Claude | Gemini
    model: str
    text: str = ""
    usage: Usage = field(default_factory=Usage)
    truncated: bool = False
    weakness_count: int | None = None
    retried: bool = False
    usage_estimated: bool = False  # usage guessed from text length (turn was cut off)
    score: float | None = None  # critic's "Điểm: X/10"
    abandoned: bool = False  # unfinished turn left behind when the session was resumed
    done: bool = False

    @property
    def title(self) -> str:
        if self.role == "synthesizer":
            return f"Kết quả cuối — {self.speaker} ({self.model})"
        title = f"Vòng {self.round} · {ROLE_LABELS[self.role]} — {self.speaker} ({self.model})"
        if self.score is not None:
            title += f" · {self.score:g}/10"
        return title


class Debate:
    """Runs the debate as a stream of events so the UI can render it live.

    Events are tuples: ("turn_start", turn), ("chunk", turn, text),
    ("turn_reset", turn) when a critic reply is re-asked, and ("turn_end", turn).
    """

    def __init__(self, config: DebateConfig, clients: dict[str, LLMClient]):
        missing = [p for p in PROVIDERS if p not in clients]
        if missing:
            raise ValueError(f"Thiếu client cho: {', '.join(missing)}")
        self.config = config
        self.clients = clients
        self.turns: list[Turn] = []
        self.status = "pending"  # pending | running | done | stopped | error
        self.error: str | None = None
        self.started_at = datetime.now()
        self.finished_at: datetime | None = None
        self.budget_hit = False
        self.early_stopped = False
        self.resumed = 0
        self._current_prompt = ""
        self._log_stem: str | None = None

    @classmethod
    def from_dict(
        cls, data: dict, clients: dict[str, LLMClient], log_stem: str | None = None
    ) -> Debate:
        """Rebuild a session from its saved JSON log (see `to_dict`)."""
        known = {f.name for f in fields(DebateConfig)}
        config = DebateConfig(**{k: v for k, v in data["config"].items() if k in known})
        debate = cls(config, clients)
        debate.started_at = datetime.fromisoformat(data["started_at"])
        if data.get("finished_at"):
            debate.finished_at = datetime.fromisoformat(data["finished_at"])
        debate.status = data.get("status", "stopped")
        debate.error = data.get("error")
        debate.budget_hit = bool(data.get("budget_hit"))
        debate.early_stopped = bool(data.get("early_stopped"))
        debate.resumed = int(data.get("resumed", 0))
        turn_fields = {f.name for f in fields(Turn)} - {"usage"}
        for raw in data.get("turns", []):
            turn = Turn(**{k: v for k, v in raw.items() if k in turn_fields})
            turn.usage = Usage(**raw.get("usage", {}))
            debate.turns.append(turn)
        debate._log_stem = log_stem
        return debate

    @property
    def can_resume(self) -> bool:
        return self.status in ("stopped", "error") and self.final_text is None

    def prepare_resume(self) -> None:
        """Keep finished turns, set aside the cut-off one, and get ready to `run()` again."""
        if not self.can_resume:
            raise ValueError("Chỉ tiếp tục được phiên đã dừng hoặc bị lỗi, chưa có kết quả cuối.")
        for turn in self.turns:
            if not turn.done:
                turn.abandoned = True
        self.status = "pending"
        self.error = None
        self.finished_at = None
        self.resumed += 1

    # ---- results -------------------------------------------------------
    @property
    def usage_by_provider(self) -> dict[str, Usage]:
        totals = {p: Usage() for p in PROVIDERS}
        for turn in self.turns:
            totals[turn.speaker].add(turn.usage)
        return totals

    @property
    def total_usage(self) -> Usage:
        total = Usage()
        for usage in self.usage_by_provider.values():
            total.add(usage)
        return total

    @property
    def cost_by_provider(self) -> dict[str, float | None]:
        """Estimated USD per provider; None if any turn used a model without a known price."""
        costs: dict[str, float | None] = {p: 0.0 for p in PROVIDERS}
        for turn in self.turns:
            cost = cost_usd(turn.model, turn.usage, self.started_at.date())
            current = costs[turn.speaker]
            costs[turn.speaker] = None if cost is None or current is None else current + cost
        return costs

    @property
    def total_cost(self) -> float | None:
        values = list(self.cost_by_provider.values())
        return None if None in values else sum(values)

    @property
    def scores(self) -> list[tuple[int, float]]:
        return [(t.round, t.score) for t in self.turns if t.done and t.score is not None]

    @property
    def final_text(self) -> str | None:
        last = self.turns[-1] if self.turns else None
        if last and last.role == "synthesizer" and last.done:
            return last.text
        return None

    # ---- prompts -------------------------------------------------------
    def _transcript(self) -> str:
        parts = []
        for turn in self.turns:
            if turn.done and turn.role != "synthesizer":
                label = ROLE_LABELS[turn.role]
                parts.append(
                    f"### Vòng {turn.round} — {label} ({turn.speaker})\n{turn.text.strip()}"
                )
        return "\n\n".join(parts) if parts else "(chưa có)"

    def _prompt(self, role: str, round_no: int) -> str:
        rounds = self.config.rounds
        if role == "proposer" and round_no == 1:
            instruction = "Đưa ra đề xuất ban đầu cho task."
        elif role == "proposer":
            instruction = (
                f"Đây là vòng {round_no}/{rounds}. Phản hồi từng điểm yếu ở lượt phản biện "
                "gần nhất và đưa ra bản đề xuất đã cải tiến."
            )
        elif role == "critic":
            instruction = (
                f"Đây là vòng {round_no}/{rounds}. Phản biện đề xuất mới nhất: nêu ít nhất "
                f"{MIN_WEAKNESSES} điểm yếu cụ thể theo đúng định dạng."
            )
        else:
            instruction = "Cuộc thảo luận đã kết thúc. Viết kết quả cuối cùng cho task."
        return (
            f"# Task của người dùng\n{self.config.task}\n\n"
            f"# Diễn biến thảo luận\n{self._transcript()}\n\n"
            f"# Việc của bạn lúc này\n{instruction}"
        )

    def _system(self, role: str) -> str:
        cfg = self.config
        base = {"proposer": PROPOSER_SYSTEM, "critic": CRITIC_SYSTEM, "synthesizer": SYNTH_SYSTEM}
        parts = [base[role], LANGUAGE_RULES[cfg.language]]
        persona = {"proposer": cfg.proposer_persona, "critic": cfg.critic_persona}.get(role)
        if persona:
            parts.append(f"Vai chuyên môn của bạn: {persona}. Vẫn giữ nguyên mọi quy tắc ở trên.")
        return "\n".join(parts)

    # ---- engine --------------------------------------------------------
    def _schedule(self) -> list[tuple[int, str, str]]:
        cfg = self.config
        steps = []
        for r in range(1, cfg.rounds + 1):
            steps.append((r, "proposer", cfg.proposer))
            steps.append((r, "critic", cfg.critic))
        steps.append((cfg.rounds, "synthesizer", cfg.synthesizer))
        return steps

    def run(self, should_stop: Callable[[], bool] = lambda: False) -> Iterator[tuple]:
        self.status = "running"
        # On a resumed session, finished turns are replayed from the log, not re-run.
        finished = [(t.round, t.role) for t in self.turns if t.done]
        try:
            for round_no, role, speaker in self._schedule():
                if (self.budget_hit or self.early_stopped) and role != "synthesizer":
                    continue  # over budget or good enough: skip remaining rounds, synthesize
                if finished and finished[0] == (round_no, role):
                    finished.pop(0)
                    continue
                client = self.clients[speaker]
                turn = Turn(round=round_no, role=role, speaker=speaker, model=client.model)
                prompt = self._prompt(role, round_no)
                self._current_prompt = prompt
                self.turns.append(turn)
                yield ("turn_start", turn)
                attempts = 2 if role == "critic" else 1
                for attempt in range(attempts):
                    if attempt:
                        # The critic agreed too easily: ask once more, stating the rule.
                        turn.text = ""
                        turn.retried = True
                        yield ("turn_reset", turn)
                        prompt += (
                            f"\n\nLƯU Ý: lượt trước của bạn chưa nêu đủ {MIN_WEAKNESSES} điểm yếu "
                            "cụ thể dưới mục '## Điểm yếu'. Làm lại đúng quy tắc."
                        )
                    for chunk in client.stream(self._system(role), prompt, self.config.max_tokens):
                        if should_stop():
                            self._estimate_partial(turn, prompt)
                            self._finish("stopped")
                            return
                        turn.text += chunk
                        yield ("chunk", turn, chunk)
                    turn.usage.add(client.last_usage)
                    turn.truncated = client.last_truncated
                    if role != "critic":
                        break
                    turn.weakness_count = count_weaknesses(turn.text)
                    if turn.weakness_count >= MIN_WEAKNESSES:
                        break
                turn.done = True
                if role == "critic":
                    turn.score = parse_score(turn.text)
                    stop_at = self.config.stop_score
                    if stop_at and turn.score is not None and turn.score >= stop_at:
                        self.early_stopped = round_no < self.config.rounds
                if role != "synthesizer" and self.total_usage.total >= self.config.token_budget:
                    self.budget_hit = True
                yield ("turn_end", turn)
                if should_stop():
                    self._finish("stopped")
                    return
        except LLMError as e:
            self.error = str(e)
            self._finish("error")
            return
        except BaseException:
            # Cut off from outside: the UI closed us (GeneratorExit) or Streamlit raised its
            # StopException inside the running stream when "Dừng" was clicked.
            last = self.turns[-1] if self.turns else None
            if last is not None and not last.done:
                self._estimate_partial(last, self._current_prompt)
            if self.status == "running":
                self._finish("stopped")
            raise
        self._finish("done")

    def stop(self) -> None:
        """Stop from outside the engine (UI "Dừng"): settle status and the cut-off turn now.

        Streamlit starts the next script run before the interrupted one has unwound, so the
        UI must not wait for the engine to notice the stop before saving or rendering.
        """
        last = self.turns[-1] if self.turns else None
        if last is not None and not last.done:
            self._estimate_partial(last, self._current_prompt)
        if self.status in ("pending", "running"):
            self._finish("stopped")

    @staticmethod
    def _estimate_partial(turn: Turn, prompt: str) -> None:
        """Providers report usage only at the end of a stream; guess it (~4 chars/token)."""
        if turn.usage.total == 0:
            turn.usage = Usage(len(prompt) // 4, len(turn.text) // 4)
            turn.usage_estimated = True

    def _finish(self, status: str) -> None:
        self.status = status
        self.finished_at = datetime.now()

    # ---- export --------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "error": self.error,
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "finished_at": self.finished_at.isoformat(timespec="seconds")
            if self.finished_at
            else None,
            "config": asdict(self.config),
            "models": {p: c.model for p, c in self.clients.items()},
            "usage": {p: asdict(u) for p, u in self.usage_by_provider.items()},
            "cost_usd": self.cost_by_provider,
            "budget_hit": self.budget_hit,
            "early_stopped": self.early_stopped,
            "resumed": self.resumed,
            "scores": [{"round": r, "score": sc} for r, sc in self.scores],
            "turns": [asdict(t) for t in self.turns],
            "final": self.final_text,
        }

    def final_markdown(self) -> str:
        cfg = self.config
        usage = self.total_usage
        return (
            f"# Kết quả AI Debate\n\n**Task:** {cfg.task}\n\n"
            f"_Tổng hợp bởi {cfg.synthesizer} · {cfg.rounds} vòng · "
            f"{usage.total:,} token · {format_usd(self.total_cost)}_\n\n---\n\n"
            f"{self.final_text or '(chưa có kết quả cuối)'}\n"
        )

    def to_markdown(self) -> str:
        cfg = self.config
        lines = [
            "# Phiên AI Debate",
            "",
            f"- Thời gian: {self.started_at:%Y-%m-%d %H:%M:%S}",
            f"- Trạng thái: {self.status}" + (f" — {self.error}" if self.error else ""),
            f"- Số vòng: {cfg.rounds} · max_tokens/lượt: {cfg.max_tokens}",
            f"- Đề xuất: {cfg.proposer} · Phản biện: {cfg.critic} · Tổng hợp: {cfg.synthesizer}",
            f"- Ngôn ngữ: {LANGUAGES[cfg.language]}",
        ]
        if cfg.proposer_persona or cfg.critic_persona:
            lines.append(
                f"- Vai chuyên môn: đề xuất = {cfg.proposer_persona or '—'} · "
                f"phản biện = {cfg.critic_persona or '—'}"
            )
        if self.scores:
            lines.append("- Điểm phản biện: " + ", ".join(f"V{r}: {s:g}" for r, s in self.scores))
        costs = self.cost_by_provider
        for provider, u in self.usage_by_provider.items():
            lines.append(
                f"- Token {provider}: vào {u.input_tokens:,} / ra {u.output_tokens:,}"
                f" · {format_usd(costs[provider])}"
            )
        lines.append(f"- Chi phí ước tính: {format_usd(self.total_cost)}")
        if self.budget_hit:
            lines.append(f"- Chạm ngân sách {cfg.token_budget:,} token → bỏ các vòng còn lại")
        if self.early_stopped:
            lines.append(f"- Điểm đạt ngưỡng {cfg.stop_score}/10 → dừng sớm, chuyển sang tổng hợp")
        if self.resumed:
            lines.append(f"- Đã tiếp tục phiên {self.resumed} lần")
        lines += ["", "## Task", "", cfg.task, ""]
        for turn in self.turns:
            note = (
                " _(bỏ dở, đã chạy lại khi tiếp tục phiên)_"
                if turn.abandoned
                else ("" if turn.done else " _(chưa xong)_")
            )
            lines += [f"## {turn.title}{note}", "", turn.text.strip(), ""]
        return "\n".join(lines)


def format_usd(value: float | None) -> str:
    if value is None:
        return "chưa rõ giá"
    return f"~${value:.4f}" if value < 1 else f"~${value:,.2f}"


def _slug(text: str, limit: int = 40) -> str:
    """ASCII-only slug: non-ASCII file names break browser downloads and some Windows tools."""
    text = text.lower().replace("đ", "d")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return slug[:limit].strip("-") or "task"


def save_log(debate: Debate, logs_dir: str | Path = "logs") -> tuple[Path, Path]:
    """Write the session to logs/ as JSON and Markdown; returns both paths."""
    folder = Path(logs_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{debate.started_at:%Y%m%d-%H%M%S}_{_slug(debate.config.task)}"
    if getattr(debate, "_log_stem", None):
        stem = debate._log_stem  # re-saving the same session overwrites its own files
    else:
        base, n = stem, 2
        while (folder / f"{stem}.json").exists():
            stem, n = f"{base}-{n}", n + 1
        debate._log_stem = stem
    json_path = folder / f"{stem}.json"
    md_path = folder / f"{stem}.md"
    json_path.write_text(
        json.dumps(debate.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_path.write_text(debate.to_markdown(), encoding="utf-8")
    return json_path, md_path


def list_logs(logs_dir: str | Path = "logs") -> list[dict]:
    """Saved sessions, newest first: {json, md, started_at, task, status, tokens, cost}."""
    folder = Path(logs_dir)
    sessions = []
    for json_path in sorted(folder.glob("*.json"), reverse=True):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            usage = data.get("usage") or {}
            costs = (data.get("cost_usd") or {}).values()
            sessions.append(
                {
                    "json": json_path,
                    "md": json_path.with_suffix(".md"),
                    "started_at": data.get("started_at", ""),
                    "task": (data.get("config") or {}).get("task", ""),
                    "status": data.get("status", "?"),
                    "tokens": sum(
                        u.get("input_tokens", 0) + u.get("output_tokens", 0) for u in usage.values()
                    ),
                    "cost": None if not costs or None in costs else sum(costs),
                    "resumable": data.get("status") in ("stopped", "error")
                    and not data.get("final"),
                }
            )
        except (OSError, ValueError, AttributeError):
            continue  # skip unreadable or foreign files
    return sessions

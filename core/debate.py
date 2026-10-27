"""Debate engine: a proposer and a critic take turns, then one side writes the final result."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from core.base import LLMClient, LLMError, Usage

# Hard limits so a run can never cost more than expected.
MIN_ROUNDS = 1
MAX_ROUNDS = 5
DEFAULT_ROUNDS = 3
MIN_MAX_TOKENS = 256
MAX_TOKENS_CAP = 4096
DEFAULT_MAX_TOKENS = 2048
MAX_TASK_CHARS = 8000
MIN_WEAKNESSES = 2

PROVIDERS = ("Claude", "Gemini")

PROPOSER_SYSTEM = """Bạn là bên ĐỀ XUẤT trong một cuộc thảo luận giữa hai AI để giải quyết task của người dùng.
- Vòng đầu: đưa ra giải pháp cụ thể, có thể làm theo được ngay.
- Các vòng sau: xét TỪNG điểm yếu mà bên kia vừa nêu. Điểm nào đúng thì sửa giải pháp; điểm nào sai thì bác bỏ kèm lý do cụ thể. Không được đồng ý chung chung cho xong, không xin lỗi rườm rà.
- Định dạng Markdown: "## Đề xuất" (bản đầy đủ hiện tại), và từ vòng 2 thêm "## Phản hồi phản biện" (mỗi điểm: chấp nhận/bác bỏ + lý do).
- Trả lời bằng ngôn ngữ của task, súc tích."""

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
Trả lời bằng ngôn ngữ của task, súc tích."""

SYNTH_SYSTEM = """Bạn là bên TỔNG HỢP. Dựa trên toàn bộ cuộc thảo luận, viết KẾT QUẢ CUỐI CÙNG hoàn chỉnh cho task của người dùng.
- Dùng đề xuất mới nhất làm nền, áp dụng các phản biện hợp lý, bỏ các phản biện đã bị bác bỏ có lý.
- Kết quả phải dùng được ngay, không kể lại quá trình tranh luận.
- Cuối cùng thêm mục ngắn "## Điểm còn tranh cãi / rủi ro" (nếu có).
- Markdown, bằng ngôn ngữ của task."""

ROLE_LABELS = {"proposer": "Đề xuất", "critic": "Phản biện", "synthesizer": "Tổng hợp"}


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


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
    done: bool = False

    @property
    def title(self) -> str:
        if self.role == "synthesizer":
            return f"Kết quả cuối — {self.speaker} ({self.model})"
        return f"Vòng {self.round} · {ROLE_LABELS[self.role]} — {self.speaker} ({self.model})"


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
        systems = {
            "proposer": PROPOSER_SYSTEM,
            "critic": CRITIC_SYSTEM,
            "synthesizer": SYNTH_SYSTEM,
        }
        try:
            for round_no, role, speaker in self._schedule():
                client = self.clients[speaker]
                turn = Turn(round=round_no, role=role, speaker=speaker, model=client.model)
                self.turns.append(turn)
                yield ("turn_start", turn)
                prompt = self._prompt(role, round_no)
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
                    for chunk in client.stream(systems[role], prompt, self.config.max_tokens):
                        if should_stop():
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
                yield ("turn_end", turn)
                if should_stop():
                    self._finish("stopped")
                    return
        except LLMError as e:
            self.error = str(e)
            self._finish("error")
            return
        self._finish("done")

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
            "turns": [asdict(t) for t in self.turns],
            "final": self.final_text,
        }

    def final_markdown(self) -> str:
        cfg = self.config
        usage = self.total_usage
        return (
            f"# Kết quả AI Debate\n\n**Task:** {cfg.task}\n\n"
            f"_Tổng hợp bởi {cfg.synthesizer} · {cfg.rounds} vòng · "
            f"{usage.total:,} token_\n\n---\n\n{self.final_text or '(chưa có kết quả cuối)'}\n"
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
        ]
        for provider, u in self.usage_by_provider.items():
            lines.append(f"- Token {provider}: vào {u.input_tokens:,} / ra {u.output_tokens:,}")
        lines += ["", "## Task", "", cfg.task, ""]
        for turn in self.turns:
            note = "" if turn.done else " _(chưa xong)_"
            lines += [f"## {turn.title}{note}", "", turn.text.strip(), ""]
        return "\n".join(lines)


def _slug(text: str, limit: int = 40) -> str:
    slug = re.sub(r"[^\w]+", "-", text.lower(), flags=re.UNICODE).strip("-")
    return slug[:limit].strip("-") or "task"


def save_log(debate: Debate, logs_dir: str | Path = "logs") -> tuple[Path, Path]:
    """Write the session to logs/ as JSON and Markdown; returns both paths."""
    folder = Path(logs_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{debate.started_at:%Y%m%d-%H%M%S}_{_slug(debate.config.task)}"
    json_path = folder / f"{stem}.json"
    md_path = folder / f"{stem}.md"
    json_path.write_text(
        json.dumps(debate.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_path.write_text(debate.to_markdown(), encoding="utf-8")
    return json_path, md_path

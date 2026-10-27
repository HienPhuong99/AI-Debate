"""AI Debate — Claude và Gemini thảo luận một task rồi trả kết quả cuối.

Chạy: streamlit run app.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import altair as alt
import streamlit as st
from dotenv import load_dotenv

from core.base import LLMError
from core.claude_client import CLAUDE_MODELS, DEFAULT_CLAUDE_MODEL, ClaudeClient
from core.debate import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_ROUNDS,
    DEFAULT_TOKEN_BUDGET,
    LANGUAGES,
    MAX_PERSONA_CHARS,
    MAX_ROUNDS,
    MAX_TOKEN_BUDGET,
    MAX_TOKENS_CAP,
    MIN_MAX_TOKENS,
    MIN_ROUNDS,
    MIN_TOKEN_BUDGET,
    MIN_WEAKNESSES,
    Debate,
    DebateConfig,
    Turn,
    format_usd,
    list_logs,
    save_log,
)
from core.gemini_client import DEFAULT_GEMINI_MODEL, GEMINI_MODELS, GeminiClient
from core.mock_client import MockClient

APP_DIR = Path(__file__).parent
LOGS_DIR = APP_DIR / "logs"
load_dotenv(APP_DIR / ".env")

AVATARS = {"Claude": "🟠", "Gemini": "🔵"}
SCORE_COLOR = "#c4613f"  # passes the dataviz validator on the light surface
EXAMPLE_TASKS = [
    "Lập kế hoạch 4 tuần học Python cho người mới, mỗi ngày 1 giờ.",
    "Thiết kế quy trình onboarding 2 tuần cho nhân viên mới ở công ty 20 người.",
    "Viết email xin tăng lương ngắn gọn, lịch sự, có số liệu đóng góp.",
    "So sánh PostgreSQL và MongoDB cho app quản lý đơn hàng nhỏ, đưa ra khuyến nghị.",
]
STATUS_LABELS = {"done": "✅ xong", "stopped": "⏹ đã dừng", "error": "❌ lỗi", "running": "… dở"}

st.set_page_config(page_title="AI Debate", page_icon="⚖️", layout="wide")
# Model replies use Markdown headings; keep them from dwarfing the page.
st.markdown(
    """<style>
    [data-testid="stChatMessage"] h1, .st-key-history_view h1 { font-size: 1.35rem; }
    [data-testid="stChatMessage"] h2, .st-key-history_view h2 { font-size: 1.15rem; }
    [data-testid="stChatMessage"] h3, [data-testid="stChatMessage"] h4,
    .st-key-history_view h3, .st-key-history_view h4 { font-size: 1.0rem; }
    </style>""",
    unsafe_allow_html=True,
)

ss = st.session_state
ss.setdefault("debate", None)
ss.setdefault("running", False)
ss.setdefault("stop_requested", False)
ss.setdefault("saved_paths", None)
ss.setdefault("form_error", None)


# ---- callbacks -------------------------------------------------------------
def build_clients(mock: bool) -> dict:
    if mock:
        return {
            "Claude": MockClient("Claude", f"mock:{ss.claude_model}"),
            "Gemini": MockClient("Gemini", f"mock:{ss.gemini_model}"),
        }
    clients, errors = {}, []
    for name, factory, model in (
        ("Claude", ClaudeClient, ss.claude_model),
        ("Gemini", GeminiClient, ss.gemini_model),
    ):
        try:
            clients[name] = factory(model=model)
        except LLMError as e:
            errors.append(str(e))
    if errors:
        raise LLMError(" ".join(errors))
    return clients


def clients_for_models(models: dict[str, str]) -> dict:
    """Clients for a saved session's models; 'mock:' models stay in demo mode."""
    load_dotenv(APP_DIR / ".env", override=True)  # pick up a key fixed after an error
    if all(m.startswith("mock:") for m in models.values()):
        return {p: MockClient(p, m) for p, m in models.items()}
    clients, errors = {}, []
    for name, factory in (("Claude", ClaudeClient), ("Gemini", GeminiClient)):
        try:
            clients[name] = factory(model=models[name].removeprefix("mock:"))
        except LLMError as e:
            errors.append(str(e))
    if errors:
        raise LLMError(" ".join(errors))
    return clients


def start(debate: Debate) -> None:
    ss.debate = debate
    ss.saved_paths = None
    ss.stop_requested = False
    ss.running = True


def on_resume() -> None:
    debate = ss.debate
    ss.form_error = None
    try:
        debate.clients = clients_for_models({p: c.model for p, c in debate.clients.items()})
        debate.prepare_resume()
    except (ValueError, LLMError) as e:
        ss.form_error = str(e)
        return
    start(debate)


def on_resume_from_log(json_path: Path) -> None:
    ss.form_error = None
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        debate = Debate.from_dict(data, clients_for_models(data["models"]), json_path.stem)
        debate.prepare_resume()
    except (OSError, KeyError, ValueError, LLMError) as e:
        ss.form_error = f"Không tiếp tục được phiên: {e}"
        return
    ss.task = debate.config.task
    start(debate)


def on_run() -> None:
    ss.form_error = None
    try:
        config = DebateConfig(
            task=ss.task,
            rounds=ss.rounds,
            max_tokens=ss.max_tokens,
            proposer=ss.proposer,
            synthesizer=ss.synthesizer,
            token_budget=ss.token_budget,
            language=ss.language,
            proposer_persona=ss.proposer_persona,
            critic_persona=ss.critic_persona,
            stop_score=ss.stop_score,
        )
        clients = build_clients(ss.mock)
    except (ValueError, LLMError) as e:
        ss.form_error = str(e)
        return
    start(Debate(config, clients))


def on_stop() -> None:
    # Clicking any widget interrupts the running script; this callback runs first on the rerun.
    ss.stop_requested = True
    ss.running = False
    if ss.debate is not None:
        ss.debate.stop()


def on_pick_example() -> None:
    if ss.example:
        ss.task = ss.example


def save_once(debate: Debate) -> None:
    if ss.saved_paths is None and debate.status in ("done", "stopped", "error"):
        try:
            ss.saved_paths = save_log(debate, LOGS_DIR)
        except OSError as e:
            st.error(f"Không ghi được log vào {LOGS_DIR}: {e}")


# ---- rendering -------------------------------------------------------------
def render_metrics(target, debate: Debate | None) -> None:
    usage = debate.usage_by_provider if debate else {}
    with target.container():
        cols = st.columns(4)
        costs = debate.cost_by_provider if debate else {}
        for col, provider in zip(cols, ("Claude", "Gemini"), strict=False):
            u = usage.get(provider)
            col.metric(
                f"Token {provider}",
                f"{u.total:,}" if u else "0",
                help="Tổng input + output (gồm cả token suy nghĩ)",
            )
            if u:
                col.caption(
                    f"vào {u.input_tokens:,} · ra {u.output_tokens:,} · "
                    f"{format_usd(costs.get(provider))}"
                )
        total = debate.total_usage.total if debate else 0
        cols[2].metric("Tổng token", f"{total:,}")
        if debate:
            budget = debate.config.token_budget
            cols[2].progress(min(total / budget, 1.0), text=f"ngân sách {budget:,}")
        cols[3].metric(
            "Chi phí ước tính",
            format_usd(debate.total_cost) if debate else "$0",
            help="Theo bảng giá chính thức (tier trả phí chuẩn). Chế độ demo: giá giả định.",
        )


def render_scores(target, debate: Debate | None) -> None:
    scores = debate.scores if debate else []
    if not scores:
        target.empty()
        return
    rows = [{"Vòng": r, "Điểm": sc} for r, sc in scores]
    chart = (
        alt.Chart(alt.Data(values=rows))
        .mark_line(
            color=SCORE_COLOR,
            strokeWidth=2,
            point=alt.OverlayMarkDef(color=SCORE_COLOR, size=80, filled=True),
        )
        .encode(
            x=alt.X("Vòng:O", axis=alt.Axis(labelAngle=0)),
            y=alt.Y(
                "Điểm:Q", scale=alt.Scale(domain=[0, 10]), axis=alt.Axis(values=[0, 2, 4, 6, 8, 10])
            ),
            tooltip=[alt.Tooltip("Vòng:O"), alt.Tooltip("Điểm:Q", format="g")],
        )
        .properties(height=180)
    )
    with target.container():
        st.markdown("**Điểm bên phản biện chấm cho đề xuất (0–10)**")
        st.altair_chart(chart, width="stretch")
        st.caption(" · ".join(f"Vòng {r}: {sc:g}/10" for r, sc in scores))


def turn_notes(turn: Turn) -> list[str]:
    notes = []
    if turn.truncated:
        notes.append("⚠️ Câu trả lời bị cắt vì chạm giới hạn max_tokens.")
    if turn.retried:
        notes.append("↻ Phản biện lần đầu chưa đủ điểm yếu nên đã được yêu cầu làm lại.")
    if turn.role == "critic" and turn.weakness_count is not None:
        if turn.weakness_count < MIN_WEAKNESSES:
            notes.append(f"⚠️ Chỉ nêu {turn.weakness_count} điểm yếu (yêu cầu ≥ {MIN_WEAKNESSES}).")
    if turn.usage_estimated:
        notes.append("≈ Token của lượt này là ước tính (bị dừng trước khi API báo số thật).")
    if turn.abandoned:
        notes.append("↻ Lượt bỏ dở này đã được chạy lại khi tiếp tục phiên.")
    elif not turn.done:
        notes.append("⏹ Lượt này chưa xong.")
    return notes


def open_turn(turn: Turn, box):
    """Draw the turn header inside `box` and return a placeholder for its body."""
    with box:
        message = st.chat_message(turn.speaker, avatar=AVATARS[turn.speaker])
        message.markdown(f"**{turn.title}**")
        body = message.empty()
        notes = message.empty()
    return body, notes


def show_turn_body(turn: Turn, body, notes) -> None:
    body.markdown(turn.text or "_(trống)_")
    lines = turn_notes(turn)
    if lines:
        notes.caption("  \n".join(lines))
    else:
        notes.empty()


def run_live(debate: Debate, conv, final_box, metrics, scores) -> None:
    slots = {}
    events = debate.run(should_stop=lambda: ss.stop_requested)
    try:
        for event in events:
            kind, turn = event[0], event[1]
            if kind == "turn_start":
                box = final_box if turn.role == "synthesizer" else conv
                slots[id(turn)] = open_turn(turn, box)
            body, notes = slots[id(turn)]
            if kind == "chunk":
                body.markdown(turn.text + " ▌")
            elif kind == "turn_reset":
                body.info("Phản biện chưa nêu đủ điểm yếu — đang yêu cầu làm lại…")
            elif kind == "turn_end":
                show_turn_body(turn, body, notes)
                render_metrics(metrics, debate)
                render_scores(scores, debate)
    finally:
        # "Dừng" interrupts this script mid-loop; close the engine now (not at some later GC)
        # so a turn cut off between chunks is marked stopped and its tokens estimated.
        events.close()


def render_final(debate: Debate) -> None:
    final = debate.final_text
    if not final:
        return
    stamp = f"{debate.started_at:%Y%m%d-%H%M%S}"
    c1, c2, c3 = st.columns(3)
    c1.download_button(
        "⬇️ Tải kết quả cuối (.md)",
        data=debate.final_markdown(),
        file_name=f"ket-qua-{stamp}.md",
        mime="text/markdown",
        on_click="ignore",
        type="primary",
        width="stretch",
    )
    c2.download_button(
        "⬇️ Tải toàn bộ hội thoại (.md)",
        data=debate.to_markdown(),
        file_name=f"hoi-thoai-{stamp}.md",
        mime="text/markdown",
        on_click="ignore",
        width="stretch",
    )
    c3.download_button(
        "⬇️ Tải log (.json)",
        data=json.dumps(debate.to_dict(), ensure_ascii=False, indent=2),
        file_name=f"phien-{stamp}.json",
        mime="application/json",
        on_click="ignore",
        width="stretch",
    )


# ---- sidebar ---------------------------------------------------------------
with st.sidebar:
    st.header("Cấu hình")
    locked = ss.running
    st.selectbox(
        "Model Claude",
        CLAUDE_MODELS,
        index=CLAUDE_MODELS.index(DEFAULT_CLAUDE_MODEL),
        key="claude_model",
        disabled=locked,
    )
    st.selectbox(
        "Model Gemini",
        GEMINI_MODELS,
        index=GEMINI_MODELS.index(DEFAULT_GEMINI_MODEL),
        key="gemini_model",
        disabled=locked,
    )
    st.radio(
        "Bên đề xuất (bên kia chỉ phản biện)",
        ["Claude", "Gemini"],
        key="proposer",
        horizontal=True,
        disabled=locked,
    )
    st.radio(
        "Bên tổng hợp kết quả cuối",
        ["Claude", "Gemini"],
        key="synthesizer",
        horizontal=True,
        disabled=locked,
    )
    st.slider("Số vòng", MIN_ROUNDS, MAX_ROUNDS, DEFAULT_ROUNDS, key="rounds", disabled=locked)
    st.slider(
        "max_tokens mỗi lượt",
        MIN_MAX_TOKENS,
        MAX_TOKENS_CAP,
        DEFAULT_MAX_TOKENS,
        step=256,
        key="max_tokens",
        disabled=locked,
        help=f"Giới hạn cứng: tối đa {MAX_ROUNDS} vòng và {MAX_TOKENS_CAP} token/lượt.",
    )
    st.number_input(
        "Ngân sách token cả phiên",
        MIN_TOKEN_BUDGET,
        MAX_TOKEN_BUDGET,
        DEFAULT_TOKEN_BUDGET,
        step=5_000,
        key="token_budget",
        disabled=locked,
        help="Vượt ngân sách thì bỏ các vòng còn lại và chuyển thẳng sang tổng hợp.",
    )
    st.selectbox(
        "Dừng sớm khi điểm phản biện ≥",
        [0, 7, 8, 9, 10],
        index=0,
        format_func=lambda v: "Tắt" if v == 0 else f"{v}/10",
        key="stop_score",
        disabled=locked,
        help="Bên phản biện chấm đề xuất mỗi vòng. Đạt ngưỡng thì bỏ các vòng còn lại "
        "và chuyển sang tổng hợp để tiết kiệm token.",
    )
    st.selectbox(
        "Ngôn ngữ trả lời",
        list(LANGUAGES),
        format_func=LANGUAGES.get,
        key="language",
        disabled=locked,
    )
    with st.expander("Vai chuyên môn (tuỳ chọn)"):
        st.text_input(
            "Bên đề xuất đóng vai",
            key="proposer_persona",
            max_chars=MAX_PERSONA_CHARS,
            placeholder="vd: kiến trúc sư phần mềm 10 năm kinh nghiệm",
            disabled=locked,
        )
        st.text_input(
            "Bên phản biện đóng vai",
            key="critic_persona",
            max_chars=MAX_PERSONA_CHARS,
            placeholder="vd: kỹ sư bảo mật khó tính",
            disabled=locked,
        )
        st.caption("Vai chỉ thêm góc nhìn; quy tắc phản biện ≥ 2 điểm yếu vẫn giữ nguyên.")
    st.toggle(
        "Chế độ demo (mock, không gọi API)",
        value=os.getenv("AI_DEBATE_MOCK") == "1",
        key="mock",
        disabled=locked,
    )
    st.caption(
        f"Mỗi phiên gồm {2 * ss.rounds + 1} lượt gọi model "
        f"(tối đa ~{(2 * ss.rounds + 1) * ss.max_tokens:,} token output)."
    )

# ---- main ------------------------------------------------------------------
st.title("⚖️ AI Debate")
st.caption(
    "Claude và Gemini thảo luận task của bạn: một bên đề xuất, một bên phản biện, rồi tổng hợp."
)

tab_run, tab_history = st.tabs(["Phiên hiện tại", "Lịch sử"])


def render_history() -> None:
    sessions = list_logs(LOGS_DIR)
    if not sessions:
        st.info("Chưa có phiên nào trong `logs/`.")
        return
    st.caption(f"{len(sessions)} phiên đã lưu trong `logs/` (mới nhất trước).")

    def label(i: int) -> str:
        item = sessions[i]
        task = item["task"] if len(item["task"]) <= 60 else item["task"][:57] + "…"
        when = item["started_at"].replace("T", " ")
        status = STATUS_LABELS.get(item["status"], item["status"])
        return f"{when} · {status} · {item['tokens']:,} token · {task}"

    choice = st.selectbox("Chọn phiên", range(len(sessions)), format_func=label, key="history_pick")
    item = sessions[choice]
    md = item["md"].read_text(encoding="utf-8") if item["md"].exists() else "(thiếu file .md)"
    c1, c2, c3 = st.columns([1, 1, 2])
    if item["resumable"]:
        c3.button(
            "↻ Tiếp tục phiên này",
            on_click=on_resume_from_log,
            args=(item["json"],),
            key="history_resume",
            help="Giữ các lượt đã xong, chạy tiếp từ lượt bị dừng/lỗi. Mở tab Phiên hiện tại để xem.",
        )
    c1.download_button(
        "⬇️ Tải .md",
        data=md,
        file_name=item["md"].name,
        mime="text/markdown",
        on_click="ignore",
        width="stretch",
        key="history_md",
    )
    c2.download_button(
        "⬇️ Tải .json",
        data=item["json"].read_text(encoding="utf-8"),
        file_name=item["json"].name,
        mime="application/json",
        on_click="ignore",
        width="stretch",
        key="history_json",
    )
    st.caption(f"Chi phí ước tính: {format_usd(item['cost'])}")
    with st.container(border=True, key="history_view"):
        st.markdown(md)


# History is drawn first: a live run below blocks the script until it finishes.
with tab_history:
    if ss.running:
        st.info(
            "Đang chạy một phiên — mở tab **Phiên hiện tại** để xem; lịch sử hiện lại sau khi xong."
        )
    else:
        render_history()

with tab_run:
    st.selectbox(
        "Task mẫu",
        [""] + EXAMPLE_TASKS,
        key="example",
        on_change=on_pick_example,
        format_func=lambda x: x or "— chọn nhanh một task mẫu —",
        disabled=ss.running,
    )
    st.text_area(
        "Task",
        key="task",
        height=120,
        placeholder="Ví dụ: Lập kế hoạch 4 tuần học Python cho người mới, mỗi ngày 1 giờ.",
        disabled=ss.running,
    )
    b1, b2, _ = st.columns([1, 1, 4])
    b1.button("▶ Chạy", on_click=on_run, disabled=ss.running, type="primary", width="stretch")
    b2.button("⏹ Dừng", on_click=on_stop, disabled=not ss.running, width="stretch")

    if ss.form_error:
        st.error(ss.form_error)

    status_box = st.container()
    metrics = st.empty()
    scores = st.empty()
    st.subheader("Hội thoại")
    conv = st.container()
    st.subheader("Kết quả cuối")
    final_box = st.container(border=True)

debate: Debate | None = ss.debate
render_metrics(metrics, debate)
render_scores(scores, debate)

if debate is None:
    conv.info("Nhập task rồi bấm **Chạy** để bắt đầu.")
elif ss.running and debate.status == "pending":
    for turn in debate.turns:  # a resumed session shows its earlier turns first
        show_turn_body(turn, *open_turn(turn, conv))
    run_live(debate, conv, final_box, metrics, scores)
    ss.running = False
    save_once(debate)
    st.rerun()
else:
    for turn in debate.turns:
        body, notes = open_turn(turn, final_box if turn.role == "synthesizer" else conv)
        show_turn_body(turn, body, notes)
    save_once(debate)
    with final_box:
        if debate.final_text:
            render_final(debate)
        else:
            st.caption("Chưa có kết quả cuối.")
    with status_box:
        if debate.status == "stopped":
            st.warning("Đã dừng theo yêu cầu. Phần hội thoại đã có vẫn được lưu.")
        elif debate.status == "error":
            st.error(f"Lỗi khi gọi API: {debate.error}")
        if debate.can_resume:
            st.button(
                "↻ Tiếp tục phiên",
                on_click=on_resume,
                help="Giữ các lượt đã xong, chạy tiếp từ lượt bị dừng/lỗi "
                "(sửa key trong .env trước nếu lỗi do key).",
            )
        elif debate.status == "done":
            st.success("Hoàn tất.")
        if debate.budget_hit:
            st.info(
                f"Đã chạm ngân sách {debate.config.token_budget:,} token nên bỏ các vòng còn lại "
                "và chuyển thẳng sang tổng hợp."
            )
        if debate.early_stopped:
            st.info(
                f"Điểm phản biện đạt ngưỡng {debate.config.stop_score}/10 nên dừng sớm "
                "và chuyển sang tổng hợp."
            )
        if ss.saved_paths:
            names = ", ".join(p.name for p in ss.saved_paths)
            st.caption(f"Log phiên: `logs/` → {names}")

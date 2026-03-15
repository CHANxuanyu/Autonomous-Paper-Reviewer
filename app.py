from __future__ import annotations

import html
import time
from typing import Any

import requests
import streamlit as st

API_BASE_URL = "http://127.0.0.1:8000"
POLL_INTERVAL_SECONDS = 2
TERMINAL_STATUSES = {"COMPLETED", "FAILED"}
STATUS_FLOW = [
    "PENDING",
    "PARSING_DOC",
    "VECTORIZING",
    "AGENT_PLANNING",
    "EVIDENCE_RETRIEVAL",
    "REPORT_GENERATING",
    "COMPLETED",
]
STATUS_COPY = {
    "PENDING": "Queued and waiting for a worker slot.",
    "PARSING_DOC": "Reading the PDF and extracting the paper structure.",
    "VECTORIZING": "Building embeddings for retrieval and evidence search.",
    "AGENT_PLANNING": "Drafting the review plan and focus map.",
    "EVIDENCE_RETRIEVAL": "Pulling the most relevant paper chunks for support.",
    "REPORT_GENERATING": "Composing the final structured review.",
    "COMPLETED": "The review is ready to read.",
    "FAILED": "The pipeline stopped before the review could finish.",
}


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(212, 143, 84, 0.18), transparent 28%),
                radial-gradient(circle at bottom right, rgba(42, 110, 92, 0.14), transparent 30%),
                linear-gradient(135deg, #f7f1e8 0%, #f1eee7 42%, #eef4f1 100%);
            color: #14222b;
        }

        html, body, [class*="css"] {
            font-family: "Avenir Next", "Segoe UI", sans-serif;
        }

        h1, h2, h3, h4 {
            font-family: Georgia, "Times New Roman", serif;
            letter-spacing: -0.02em;
        }

        [data-testid="block-container"] {
            padding-top: 2.4rem;
            padding-bottom: 2.8rem;
            max-width: 1280px;
        }

        .hero-shell {
            background: linear-gradient(140deg, rgba(20, 34, 43, 0.95), rgba(43, 72, 69, 0.9));
            border: 1px solid rgba(255, 255, 255, 0.18);
            border-radius: 28px;
            color: #f6efe5;
            padding: 1.8rem 1.9rem 1.6rem;
            box-shadow: 0 28px 90px rgba(15, 28, 35, 0.15);
            margin-bottom: 1.4rem;
        }

        .hero-eyebrow {
            text-transform: uppercase;
            letter-spacing: 0.18em;
            font-size: 0.72rem;
            opacity: 0.72;
            margin-bottom: 0.9rem;
        }

        .hero-title {
            font-size: 3rem;
            line-height: 1.02;
            margin: 0;
        }

        .hero-subtitle {
            max-width: 820px;
            margin-top: 0.95rem;
            font-size: 1.03rem;
            line-height: 1.72;
            color: rgba(246, 239, 229, 0.82);
        }

        .panel-shell {
            background: rgba(255, 255, 255, 0.72);
            border: 1px solid rgba(20, 34, 43, 0.08);
            border-radius: 24px;
            padding: 1.2rem 1.25rem 1.05rem;
            box-shadow: 0 20px 70px rgba(31, 49, 63, 0.09);
            backdrop-filter: blur(10px);
        }

        .panel-title {
            text-transform: uppercase;
            letter-spacing: 0.12em;
            font-size: 0.76rem;
            color: #6a5d52;
            margin-bottom: 0.35rem;
        }

        .panel-heading {
            font-size: 1.55rem;
            color: #14222b;
            margin-bottom: 0.3rem;
        }

        .panel-copy {
            color: #55616a;
            line-height: 1.64;
            margin-bottom: 1rem;
        }

        .meta-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.8rem;
            margin: 0.85rem 0 0.35rem;
        }

        .meta-card {
            padding: 0.82rem 0.92rem;
            background: rgba(247, 241, 232, 0.68);
            border: 1px solid rgba(20, 34, 43, 0.08);
            border-radius: 18px;
        }

        .meta-label {
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            color: #7f7268;
            margin-bottom: 0.35rem;
        }

        .meta-value {
            color: #14222b;
            font-size: 0.95rem;
            word-break: break-word;
        }

        .status-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.75rem;
            margin-top: 1rem;
        }

        .stage-card {
            border-radius: 18px;
            padding: 0.9rem;
            border: 1px solid rgba(20, 34, 43, 0.08);
            background: rgba(255, 255, 255, 0.8);
            min-height: 120px;
        }

        .stage-card.done {
            background: rgba(236, 247, 241, 0.96);
            border-color: rgba(42, 110, 92, 0.22);
        }

        .stage-card.active {
            background: linear-gradient(160deg, rgba(20, 34, 43, 0.96), rgba(57, 89, 84, 0.92));
            border-color: rgba(255, 255, 255, 0.12);
            color: #f6efe5;
            transform: translateY(-1px);
        }

        .stage-card.pending {
            opacity: 0.76;
        }

        .stage-index {
            display: inline-flex;
            width: 1.85rem;
            height: 1.85rem;
            align-items: center;
            justify-content: center;
            border-radius: 999px;
            background: rgba(20, 34, 43, 0.08);
            font-size: 0.82rem;
            font-weight: 700;
            margin-bottom: 0.75rem;
        }

        .stage-card.active .stage-index {
            background: rgba(246, 239, 229, 0.14);
        }

        .stage-name {
            font-size: 0.96rem;
            font-weight: 700;
            margin-bottom: 0.35rem;
        }

        .stage-text {
            font-size: 0.88rem;
            line-height: 1.55;
        }

        .summary-card, .result-card, .empty-card {
            border-radius: 22px;
            border: 1px solid rgba(20, 34, 43, 0.08);
            background: rgba(255, 255, 255, 0.78);
            padding: 1.1rem 1.15rem;
            box-shadow: 0 16px 60px rgba(31, 49, 63, 0.06);
        }

        .summary-card {
            background: linear-gradient(140deg, rgba(255, 255, 255, 0.82), rgba(247, 241, 232, 0.95));
            margin-top: 0.3rem;
        }

        .section-kicker {
            text-transform: uppercase;
            letter-spacing: 0.13em;
            font-size: 0.74rem;
            color: #8b6c48;
            margin-bottom: 0.6rem;
        }

        .summary-copy {
            font-size: 1rem;
            line-height: 1.82;
            color: #1a2a34;
            margin: 0;
        }

        .result-list {
            margin: 0;
            padding-left: 1.05rem;
            color: #22323d;
            line-height: 1.7;
        }

        .result-list li {
            margin-bottom: 0.42rem;
        }

        .muted-copy {
            color: #66737d;
            line-height: 1.65;
            margin: 0;
        }

        [data-testid="stFileUploader"] {
            border-radius: 18px;
            border: 1px dashed rgba(20, 34, 43, 0.24);
            background: rgba(248, 245, 239, 0.88);
            padding: 0.35rem 0.5rem;
        }

        [data-testid="stTextInputRootElement"] > div > div {
            border-radius: 14px;
        }

        div[data-testid="stButton"] > button {
            border-radius: 999px;
            min-height: 3.1rem;
            font-weight: 700;
            letter-spacing: 0.02em;
            border: none;
            background: linear-gradient(135deg, #c86f42, #b85748);
            color: white;
            box-shadow: 0 18px 30px rgba(184, 87, 72, 0.2);
        }

        div[data-testid="stButton"] > button:hover {
            background: linear-gradient(135deg, #b65f37, #a94e40);
        }

        .focus-pill {
            display: inline-flex;
            align-items: center;
            padding: 0.35rem 0.7rem;
            border-radius: 999px;
            background: rgba(20, 34, 43, 0.06);
            border: 1px solid rgba(20, 34, 43, 0.08);
            margin: 0.12rem 0.4rem 0.12rem 0;
            font-size: 0.86rem;
            color: #22323d;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def init_session_state() -> None:
    defaults: dict[str, Any] = {
        "document_id": None,
        "task_id": None,
        "review_status": None,
        "review_result": None,
        "error_message": None,
        "retry_count": None,
        "status_history": [],
        "focus_areas": [],
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def friendly_status(status: str | None) -> str:
    if not status:
        return "Idle"
    return status.replace("_", " ").title()


def parse_focus_areas(raw_focus_areas: str) -> list[str]:
    return [item.strip() for item in raw_focus_areas.split(",") if item.strip()]


def format_text(value: Any) -> str:
    return html.escape(str(value or "")).replace("\n", "<br>")


def extract_error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text or f"Unexpected HTTP {response.status_code}"

    detail = payload.get("detail")
    if isinstance(detail, list):
        return "; ".join(str(item) for item in detail)
    if detail:
        return str(detail)
    return str(payload)


def progress_for_status(status: str, history: list[str]) -> float:
    if status == "COMPLETED":
        return 1.0
    if status == "FAILED":
        completed_steps = max(len(history), 1)
        return min(completed_steps / len(STATUS_FLOW), 0.92)
    if status in STATUS_FLOW:
        return max((STATUS_FLOW.index(status) + 1) / len(STATUS_FLOW), 0.08)
    return 0.0


def create_document(uploaded_file: Any) -> str:
    files = {
        "file": (
            uploaded_file.name,
            uploaded_file.getvalue(),
            uploaded_file.type or "application/pdf",
        )
    }
    response = requests.post(
        f"{API_BASE_URL}/api/v1/documents",
        files=files,
        timeout=120,
    )
    if not response.ok:
        raise RuntimeError(f"Document upload failed: {extract_error_message(response)}")
    return response.json()["document_id"]


def create_review(document_id: str, focus_areas: list[str]) -> tuple[str, str]:
    payload = {"document_id": document_id, "focus_areas": focus_areas}
    response = requests.post(
        f"{API_BASE_URL}/api/v1/reviews",
        json=payload,
        timeout=60,
    )
    if not response.ok:
        raise RuntimeError(f"Review creation failed: {extract_error_message(response)}")
    data = response.json()
    return data["task_id"], data["status"]


def render_focus_pills(focus_areas: list[str]) -> None:
    if not focus_areas:
        st.caption("No specific focus areas selected. The review will stay broad.")
        return

    pill_markup = "".join(
        f"<span class='focus-pill'>{html.escape(area)}</span>" for area in focus_areas
    )
    st.markdown(pill_markup, unsafe_allow_html=True)


def render_stage_grid(current_status: str, history: list[str]) -> str:
    cards: list[str] = []
    for index, stage in enumerate(STATUS_FLOW[:-1], start=1):
        if stage == current_status:
            variant = "active"
        elif stage in history:
            variant = "done"
        else:
            variant = "pending"

        cards.append(
            f"""
            <div class="stage-card {variant}">
                <div class="stage-index">{index}</div>
                <div class="stage-name">{html.escape(friendly_status(stage))}</div>
                <div class="stage-text">{html.escape(STATUS_COPY[stage])}</div>
            </div>
            """
        )

    return f"<div class='status-grid'>{''.join(cards)}</div>"


def render_result_card(title: str, items: list[str]) -> None:
    if items:
        body = "<ul class='result-list'>" + "".join(
            f"<li>{format_text(item)}</li>" for item in items
        ) + "</ul>"
    else:
        body = "<p class='muted-copy'>No notes were generated for this section.</p>"

    st.markdown(
        f"""
        <div class="result-card">
            <div class="section-kicker">{html.escape(title)}</div>
            {body}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_results(payload: dict[str, Any]) -> None:
    result = payload.get("result_json") or {}

    st.success("Review completed successfully.")
    st.markdown(
        f"""
        <div class="summary-card">
            <div class="section-kicker">Summary</div>
            <p class="summary-copy">{format_text(result.get("summary") or "No summary returned.")}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    upper_left, upper_right = st.columns(2, gap="large")
    with upper_left:
        render_result_card("Strengths", list(result.get("strengths") or []))
    with upper_right:
        render_result_card("Weaknesses", list(result.get("weaknesses") or []))

    lower_left, lower_right = st.columns(2, gap="large")
    with lower_left:
        render_result_card("Missing Evidence", list(result.get("missing_evidence") or []))
    with lower_right:
        render_result_card("Questions For Authors", list(result.get("questions_for_authors") or []))


def render_idle_state() -> None:
    st.markdown(
        """
        <div class="empty-card">
            <div class="section-kicker">Results Console</div>
            <h3 style="margin-top:0; margin-bottom:0.45rem;">Your review output will appear here</h3>
            <p class="muted-copy">
                Upload a PDF, choose a few focus areas, and start the review. The right side will track
                each workflow stage live, then unfold the final report once the worker finishes.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def poll_review(task_id: str) -> None:
    status_placeholder = st.empty()
    progress_placeholder = st.empty()
    meta_placeholder = st.empty()
    stages_placeholder = st.empty()
    result_placeholder = st.empty()

    while True:
        try:
            response = requests.get(
                f"{API_BASE_URL}/api/v1/reviews/{task_id}",
                timeout=30,
            )
        except requests.RequestException as exc:
            st.session_state.error_message = f"Polling failed: {exc}"
            st.session_state.review_status = "FAILED"
            break

        if not response.ok:
            st.session_state.error_message = extract_error_message(response)
            st.session_state.review_status = "FAILED"
            break

        payload = response.json()
        current_status = str(payload.get("status"))
        st.session_state.review_status = current_status
        st.session_state.review_result = payload.get("result_json")
        st.session_state.error_message = payload.get("error_message")
        st.session_state.retry_count = payload.get("retry_count")

        if not st.session_state.status_history or st.session_state.status_history[-1] != current_status:
            st.session_state.status_history.append(current_status)

        message = STATUS_COPY.get(current_status, "Working through the review pipeline.")
        if current_status == "FAILED":
            status_placeholder.error(f"{friendly_status(current_status)}: {message}")
        elif current_status == "COMPLETED":
            status_placeholder.success(f"{friendly_status(current_status)}: {message}")
        else:
            status_placeholder.info(f"{friendly_status(current_status)}: {message}")

        progress_placeholder.progress(
            progress_for_status(current_status, st.session_state.status_history),
            text=f"Pipeline state: {friendly_status(current_status)}",
        )

        meta_placeholder.markdown(
            f"""
            <div class="meta-grid">
                <div class="meta-card">
                    <div class="meta-label">Task ID</div>
                    <div class="meta-value">{html.escape(task_id)}</div>
                </div>
                <div class="meta-card">
                    <div class="meta-label">Retry Count</div>
                    <div class="meta-value">{st.session_state.retry_count or 0}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        stages_placeholder.markdown(
            render_stage_grid(current_status, st.session_state.status_history),
            unsafe_allow_html=True,
        )

        if current_status == "COMPLETED":
            with result_placeholder.container():
                render_results(payload)
            break

        if current_status == "FAILED":
            with result_placeholder.container():
                st.error(st.session_state.error_message or "The review pipeline failed.")
            break

        time.sleep(POLL_INTERVAL_SECONDS)


def render_existing_state() -> None:
    if not st.session_state.task_id:
        render_idle_state()
        return

    if st.session_state.review_status not in TERMINAL_STATUSES:
        poll_review(st.session_state.task_id)
        return

    st.info(
        f"{friendly_status(st.session_state.review_status)}: "
        f"{STATUS_COPY.get(st.session_state.review_status or '', 'No status copy available.')}"
    )
    st.progress(
        progress_for_status(
            st.session_state.review_status or "FAILED",
            st.session_state.status_history,
        ),
        text=f"Pipeline state: {friendly_status(st.session_state.review_status)}",
    )

    st.markdown(
        f"""
        <div class="meta-grid">
            <div class="meta-card">
                <div class="meta-label">Task ID</div>
                <div class="meta-value">{html.escape(str(st.session_state.task_id))}</div>
            </div>
            <div class="meta-card">
                <div class="meta-label">Retry Count</div>
                <div class="meta-value">{st.session_state.retry_count or 0}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        render_stage_grid(
            st.session_state.review_status or "FAILED",
            st.session_state.status_history,
        ),
        unsafe_allow_html=True,
    )

    if st.session_state.review_status == "COMPLETED":
        render_results({"result_json": st.session_state.review_result or {}})
    else:
        st.error(st.session_state.error_message or "The review pipeline failed.")


def main() -> None:
    st.set_page_config(
        page_title="AI Paper Analyzer",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    inject_styles()
    init_session_state()

    st.markdown(
        """
        <div class="hero-shell">
            <div class="hero-eyebrow">Academic Intelligence Workspace</div>
            <h1 class="hero-title">AI Paper Analyzer</h1>
            <div class="hero-subtitle">
                Drop in a research paper, steer the review with a few focus areas, and watch the backend
                move from parsing to evidence retrieval to the final peer-review style report.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    left_col, right_col = st.columns([0.92, 1.28], gap="large")

    with left_col:
        st.markdown(
            """
            <div class="panel-shell">
                <div class="panel-title">Inputs</div>
                <div class="panel-heading">Launch a new analysis</div>
                <div class="panel-copy">
                Upload a PDF and optionally guide the review with focus areas such as methodology,
                novelty, baselines, limitations, or statistical rigor.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        uploaded_file = st.file_uploader(
            "Paper PDF",
            type=["pdf"],
            help="Upload the research paper you want the review pipeline to analyze.",
        )
        focus_input = st.text_input(
            "Focus Areas",
            placeholder="methodology, novelty, baselines, limitations",
            help="Comma-separated topics to emphasize during the review.",
        )

        if st.button("Start Review", use_container_width=True):
            if uploaded_file is None:
                st.warning("Please upload a PDF before starting the review.")
            else:
                focus_areas = parse_focus_areas(focus_input)
                try:
                    with st.spinner("Uploading paper and creating the review task..."):
                        document_id = create_document(uploaded_file)
                        task_id, initial_status = create_review(document_id, focus_areas)
                except Exception as exc:
                    st.session_state.error_message = str(exc)
                    st.session_state.review_status = "FAILED"
                    st.error(str(exc))
                else:
                    st.session_state.document_id = document_id
                    st.session_state.task_id = task_id
                    st.session_state.review_status = initial_status
                    st.session_state.review_result = None
                    st.session_state.error_message = None
                    st.session_state.retry_count = 0
                    st.session_state.status_history = [initial_status]
                    st.session_state.focus_areas = focus_areas
                    st.success("Review task submitted. The live pipeline is now tracking on the right.")

        if st.session_state.document_id or st.session_state.task_id:
            st.markdown(
                f"""
                <div class="meta-grid">
                    <div class="meta-card">
                        <div class="meta-label">Document ID</div>
                        <div class="meta-value">{html.escape(str(st.session_state.document_id or "Pending"))}</div>
                    </div>
                    <div class="meta-card">
                        <div class="meta-label">Task ID</div>
                        <div class="meta-value">{html.escape(str(st.session_state.task_id or "Pending"))}</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown("<div style='margin-top: 0.9rem;'></div>", unsafe_allow_html=True)
        st.caption("Selected focus areas")
        render_focus_pills(st.session_state.focus_areas)

    with right_col:
        st.markdown(
            """
            <div class="panel-shell">
                <div class="panel-title">Results</div>
                <div class="panel-heading">Review pipeline and report</div>
                <div class="panel-copy">
                This panel polls the FastAPI backend every two seconds, surfaces the current state
                machine stage, and unfolds the final structured review when the task completes.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        render_existing_state()


if __name__ == "__main__":
    main()

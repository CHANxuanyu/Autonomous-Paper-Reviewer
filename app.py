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
    "VECTORIZING": "Building multimodal chunks, embeddings, and visual anchors.",
    "AGENT_PLANNING": "Drafting the review strategy and deciding what deserves attention.",
    "EVIDENCE_RETRIEVAL": "Pulling text evidence and linked figures from the vector index.",
    "REPORT_GENERATING": "Running multimodal reasoning and optional ArXiv fact-checking.",
    "COMPLETED": "The review is ready to read.",
    "FAILED": "The pipeline stopped before the review could finish.",
}
STATUS_LABELS = {
    "PENDING": "⏳ Waiting in the launch queue...",
    "PARSING_DOC": "📚 Parsing PDF structure...",
    "VECTORIZING": "🧩 Chunking & extracting images...",
    "AGENT_PLANNING": "🧠 Planning the review strategy...",
    "EVIDENCE_RETRIEVAL": "🔎 Retrieving evidence & visual context...",
    "REPORT_GENERATING": "🕵️‍♂️ Agent fact-checking on ArXiv...",
    "COMPLETED": "✨ Review Completed!",
    "FAILED": "⚠️ Review interrupted",
}


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Source+Serif+4:wght@600;700&display=swap');

        :root {
            --ink: #15233b;
            --muted: #61708f;
            --line: rgba(87, 105, 160, 0.16);
            --card: rgba(255, 255, 255, 0.82);
            --card-strong: rgba(255, 255, 255, 0.96);
            --lavender: #8f7cff;
            --blue: #65b5ff;
            --mint: #6fe1c5;
            --peach: #ffb38e;
        }

        .stApp {
            background:
                radial-gradient(circle at top left, rgba(143, 124, 255, 0.19), transparent 26%),
                radial-gradient(circle at top right, rgba(101, 181, 255, 0.16), transparent 24%),
                radial-gradient(circle at bottom left, rgba(111, 225, 197, 0.16), transparent 24%),
                linear-gradient(145deg, #f7f8ff 0%, #f6fbff 38%, #f9fcfb 100%);
            color: var(--ink);
        }

        html, body, [class*="css"] {
            font-family: "Manrope", "Segoe UI", sans-serif;
        }

        h1, h2, h3, h4 {
            font-family: "Source Serif 4", Georgia, serif;
            letter-spacing: -0.02em;
            color: var(--ink);
        }

        [data-testid="block-container"] {
            max-width: 1320px;
            padding-top: 2.3rem;
            padding-bottom: 3rem;
        }

        [data-testid="stSidebar"] > div:first-child {
            background:
                linear-gradient(180deg, rgba(255, 255, 255, 0.95), rgba(246, 248, 255, 0.92)),
                linear-gradient(180deg, rgba(143, 124, 255, 0.06), rgba(101, 181, 255, 0.05));
            border-right: 1px solid var(--line);
        }

        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
            color: var(--muted);
            line-height: 1.65;
        }

        .hero-shell {
            position: relative;
            overflow: hidden;
            padding: 1.8rem 1.85rem 1.55rem;
            border-radius: 28px;
            border: 1px solid rgba(255, 255, 255, 0.6);
            background:
                radial-gradient(circle at top right, rgba(255, 255, 255, 0.18), transparent 28%),
                linear-gradient(135deg, rgba(26, 39, 88, 0.96), rgba(77, 65, 157, 0.94) 48%, rgba(66, 145, 177, 0.92));
            box-shadow: 0 24px 80px rgba(52, 61, 130, 0.18);
            margin-bottom: 1.25rem;
            color: white;
        }

        .hero-shell:after {
            content: "";
            position: absolute;
            width: 240px;
            height: 240px;
            right: -60px;
            top: -80px;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.11);
            filter: blur(4px);
        }

        .hero-kicker {
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            padding: 0.4rem 0.8rem;
            border-radius: 999px;
            background: rgba(255, 255, 255, 0.12);
            border: 1px solid rgba(255, 255, 255, 0.18);
            font-size: 0.78rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            font-weight: 700;
        }

        .hero-copy {
            max-width: 820px;
            margin-top: 0.85rem;
            font-size: 1.02rem;
            line-height: 1.75;
            color: rgba(255, 255, 255, 0.88);
        }

        .glass-card {
            background: var(--card);
            border: 1px solid rgba(255, 255, 255, 0.82);
            border-radius: 22px;
            box-shadow: 0 16px 48px rgba(73, 94, 158, 0.09);
            padding: 1.05rem 1.1rem;
            backdrop-filter: blur(16px);
        }

        .overview-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.85rem;
            margin-bottom: 1rem;
        }

        .overview-card {
            background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(245, 248, 255, 0.92));
            border: 1px solid var(--line);
            border-radius: 18px;
            padding: 0.95rem 1rem;
            box-shadow: 0 12px 34px rgba(73, 94, 158, 0.08);
        }

        .overview-label {
            font-size: 0.73rem;
            text-transform: uppercase;
            letter-spacing: 0.11em;
            color: var(--muted);
            margin-bottom: 0.45rem;
        }

        .overview-value {
            font-size: 0.95rem;
            font-weight: 700;
            color: var(--ink);
            word-break: break-word;
        }

        .focus-pill {
            display: inline-flex;
            align-items: center;
            padding: 0.42rem 0.78rem;
            border-radius: 999px;
            background: rgba(143, 124, 255, 0.09);
            border: 1px solid rgba(143, 124, 255, 0.16);
            color: #43357c;
            margin: 0.12rem 0.45rem 0.12rem 0;
            font-size: 0.86rem;
            font-weight: 600;
        }

        .stage-strip {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 0.75rem;
            margin-top: 0.5rem;
        }

        .stage-pill {
            border-radius: 18px;
            padding: 0.8rem 0.86rem;
            border: 1px solid var(--line);
            background: rgba(255, 255, 255, 0.72);
            min-height: 92px;
        }

        .stage-pill.active {
            background: linear-gradient(145deg, rgba(143, 124, 255, 0.92), rgba(101, 181, 255, 0.92));
            color: white;
            transform: translateY(-1px);
            box-shadow: 0 14px 28px rgba(111, 120, 224, 0.18);
        }

        .stage-pill.done {
            background: rgba(111, 225, 197, 0.12);
            border-color: rgba(111, 225, 197, 0.35);
        }

        .stage-pill.pending {
            opacity: 0.76;
        }

        .stage-title {
            font-size: 0.9rem;
            font-weight: 700;
            margin-bottom: 0.35rem;
        }

        .stage-note {
            font-size: 0.82rem;
            line-height: 1.5;
        }

        .result-hero {
            padding: 1.15rem 1.2rem;
            border-radius: 24px;
            background:
                radial-gradient(circle at top left, rgba(143, 124, 255, 0.16), transparent 30%),
                linear-gradient(155deg, rgba(255, 255, 255, 0.95), rgba(245, 248, 255, 0.96));
            border: 1px solid var(--line);
            box-shadow: 0 16px 48px rgba(73, 94, 158, 0.09);
            margin-bottom: 1rem;
        }

        .summary-copy {
            margin: 0;
            font-size: 1rem;
            line-height: 1.82;
            color: #223150;
        }

        .reference-card {
            padding: 1rem 1.05rem;
            border-radius: 18px;
            background: linear-gradient(160deg, rgba(255, 255, 255, 0.98), rgba(246, 248, 255, 0.92));
            border: 1px solid rgba(143, 124, 255, 0.14);
            box-shadow: 0 14px 36px rgba(73, 94, 158, 0.08);
            margin-bottom: 0.9rem;
        }

        .reference-title {
            font-size: 1rem;
            font-weight: 800;
            color: var(--ink);
            margin-bottom: 0.35rem;
        }

        .reference-meta {
            font-size: 0.84rem;
            color: var(--muted);
            line-height: 1.55;
            margin-bottom: 0.2rem;
        }

        .reference-card blockquote {
            margin: 0.85rem 0 0;
            padding: 0.85rem 1rem;
            border-left: 4px solid rgba(143, 124, 255, 0.48);
            background: rgba(143, 124, 255, 0.06);
            border-radius: 0 12px 12px 0;
            color: #33415f;
        }

        .empty-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.9rem;
            margin-top: 1rem;
        }

        .empty-card {
            padding: 1rem;
            border-radius: 20px;
            background: rgba(255, 255, 255, 0.88);
            border: 1px solid var(--line);
            box-shadow: 0 14px 36px rgba(73, 94, 158, 0.08);
        }

        .empty-card h4 {
            margin: 0 0 0.4rem;
            font-size: 1.03rem;
        }

        .empty-card p {
            margin: 0;
            color: var(--muted);
            line-height: 1.66;
        }

        [data-testid="stFileUploader"] section,
        [data-testid="stTextInputRootElement"] > div,
        [data-testid="stStatusWidget"] {
            border-radius: 18px;
            box-shadow: 0 10px 30px rgba(73, 94, 158, 0.08);
        }

        [data-testid="stFileUploader"] section {
            border: 1px dashed rgba(143, 124, 255, 0.32);
            background: rgba(255, 255, 255, 0.76);
        }

        [data-testid="stTextInputRootElement"] input {
            border-radius: 14px;
        }

        div[data-testid="stButton"] > button,
        div[data-testid="stFormSubmitButton"] > button {
            border-radius: 12px;
            min-height: 3.05rem;
            font-weight: 800;
            border: none;
            color: white;
            background: linear-gradient(135deg, #7d77ff 0%, #52b1ff 100%);
            box-shadow: 0 16px 32px rgba(101, 117, 255, 0.24);
            transition: transform 0.18s ease, box-shadow 0.18s ease, filter 0.18s ease;
        }

        div[data-testid="stButton"] > button:hover,
        div[data-testid="stFormSubmitButton"] > button:hover {
            transform: translateY(-1px);
            filter: brightness(1.02);
            box-shadow: 0 18px 34px rgba(101, 117, 255, 0.28);
        }

        div[data-baseweb="tab-list"] {
            gap: 0.45rem;
        }

        button[data-baseweb="tab"] {
            height: 46px;
            padding: 0 1rem;
            border-radius: 14px;
            background: rgba(255, 255, 255, 0.72);
            border: 1px solid rgba(143, 124, 255, 0.12);
        }

        button[data-baseweb="tab"][aria-selected="true"] {
            background: linear-gradient(135deg, rgba(143, 124, 255, 0.16), rgba(101, 181, 255, 0.16));
            color: #30215c;
            border-color: rgba(143, 124, 255, 0.26);
        }

        div[data-baseweb="tab-highlight"] {
            display: none;
        }

        @media (max-width: 960px) {
            .overview-grid,
            .empty-grid,
            .stage-strip {
                grid-template-columns: 1fr;
            }
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
        "celebrated_task_id": None,
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


def render_stage_timeline(current_status: str, history: list[str]) -> str:
    cards: list[str] = []
    for stage in STATUS_FLOW[:-1]:
        if stage == current_status:
            variant = "active"
        elif stage in history:
            variant = "done"
        else:
            variant = "pending"

        cards.append(
            f"""
            <div class="stage-pill {variant}">
                <div class="stage-title">{html.escape(friendly_status(stage))}</div>
                <div class="stage-note">{html.escape(STATUS_COPY[stage])}</div>
            </div>
            """
        )

    return f"<div class='stage-strip'>{''.join(cards)}</div>"


def render_header() -> None:
    st.markdown(
        """
        <div class="hero-shell">
            <div class="hero-kicker">Multimodal Vision RAG • Agentic Fact-Checking</div>
            <h1 style="margin:0.85rem 0 0;">🦄 Autonomous Paper Reviewer</h1>
            <p class="hero-copy">
                Upload a research paper and let the pipeline parse text, inspect figures, retrieve evidence,
                fact-check against ArXiv, and produce a polished reviewer-style report.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_overview_cards() -> None:
    document_id = st.session_state.document_id or "No document yet"
    task_id = st.session_state.task_id or "No task yet"
    focus_count = len(st.session_state.focus_areas or [])
    current_state = friendly_status(st.session_state.review_status)

    st.markdown(
        f"""
        <div class="overview-grid">
            <div class="overview-card">
                <div class="overview-label">Document</div>
                <div class="overview-value">{html.escape(str(document_id))}</div>
            </div>
            <div class="overview-card">
                <div class="overview-label">Task</div>
                <div class="overview-value">{html.escape(str(task_id))}</div>
            </div>
            <div class="overview-card">
                <div class="overview-label">Focus Areas</div>
                <div class="overview-value">{focus_count}</div>
            </div>
            <div class="overview-card">
                <div class="overview-label">Pipeline State</div>
                <div class="overview-value">{html.escape(current_state)}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_idle_state() -> None:
    st.markdown(
        """
        <div class="glass-card">
            <h3 style="margin-top:0;">Review cockpit is standing by</h3>
            <p style="margin-bottom:0; color:var(--muted); line-height:1.72;">
                Launch a review from the sidebar to watch the full multimodal pipeline in real time.
            </p>
        </div>
        <div class="empty-grid">
            <div class="empty-card">
                <h4>📄 Upload once</h4>
                <p>Drop in a PDF from the sidebar and kick off a fully asynchronous backend workflow.</p>
            </div>
            <div class="empty-card">
                <h4>🧠 Review with context</h4>
                <p>The system blends parsed paper text, linked figures, tables, and retrieved evidence.</p>
            </div>
            <div class="empty-card">
                <h4>🌐 Fact-check externally</h4>
                <p>The reviewer can query ArXiv before writing the final structured report.</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_result_hero(result: dict[str, Any]) -> None:
    st.markdown(
        f"""
        <div class="result-hero">
            <div style="font-size:0.76rem; letter-spacing:0.12em; text-transform:uppercase; color:#6c74a4; margin-bottom:0.55rem;">
                Final Verdict Snapshot
            </div>
            <p class="summary-copy">{format_text(result.get("summary") or "No summary returned.")}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_results(payload: dict[str, Any]) -> None:
    result = payload.get("result_json") or {}
    review_data = result
    if st.session_state.task_id and st.session_state.celebrated_task_id != st.session_state.task_id:
        st.balloons()
        st.session_state.celebrated_task_id = st.session_state.task_id

    render_result_hero(result)

    summary_tab, strengths_tab, weaknesses_tab, questions_tab, arxiv_tab = st.tabs(
        ["📝 Summary", "💡 Strengths", "🎯 Weaknesses", "❓ Questions", "🌐 ArXiv Fact-Check"]
    )

    with summary_tab:
        st.info(result.get("summary") or "No summary returned.")
        if st.session_state.focus_areas:
            st.markdown("#### Focus Areas")
            render_focus_pills(st.session_state.focus_areas)
        st.caption("The report below is generated from document evidence, linked visuals, and optional external references.")

    with strengths_tab:
        strengths = list(result.get("strengths") or [])
        if strengths:
            for item in strengths:
                st.success(item)
        else:
            st.info("No strengths were captured for this review.")

    with weaknesses_tab:
        weaknesses = list(result.get("weaknesses") or [])
        if weaknesses:
            for item in weaknesses:
                st.warning(item)
        else:
            st.success("No explicit weaknesses were recorded.")

    with questions_tab:
        questions = list(result.get("questions_for_authors") or [])
        missing_evidence = list(result.get("missing_evidence") or [])

        st.markdown("#### Questions for the authors")
        if questions:
            for item in questions:
                st.info(item)
        else:
            st.success("No follow-up questions were needed for this run.")

        st.markdown("#### Missing evidence or unclear claims")
        if missing_evidence:
            for item in missing_evidence:
                st.warning(item)
        else:
            st.success("The reviewer did not flag additional evidence gaps.")

    with arxiv_tab:
        code_check = review_data.get("code_reproducibility_check")
        if code_check:
            st.markdown("### 💻 Code Reproducibility & Health")
            if "Tool Error" in code_check or "WARNING" in code_check:
                st.warning(code_check, icon="⚠️")
            elif "No public code repository" in code_check:
                st.caption("No open-source repository was detected or verified in this paper.")
            else:
                st.info(code_check, icon="✅")

        references = list(result.get("external_references_checked") or [])
        if code_check and references:
            st.markdown("### 🌐 External References Checked")
        if not references:
            st.info("No external ArXiv references were pulled for this review.")
        else:
            for reference in references:
                title = format_text(reference.get("title") or "Untitled reference")
                authors = ", ".join(reference.get("authors") or []) or "Authors unavailable"
                published_date = reference.get("published_date") or "Publication date unavailable"
                summary = format_text(reference.get("summary") or "No summary available.")
                citation_count = reference.get("citation_count")
                influential_citation_count = reference.get("influential_citation_count")
                citation_meta = ""
                if citation_count is not None or influential_citation_count is not None:
                    citation_parts: list[str] = []
                    if citation_count is not None:
                        citation_parts.append(
                            f"📈 <strong>Citations:</strong> {format_text(citation_count)}"
                        )
                    if influential_citation_count is not None:
                        citation_parts.append(
                            f"🔥 <strong>Influential:</strong> {format_text(influential_citation_count)}"
                        )
                    citation_meta = (
                        f"<div class=\"reference-meta\">{' | '.join(citation_parts)}</div>"
                    )
                st.markdown(
                    f"""
                    <div class="reference-card">
                        <div class="reference-title">{title}</div>
                        <div class="reference-meta"><strong>Authors</strong>: {format_text(authors)}</div>
                        <div class="reference-meta"><strong>Published</strong>: {format_text(published_date)}</div>
                        {citation_meta}
                        <blockquote>{summary}</blockquote>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("## Launch a Review")
        st.markdown(
            "Upload your PDF and let our Multi-Agent Vision RAG pipeline do the heavy lifting."
        )
        st.markdown(
            """
            <div class="glass-card" style="padding:0.95rem 1rem; margin-bottom:0.9rem;">
                <div style="font-size:0.76rem; letter-spacing:0.1em; text-transform:uppercase; color:#6c74a4; margin-bottom:0.45rem;">
                    What happens next
                </div>
                <p style="margin:0; line-height:1.65; color:#5f6f8e;">
                    We parse the PDF, extract images and tables, retrieve evidence, optionally check ArXiv,
                    and generate a structured reviewer-style report.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.form("launch-review-form"):
            uploaded_file = st.file_uploader(
                "Paper PDF",
                type=["pdf"],
                help="Upload the research paper you want the review pipeline to analyze.",
            )
            focus_input = st.text_input(
                "Focus Areas",
                placeholder="novelty, baselines, limitations, methodology",
                help="Comma-separated topics to emphasize during the review.",
            )
            submitted = st.form_submit_button("Start Review", use_container_width=True)

        if submitted:
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
                    st.session_state.celebrated_task_id = None
                    st.success("Review task submitted. Head to the main panel to watch it work.")

        st.divider()
        st.markdown("### Current focus")
        render_focus_pills(st.session_state.focus_areas)
        st.caption(
            "Tip: great prompts include novelty, experimental design, ablations, statistical rigor, or limitations."
        )


def poll_review(task_id: str) -> None:
    result_placeholder = st.empty()

    with st.status("🚀 Processing Document...", expanded=True) as status:
        meta_placeholder = st.empty()
        progress_placeholder = st.empty()
        stage_placeholder = st.empty()
        copy_placeholder = st.empty()

        while True:
            try:
                response = requests.get(
                    f"{API_BASE_URL}/api/v1/reviews/{task_id}",
                    timeout=30,
                )
            except requests.RequestException as exc:
                st.session_state.error_message = f"Polling failed: {exc}"
                st.session_state.review_status = "FAILED"
                status.update(label="⚠️ Polling failed", state="error", expanded=True)
                with result_placeholder.container():
                    st.error(st.session_state.error_message)
                break

            if not response.ok:
                st.session_state.error_message = extract_error_message(response)
                st.session_state.review_status = "FAILED"
                status.update(label="⚠️ Review interrupted", state="error", expanded=True)
                with result_placeholder.container():
                    st.error(st.session_state.error_message)
                break

            payload = response.json()
            current_status = str(payload.get("status"))
            st.session_state.review_status = current_status
            st.session_state.review_result = payload.get("result_json")
            st.session_state.error_message = payload.get("error_message")
            st.session_state.retry_count = payload.get("retry_count")

            if not st.session_state.status_history or st.session_state.status_history[-1] != current_status:
                st.session_state.status_history.append(current_status)

            state = "running"
            expanded = True
            if current_status == "COMPLETED":
                state = "complete"
                expanded = False
            elif current_status == "FAILED":
                state = "error"

            status.update(
                label=STATUS_LABELS.get(current_status, "🚀 Processing Document..."),
                state=state,
                expanded=expanded,
            )

            copy_placeholder.markdown(
                f"""
                <div class="glass-card" style="padding:0.95rem 1rem; margin-top:0.25rem;">
                    <div style="font-size:0.76rem; text-transform:uppercase; letter-spacing:0.1em; color:#6c74a4; margin-bottom:0.35rem;">
                        Live Pipeline Note
                    </div>
                    <div style="color:#31405d; line-height:1.68;">
                        {html.escape(STATUS_COPY.get(current_status, "Working through the review pipeline."))}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            meta_placeholder.markdown(
                f"""
                <div class="overview-grid" style="margin:0.35rem 0 0.6rem;">
                    <div class="overview-card">
                        <div class="overview-label">Task ID</div>
                        <div class="overview-value">{html.escape(task_id)}</div>
                    </div>
                    <div class="overview-card">
                        <div class="overview-label">Document ID</div>
                        <div class="overview-value">{html.escape(str(st.session_state.document_id or "Pending"))}</div>
                    </div>
                    <div class="overview-card">
                        <div class="overview-label">Retry Count</div>
                        <div class="overview-value">{st.session_state.retry_count or 0}</div>
                    </div>
                    <div class="overview-card">
                        <div class="overview-label">State</div>
                        <div class="overview-value">{html.escape(friendly_status(current_status))}</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            progress_placeholder.progress(
                progress_for_status(current_status, st.session_state.status_history),
                text=f"Pipeline state: {friendly_status(current_status)}",
            )
            stage_placeholder.markdown(
                render_stage_timeline(current_status, st.session_state.status_history),
                unsafe_allow_html=True,
            )

            if current_status == "COMPLETED":
                status.update(label="✨ Review Completed!", state="complete", expanded=False)
                with result_placeholder.container():
                    render_results(payload)
                break

            if current_status == "FAILED":
                status.update(label="⚠️ Review interrupted", state="error", expanded=True)
                with result_placeholder.container():
                    st.error(st.session_state.error_message or "The review pipeline failed.")
                break

            time.sleep(POLL_INTERVAL_SECONDS)


def render_terminal_state() -> None:
    current_status = st.session_state.review_status or "FAILED"
    expanded = current_status != "COMPLETED"
    state = "complete" if current_status == "COMPLETED" else "error"

    with st.status(STATUS_LABELS.get(current_status, friendly_status(current_status)), expanded=expanded) as status:
        status.update(
            label=STATUS_LABELS.get(current_status, friendly_status(current_status)),
            state=state,
            expanded=expanded,
        )
        st.markdown(
            f"""
            <div class="overview-grid" style="margin:0.35rem 0 0.6rem;">
                <div class="overview-card">
                    <div class="overview-label">Task ID</div>
                    <div class="overview-value">{html.escape(str(st.session_state.task_id or "Pending"))}</div>
                </div>
                <div class="overview-card">
                    <div class="overview-label">Document ID</div>
                    <div class="overview-value">{html.escape(str(st.session_state.document_id or "Pending"))}</div>
                </div>
                <div class="overview-card">
                    <div class="overview-label">Retry Count</div>
                    <div class="overview-value">{st.session_state.retry_count or 0}</div>
                </div>
                <div class="overview-card">
                    <div class="overview-label">State</div>
                    <div class="overview-value">{html.escape(friendly_status(current_status))}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.progress(
            progress_for_status(current_status, st.session_state.status_history),
            text=f"Pipeline state: {friendly_status(current_status)}",
        )
        st.markdown(
            render_stage_timeline(current_status, st.session_state.status_history),
            unsafe_allow_html=True,
        )

    if current_status == "COMPLETED":
        render_results({"result_json": st.session_state.review_result or {}})
    else:
        st.error(st.session_state.error_message or "The review pipeline failed.")


def render_existing_state() -> None:
    if not st.session_state.task_id:
        render_idle_state()
        return

    if st.session_state.review_status not in TERMINAL_STATUSES:
        poll_review(st.session_state.task_id)
        return

    render_terminal_state()


def main() -> None:
    st.set_page_config(
        page_title="Agentic Paper Reviewer",
        page_icon="🦄",
        layout="wide",
    )
    inject_styles()
    init_session_state()
    render_sidebar()

    st.markdown("# 🦄 Autonomous Paper Reviewer")
    render_header()
    render_overview_cards()
    render_existing_state()


if __name__ == "__main__":
    main()

"""
AI GitHub Repository Analyzer — Streamlit frontend.

This file only builds the UI layer. Every piece of real work
(fetching the repo, indexing it in ChromaDB, calling Gemini) is
delegated to the existing backend modules in ``backend/``:

    backend/main.py       -> get_repository_files, get_file_content
    backend/rag.py         -> add_documents, search_repository (via rag_chat),
                               clear_repository, get_repository_stats
    backend/analyzer.py    -> analyze_repository
    backend/rag_chat.py    -> ask_repository

Run from the project root with:

    streamlit run frontend/app.py
"""

from __future__ import annotations

import os
import re
import sys
import traceback
from pathlib import Path

import streamlit as st

# ============================================================
# PATH SETUP
# ============================================================
# This file lives at <project_root>/frontend/app.py. Streamlit can
# be launched from any working directory, so we resolve paths from
# __file__ rather than assuming the current working directory, and
# make sure both the project root (for the .env file) and the
# backend/ folder (for imports) are always on sys.path.

FRONTEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = FRONTEND_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Load environment variables from whichever location actually has
# them (project root or backend/) *before* importing the backend
# modules. analyzer.py also calls load_dotenv() itself, but
# load_dotenv() never overrides a variable that is already set, so
# doing it here first just makes the app robust to either .env
# location without touching backend code.
from dotenv import load_dotenv  # noqa: E402

for _candidate in (PROJECT_ROOT / ".env", BACKEND_DIR / ".env"):
    if _candidate.exists():
        load_dotenv(dotenv_path=_candidate)

# ============================================================
# PAGE CONFIG (must run before any other st.* call)
# ============================================================

st.set_page_config(
    page_title="AI GitHub Repository Analyzer",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# IMPORT BACKEND (with a friendly error instead of a crash)
# ============================================================

BACKEND_IMPORT_ERROR: str | None = None

try:
    from main import get_repository_files, get_file_content  # type: ignore
    from rag import add_documents, clear_repository, get_repository_stats  # type: ignore
    from analyzer import analyze_repository  # type: ignore
    from rag_chat import ask_repository  # type: ignore
except Exception as error:  # noqa: BLE001 - surface any import failure to the UI
    BACKEND_IMPORT_ERROR = str(error)


# ============================================================
# STYLE
# ============================================================

st.markdown(
    """
    <style>
        .main > div { padding-top: 1.5rem; }
        h1, h2, h3 { font-weight: 700; }
        .app-subtitle {
            color: var(--text-color-secondary, #8a8f98);
            font-size: 1.05rem;
            margin-top: -0.6rem;
            margin-bottom: 1.4rem;
        }
        .section-card {
            border: 1px solid rgba(128,128,128,0.25);
            border-radius: 12px;
            padding: 1.1rem 1.3rem;
            margin-bottom: 0.9rem;
            background: rgba(128,128,128,0.04);
        }
        .status-pill {
            display: inline-block;
            padding: 0.15rem 0.7rem;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 600;
            background: rgba(46, 160, 67, 0.15);
            color: #2ea043;
            border: 1px solid rgba(46, 160, 67, 0.35);
        }
        code { word-break: break-word; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# SESSION STATE
# ============================================================

defaults = {
    "analysis_text": None,
    "analyzed_repo_url": None,
    "files_found": 0,
    "files_read": 0,
    "chunk_count": 0,
    "chat_history": [],  # list[tuple[str, str]] -> (question, answer)
    "repo_ready": False,
}
for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ============================================================
# HEADER
# ============================================================

st.title("🧠 AI GitHub Repository Analyzer")
st.markdown(
    '<div class="app-subtitle">Point it at any public GitHub repository and get an '
    "AI-generated architecture review, then chat with your codebase using retrieval-"
    "augmented search over the indexed source.</div>",
    unsafe_allow_html=True,
)

if BACKEND_IMPORT_ERROR:
    st.error(
        "The backend could not be loaded, so this app can't do any real work yet.\n\n"
        f"**Import error:** {BACKEND_IMPORT_ERROR}\n\n"
        "Common causes: `GEMINI_API_KEY` is missing from your `.env` file, or a "
        "backend dependency isn't installed (see `backend/requirement.txt`)."
    )
    st.stop()


# ============================================================
# SIDEBAR — REPOSITORY INDEX STATUS
# ============================================================

with st.sidebar:
    st.header("📚 Repository Index")

    try:
        stats = get_repository_stats()
        st.metric("Indexed chunks", stats.get("documents", 0))
        st.caption(f"ChromaDB collection: `{stats.get('collection', '-')}`")
        st.caption(f"Storage path: `{stats.get('chroma_path', '-')}`")
    except Exception as error:  # noqa: BLE001
        st.warning(f"Could not read index stats: {error}")

    st.divider()

    if st.button("🗑️ Clear indexed repository", use_container_width=True):
        try:
            clear_repository()
            st.session_state.repo_ready = False
            st.session_state.analysis_text = None
            st.session_state.analyzed_repo_url = None
            st.session_state.chat_history = []
            st.success("Repository index cleared.")
            st.rerun()
        except Exception as error:  # noqa: BLE001
            st.error(f"Could not clear the index: {error}")

    st.divider()
    st.caption(
        "This app calls your existing `backend/` code directly — repository "
        "fetching, chunking/embedding into ChromaDB, and every Gemini call all "
        "happen in `main.py`, `rag.py`, `analyzer.py`, and `rag_chat.py`."
    )


# ============================================================
# HELPERS
# ============================================================

SECTION_HEADING_RE = re.compile(
    r"^\s{0,3}(?:#{1,3}\s*)?(\d{1,2})[.)]\s+([A-Za-z0-9 /&+\-]{3,60})\s*$"
)


def split_analysis_into_sections(analysis_text: str) -> list[tuple[str, str]]:
    """
    Best-effort split of the raw Gemini analysis text into
    (heading, body) sections based on the numbered headings the
    analyzer prompt asks Gemini to use (e.g. "1. PROJECT OVERVIEW").

    This never fabricates or reorders content — it only groups the
    model's own output under its own headings. If no headings are
    detected, the whole text is returned as a single section so
    nothing is ever hidden.
    """

    lines = analysis_text.splitlines()
    sections: list[tuple[str, list[str]]] = []
    current_heading = None
    current_body: list[str] = []

    for line in lines:
        match = SECTION_HEADING_RE.match(line)
        if match:
            if current_heading is not None:
                sections.append((current_heading, current_body))
            current_heading = match.group(2).strip().title()
            current_body = []
        else:
            current_body.append(line)

    if current_heading is not None:
        sections.append((current_heading, current_body))

    if not sections:
        return [("Full Analysis", analysis_text.strip())]

    # Anything before the first detected heading (if non-empty) is
    # kept as an "Overview" preamble instead of being dropped.
    result = [(heading, "\n".join(body).strip()) for heading, body in sections]
    return [(h, b) for h, b in result if b]


def run_repository_analysis(repo_url: str) -> None:
    """Drive the full analyze pipeline using only backend functions."""

    progress = st.progress(0, text="Starting…")
    status = st.empty()

    try:
        # STEP 1 — discover files
        status.info("🔎 Finding useful files in the repository…")
        progress.progress(10, text="Listing repository files…")
        files = get_repository_files(repo_url)

        if not files:
            progress.empty()
            status.empty()
            st.error(
                "No supported files were found in this repository. It may be "
                "empty, private, or contain only ignored/binary file types."
            )
            return

        st.session_state.files_found = len(files)

        # STEP 2 — read file contents
        status.info(f"📥 Reading {len(files)} files from GitHub…")
        files_content: dict[str, str] = {}
        failed_files: list[str] = []

        for index, file_path in enumerate(files):
            try:
                content = get_file_content(repo_url, file_path)
                if content:
                    files_content[file_path] = content
            except Exception:  # noqa: BLE001
                failed_files.append(file_path)

            pct = 10 + int(40 * (index + 1) / len(files))
            progress.progress(pct, text=f"Reading {file_path}")

        if not files_content:
            progress.empty()
            status.empty()
            st.error("Could not read any file contents from this repository.")
            return

        st.session_state.files_read = len(files_content)

        # STEP 3 — index into ChromaDB via the existing RAG module
        status.info("🧩 Indexing repository content into ChromaDB…")
        progress.progress(60, text="Chunking + embedding content…")
        chunk_count = add_documents(files_content)

        if not chunk_count:
            progress.empty()
            status.empty()
            st.error("Indexing produced no chunks — nothing to analyze or search.")
            return

        st.session_state.chunk_count = chunk_count

        # STEP 4 — Gemini analysis
        status.info("🤖 Sending repository to Gemini for analysis…")
        progress.progress(80, text="Running AI analysis…")
        analysis_text = analyze_repository(files_content)

        progress.progress(100, text="Done.")
        status.empty()
        progress.empty()

        st.session_state.analysis_text = analysis_text
        st.session_state.analyzed_repo_url = repo_url
        st.session_state.repo_ready = True
        st.session_state.chat_history = []

        success_msg = (
            f"Analyzed **{len(files_content)}** files "
            f"({chunk_count} chunks indexed)."
        )
        if failed_files:
            success_msg += f" {len(failed_files)} file(s) could not be read and were skipped."
        st.success(success_msg)

    except ConnectionError as error:
        progress.empty()
        status.empty()
        st.error(f"Network error while contacting GitHub: {error}")
    except ValueError as error:
        progress.empty()
        status.empty()
        st.error(str(error))
    except RuntimeError as error:
        progress.empty()
        status.empty()
        st.error(f"Gemini analysis failed: {error}")
    except Exception as error:  # noqa: BLE001
        progress.empty()
        status.empty()
        st.error(f"Unexpected error: {error}")
        with st.expander("Technical details"):
            st.code(traceback.format_exc())


# ============================================================
# REPOSITORY INPUT
# ============================================================

st.subheader("🔗 Analyze a repository")

col_input, col_button = st.columns([4, 1], vertical_alignment="bottom")

with col_input:
    repo_url = st.text_input(
        "Public GitHub repository URL",
        placeholder="https://github.com/owner/repository",
        label_visibility="collapsed",
    )

with col_button:
    analyze_clicked = st.button("Analyze Repository", type="primary", use_container_width=True)

if analyze_clicked:
    cleaned_url = (repo_url or "").strip()
    if not cleaned_url:
        st.error("Please enter a GitHub repository URL.")
    elif "github.com" not in cleaned_url.lower():
        st.error("Please provide a valid GitHub repository URL (github.com/owner/repo).")
    else:
        run_repository_analysis(cleaned_url)


# ============================================================
# ANALYSIS RESULTS
# ============================================================

if st.session_state.analysis_text:
    st.divider()
    st.subheader("📊 Repository Analysis")

    m1, m2, m3 = st.columns(3)
    m1.metric("Files analyzed", st.session_state.files_read or st.session_state.files_found)
    m2.metric("Chunks indexed", st.session_state.chunk_count)
    m3.markdown(
        f"**Repository**\n\n`{st.session_state.analyzed_repo_url}`"
    )

    sections = split_analysis_into_sections(st.session_state.analysis_text)

    if len(sections) > 1:
        tabs = st.tabs([heading for heading, _ in sections])
        for tab, (_, body) in zip(tabs, sections):
            with tab:
                st.markdown(body)
    else:
        with st.expander("Full analysis", expanded=True):
            st.markdown(sections[0][1])

    with st.expander("View raw analysis text"):
        st.markdown(st.session_state.analysis_text)


# ============================================================
# REPOSITORY CHAT (RAG)
# ============================================================

st.divider()
st.subheader("💬 Ask anything about this repository")

if not st.session_state.repo_ready:
    st.info(
        "Analyze a repository above first — the chat answers questions using "
        "the ChromaDB index built during analysis, via `rag_chat.ask_repository`."
    )
else:
    for question, answer in st.session_state.chat_history:
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            st.markdown(answer)

    user_question = st.chat_input("How does the RAG system work?")

    if user_question:
        with st.chat_message("user"):
            st.markdown(user_question)

        with st.chat_message("assistant"):
            with st.spinner("Searching the indexed repository…"):
                try:
                    answer = ask_repository(user_question)
                except Exception as error:  # noqa: BLE001
                    answer = f"⚠️ Error answering question: {error}"
            st.markdown(answer)

        st.session_state.chat_history.append((user_question, answer))

"""
AI GitHub Repository Analyzer - Premium Glassmorphism Streamlit Application.

Features:
- Glassmorphic dark UI design with customizable themes
- Real-time repository ingestion & ChromaDB vector indexing
- Groq-powered multi-stage architectural & security audit
- Filterable & searchable findings with expandable evidence cards
- Interactive RAG Code Explorer with hybrid retrieval
- Grounded AI Repository Chat with citation evidence
- Automated Patch Generation & Verification Workflow
- API Settings & Token Usage Telemetry
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

import streamlit as st

# Ensure backend modules can be imported
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from dotenv import load_dotenv
load_dotenv()
backend_env = os.path.join(BACKEND_DIR, ".env")
if os.path.exists(backend_env):
    load_dotenv(backend_env)

# Import backend services
try:
    from llm_service import llm_service, redact_secrets
    from main import (
        get_repository_metadata,
        get_repository_files,
        get_file_content,
        parse_repository_url,
    )
    from rag import RepositoryRAG, sanitize_collection_name
    from analyzer import analyze_repository
except ImportError as err:
    st.error(f"Failed to load backend modules: {err}")
    st.stop()


# ============================================================
# STREAMLIT PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="AI GitHub Repository Analyzer",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# GLASSMORPHISM CUSTOM DESIGN SYSTEM (CSS)
# ============================================================

GLASS_CSS = """
<style>
/* Global Dark Surface Palette */
:root {
    --bg-dark: #090D16;
    --surface-glass: rgba(18, 24, 38, 0.7);
    --surface-glass-border: rgba(255, 255, 255, 0.08);
    --surface-glass-hover: rgba(28, 36, 56, 0.85);
    --accent-indigo: #6366F1;
    --accent-cyan: #06B6D4;
    --accent-glow: rgba(99, 102, 241, 0.25);
    --text-primary: #F3F4F6;
    --text-secondary: #9CA3AF;
    --card-radius: 14px;
}

/* Background & Body */
.stApp {
    background-color: var(--bg-dark);
    background-image: 
        radial-gradient(at 0% 0%, rgba(99, 102, 241, 0.12) 0px, transparent 50%),
        radial-gradient(at 100% 100%, rgba(6, 182, 212, 0.08) 0px, transparent 50%);
    color: var(--text-primary);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
}

/* Glassmorphism Card Containers */
.glass-card {
    background: var(--surface-glass);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border: 1px solid var(--surface-glass-border);
    border-radius: var(--card-radius);
    padding: 24px;
    margin-bottom: 20px;
    box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
    transition: transform 0.2s ease, border-color 0.2s ease;
}

.glass-card:hover {
    border-color: rgba(99, 102, 241, 0.3);
}

.glass-metric {
    background: rgba(25, 33, 50, 0.55);
    backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 12px;
    padding: 16px 20px;
    text-align: left;
}

.glass-metric .metric-val {
    font-size: 28px;
    font-weight: 700;
    color: #FFFFFF;
    margin-top: 4px;
}

.glass-metric .metric-lbl {
    font-size: 13px;
    font-weight: 500;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

/* Severity Badges */
.badge {
    display: inline-block;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: 700;
    border-radius: 6px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}
.badge-critical { background: rgba(239, 68, 68, 0.2); color: #F87171; border: 1px solid rgba(239, 68, 68, 0.4); }
.badge-high { background: rgba(245, 158, 11, 0.2); color: #FBBF24; border: 1px solid rgba(245, 158, 11, 0.4); }
.badge-medium { background: rgba(234, 179, 8, 0.2); color: #FDE047; border: 1px solid rgba(234, 179, 8, 0.4); }
.badge-low { background: rgba(99, 102, 241, 0.2); color: #A5B4FC; border: 1px solid rgba(99, 102, 241, 0.4); }
.badge-info { background: rgba(6, 182, 212, 0.2); color: #67E8F9; border: 1px solid rgba(6, 182, 212, 0.4); }

/* Header Branding */
.hero-title {
    font-size: 32px;
    font-weight: 800;
    background: linear-gradient(135deg, #FFFFFF 0%, #A5B4FC 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 4px;
}

.hero-subtitle {
    font-size: 15px;
    color: var(--text-secondary);
    margin-bottom: 24px;
}

/* Custom Scrollbars */
::-webkit-scrollbar {
    width: 6px;
    height: 6px;
}
::-webkit-scrollbar-track {
    background: rgba(0, 0, 0, 0.2);
}
::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.15);
    border-radius: 4px;
}
::-webkit-scrollbar-thumb:hover {
    background: rgba(99, 102, 241, 0.5);
}
</style>
"""
st.markdown(GLASS_CSS, unsafe_allow_html=True)


# ============================================================
# SESSION STATE INITIALIZATION
# ============================================================

if "current_repo" not in st.session_state:
    st.session_state.current_repo = None  # Dict of metadata
if "files_content" not in st.session_state:
    st.session_state.files_content = {}
if "rag_engine" not in st.session_state:
    st.session_state.rag_engine = None
if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "selected_model" not in st.session_state:
    st.session_state.selected_model = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")


# ============================================================
# SIDEBAR NAVIGATION & TELEMETRY
# ============================================================

with st.sidebar:
    st.markdown("### ⚡ AI Repo Analyzer")
    st.markdown("<p style='font-size:12px;color:#9CA3AF;'>Powered by Groq LPU & ChromaDB</p>", unsafe_allow_html=True)
    st.divider()

    navigation = st.radio(
        "Navigation",
        [
            "📊 Overview",
            "🚀 Repository Analysis",
            "📋 Audit Report",
            "🔍 RAG Code Explorer",
            "💬 AI Assistant",
            "⚙️ API & Settings",
        ],
        index=0,
    )

    st.divider()

    # Active Repo Info
    if st.session_state.current_repo:
        meta = st.session_state.current_repo
        st.markdown(f"**Current Repo:** `{meta['full_name']}`")
        st.markdown(f"⭐ {meta['stars']} | 🍴 {meta['forks']} | 🌿 `{meta['default_branch']}`")
        st.markdown(f"📁 **Files Ingested:** {len(st.session_state.files_content)}")
        if st.session_state.rag_engine:
            st.markdown(f"🧩 **Indexed Chunks:** {st.session_state.rag_engine.count_chunks()}")
    else:
        st.info("No repository analyzed yet.")

    st.divider()

    # Groq Status Pill
    is_groq_ready = llm_service.is_configured()
    if is_groq_ready:
        st.success(f"🟢 Groq Connected\n`{st.session_state.selected_model}`")
    else:
        st.error("🔴 GROQ_API_KEY Missing")


# ============================================================
# PAGE 1: OVERVIEW
# ============================================================

if navigation == "📊 Overview":
    st.markdown('<div class="hero-title">Developer Intelligence Dashboard</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-subtitle">High-velocity code audits, RAG-grounded exploration, and automated repair powered by Groq LPUs.</div>', unsafe_allow_html=True)

    # Top KPI Cards
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(
            f"""<div class="glass-metric">
                <div class="metric-lbl">Active Model</div>
                <div class="metric-val" style="font-size:18px;">{st.session_state.selected_model.split('/')[-1]}</div>
            </div>""",
            unsafe_allow_html=True,
        )
    with col2:
        file_cnt = len(st.session_state.files_content)
        st.markdown(
            f"""<div class="glass-metric">
                <div class="metric-lbl">Ingested Files</div>
                <div class="metric-val">{file_cnt}</div>
            </div>""",
            unsafe_allow_html=True,
        )
    with col3:
        chunk_cnt = st.session_state.rag_engine.count_chunks() if st.session_state.rag_engine else 0
        st.markdown(
            f"""<div class="glass-metric">
                <div class="metric-lbl">Indexed Chunks</div>
                <div class="metric-val">{chunk_cnt}</div>
            </div>""",
            unsafe_allow_html=True,
        )
    with col4:
        score_val = (
            f"{st.session_state.analysis_result.get('overall_score', 0):.1f}/10"
            if st.session_state.analysis_result
            else "N/A"
        )
        st.markdown(
            f"""<div class="glass-metric">
                <div class="metric-lbl">Health Score</div>
                <div class="metric-val">{score_val}</div>
            </div>""",
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # Quick Analyze Input Card
    with st.container():
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.subheader("⚡ Quick Ingestion")
        quick_url = st.text_input(
            "Enter public GitHub repository URL",
            placeholder="e.g., https://github.com/psf/requests or pallets/flask",
            key="quick_repo_input",
        )
        col_btn, col_hint = st.columns([1, 4])
        with col_btn:
            if st.button("Start Audit", type="primary", use_container_width=True):
                if quick_url:
                    st.session_state.target_repo_url = quick_url
                    st.switch_page = "🚀 Repository Analysis"
                    st.info("Navigating to Repository Analysis...")
                else:
                    st.warning("Please enter a valid GitHub repository URL.")
        with col_hint:
            st.caption("Inspects architecture, detects security flaws, generates unified diff patches, and builds a private vector index.")
        st.markdown('</div>', unsafe_allow_html=True)

    # Latest Audit Summary Card (if available)
    if st.session_state.analysis_result:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.subheader("📋 Latest Analysis Highlights")
        findings = st.session_state.analysis_result.get("findings", [])
        c1, c2, c3, c4 = st.columns(4)
        crit = sum(1 for f in findings if f.get("severity") == "CRITICAL")
        high = sum(1 for f in findings if f.get("severity") == "HIGH")
        med = sum(1 for f in findings if f.get("severity") == "MEDIUM")
        low = sum(1 for f in findings if f.get("severity") in ("LOW", "INFO"))

        c1.metric("Critical Defects", crit)
        c2.metric("High Severity", high)
        c3.metric("Medium Risks", med)
        c4.metric("Low / Info", low)
        st.markdown('</div>', unsafe_allow_html=True)


# ============================================================
# PAGE 2: REPOSITORY ANALYSIS
# ============================================================

elif navigation == "🚀 Repository Analysis":
    st.markdown('<div class="hero-title">Ingest & Audit Repository</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-subtitle">Automated multi-stage extraction, code chunking, vector indexing, and Groq-powered evaluation.</div>', unsafe_allow_html=True)

    input_url = st.text_input(
        "GitHub Repository URL",
        value=st.session_state.get("target_repo_url", ""),
        placeholder="https://github.com/owner/repository",
    )

    col_analyze, col_cancel = st.columns([1, 5])
    start_analysis = col_analyze.button("Run Full Pipeline", type="primary", use_container_width=True)

    if start_analysis:
        if not input_url.strip():
            st.error("Please enter a valid GitHub repository URL.")
        elif not llm_service.is_configured():
            st.error("GROQ_API_KEY is not configured. Please add it to your .env file or Settings.")
        else:
            progress_bar = st.progress(0.0)
            status_box = st.empty()

            try:
                # Stage 1: Validation & Metadata
                status_box.markdown("**[Stage 1/5]** Validating repository and fetching GitHub metadata...")
                progress_bar.progress(0.15)
                meta = get_repository_metadata(input_url)
                st.session_state.current_repo = meta
                owner, repo = meta["owner"], meta["repo"]
                branch = meta["default_branch"]

                # Stage 2: File Discovery
                status_box.markdown(f"**[Stage 2/5]** Discovering files on branch `{branch}`...")
                progress_bar.progress(0.30)
                file_list = get_repository_files(input_url, branch=branch)
                if not file_list:
                    raise ValueError(f"No supported code files found in repository {owner}/{repo}.")

                # Stage 3: Content Ingestion
                status_box.markdown(f"**[Stage 3/5]** Ingesting content for {len(file_list)} files...")
                files_content: Dict[str, str] = {}
                for idx, fpath in enumerate(file_list):
                    try:
                        content = get_file_content(input_url, fpath, branch=branch)
                        if content and content.strip():
                            files_content[fpath] = content
                    except Exception:
                        pass
                    pct = 0.30 + (0.35 * ((idx + 1) / len(file_list)))
                    progress_bar.progress(pct)

                st.session_state.files_content = files_content

                # Stage 4: Isolated Vector Indexing
                status_box.markdown(f"**[Stage 4/5]** Building isolated ChromaDB vector index for `{owner}/{repo}`...")
                progress_bar.progress(0.75)
                rag_engine = RepositoryRAG(owner, repo)
                chunk_count = rag_engine.add_documents(files_content, clear_existing=True)
                st.session_state.rag_engine = rag_engine

                # Stage 5: Groq Deep Audit
                status_box.markdown(f"**[Stage 5/5]** Performing deep architectural and security audit with Groq (`{st.session_state.selected_model}`)...")
                progress_bar.progress(0.85)

                result = analyze_repository(
                    files_content=files_content,
                    repo_name=f"{owner}/{repo}",
                    model=st.session_state.selected_model,
                )
                st.session_state.analysis_result = result
                progress_bar.progress(1.0)
                status_box.success(f"✅ Audit complete! Indexed {chunk_count} chunks across {len(files_content)} files.")

            except Exception as exc:
                progress_bar.empty()
                status_box.error(f"❌ Analysis failed: {redact_secrets(str(exc))}")

    # Display Repository Overview Card if available
    if st.session_state.current_repo:
        meta = st.session_state.current_repo
        with st.container():
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
            with c1:
                st.markdown(f"### [{meta['full_name']}](https://github.com/{meta['full_name']})")
                st.markdown(f"*{meta['description']}*")
            with c2:
                st.metric("Primary Language", meta["language"])
            with c3:
                st.metric("GitHub Stars", f"{meta['stars']:,}")
            with c4:
                st.metric("Default Branch", meta["default_branch"])
            st.markdown('</div>', unsafe_allow_html=True)


# ============================================================
# PAGE 3: AUDIT REPORT & FINDINGS
# ============================================================

elif navigation == "📋 Audit Report":
    st.markdown('<div class="hero-title">Technical Audit & Defect Report</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-subtitle">Comprehensive findings, impact assessments, evidence citations, and automated patch suggestions.</div>', unsafe_allow_html=True)

    if not st.session_state.analysis_result:
        st.warning("No audit report has been generated yet. Please run an analysis first in '🚀 Repository Analysis'.")
    else:
        report = st.session_state.analysis_result
        findings = report.get("findings", [])

        # Export Controls
        col_dl_md, col_dl_json, _ = st.columns([1, 1, 3])
        with col_dl_md:
            st.download_button(
                "📥 Download Markdown Report",
                data=report["report_markdown"],
                file_name=f"audit_report_{st.session_state.current_repo['repo']}.md",
                mime="text/markdown",
                use_container_width=True,
            )
        with col_dl_json:
            st.download_button(
                "📥 Download Findings JSON",
                data=json.dumps(findings, indent=2),
                file_name=f"findings_{st.session_state.current_repo['repo']}.json",
                mime="application/json",
                use_container_width=True,
            )

        st.markdown("<br>", unsafe_allow_html=True)

        tab_findings, tab_full_report = st.tabs(["🔍 Verified Findings", "📄 Full Narrative Report"])

        with tab_findings:
            if not findings:
                st.info("No structured findings were parsed from the audit. You can view the full report in the next tab.")
            else:
                # Severity Filters & Search
                f_col1, f_col2 = st.columns([2, 1])
                with f_col1:
                    search_query = st.text_input("Filter findings by title, file, or keyword", placeholder="e.g., auth, rate limit, exception...")
                with f_col2:
                    severity_filter = st.selectbox(
                        "Severity Filter",
                        ["ALL", "CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"],
                        index=0,
                    )

                filtered_findings = findings
                if severity_filter != "ALL":
                    filtered_findings = [f for f in filtered_findings if f.get("severity", "").upper() == severity_filter]
                if search_query.strip():
                    q = search_query.lower()
                    filtered_findings = [
                        f for f in filtered_findings
                        if q in f.get("title", "").lower()
                        or q in f.get("file_path", "").lower()
                        or q in f.get("explanation", "").lower()
                    ]

                st.markdown(f"**Showing {len(filtered_findings)} of {len(findings)} findings**")

                for idx, item in enumerate(filtered_findings):
                    sev = item.get("severity", "MEDIUM").upper()
                    badge_class = f"badge-{sev.lower()}"
                    cat = item.get("category", "QUALITY")
                    file_p = item.get("file_path", "unknown")
                    line_ref = item.get("line_reference", "N/A")

                    card_title = f"[{sev}] {item.get('title', 'Untitled Finding')} — {file_p}"
                    with st.expander(card_title, expanded=(sev in ("CRITICAL", "HIGH"))):
                        st.markdown(
                            f"""<span class="badge {badge_class}">{sev}</span> 
                            <span class="badge badge-info">{cat}</span> 
                            <code>{file_p}:{line_ref}</code>""",
                            unsafe_allow_html=True,
                        )
                        st.markdown(f"**Explanation:** {item.get('explanation', '')}")
                        if item.get("evidence"):
                            st.markdown("**Evidence:**")
                            st.code(item.get("evidence"), language="python")
                        st.markdown(f"**Potential Impact:** {item.get('impact', 'N/A')}")
                        st.markdown(f"**Recommended Remediation:** {item.get('remediation', 'N/A')}")

                        # Safe Code Repair Section
                        st.divider()
                        patch_btn_key = f"patch_btn_{idx}_{item.get('id', idx)}"
                        if st.button("🛠️ Generate Proposed Patch", key=patch_btn_key):
                            with st.spinner("Generating targeted unified diff via Groq..."):
                                current_code = st.session_state.files_content.get(file_p, "")
                                patch_info = llm_service.suggest_patch(
                                    file_path=file_p,
                                    current_content=current_code,
                                    issue_description=f"{item.get('title')}: {item.get('explanation')}",
                                )
                                st.markdown("#### Proposed Fix Explanation")
                                st.write(patch_info["explanation"])
                                if patch_info.get("diff"):
                                    st.markdown("#### Unified Git Diff")
                                    st.code(patch_info["diff"], language="diff")
                                if patch_info.get("proposed_code"):
                                    st.markdown("#### Replacement Code")
                                    st.code(patch_info["proposed_code"], language="python")

        with tab_full_report:
            st.markdown(report["report_markdown"])


# ============================================================
# PAGE 4: RAG CODE EXPLORER
# ============================================================

elif navigation == "🔍 RAG Code Explorer":
    st.markdown('<div class="hero-title">RAG Codebase Explorer</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-subtitle">Hybrid semantic & lexical search across the isolated ChromaDB repository index.</div>', unsafe_allow_html=True)

    if not st.session_state.rag_engine or st.session_state.rag_engine.count_chunks() == 0:
        st.warning("Vector database is empty. Ingest a repository first in '🚀 Repository Analysis'.")
    else:
        rag = st.session_state.rag_engine
        q_col1, q_col2 = st.columns([3, 1])
        with q_col1:
            search_query = st.text_input("Enter natural language query or symbol", placeholder="e.g. rate limit error handling, database connection, authentication headers")
        with q_col2:
            top_k = st.slider("Top Results", min_value=3, max_value=15, value=6)

        if search_query.strip():
            with st.spinner("Executing hybrid retrieval..."):
                results = rag.search(search_query, n_results=top_k)

            if not results:
                st.info("No matching chunks found.")
            else:
                st.markdown(f"**Found {len(results)} relevant code chunks:**")
                for i, r in enumerate(results):
                    filename = r.get("filename", "unknown")
                    score = r.get("score", 0.0)
                    dist = r.get("distance", 1.0)
                    chunk_idx = r.get("chunk", 0)

                    with st.expander(f"[{i+1}] {filename} (Chunk {chunk_idx}) — Relevance: {score:.3f}"):
                        st.markdown(f"**File:** `{filename}` | **Distance:** `{dist}`")
                        # Format code snippet
                        clean_doc = r["document"].split("\n\n", 1)[-1] if "\n\n" in r["document"] else r["document"]
                        ext = os.path.splitext(filename)[1].lstrip(".") or "python"
                        st.code(clean_doc, language=ext)


# ============================================================
# PAGE 5: AI REPOSITORY CHAT
# ============================================================

elif navigation == "💬 AI Assistant":
    st.markdown('<div class="hero-title">Grounded AI Repository Assistant</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-subtitle">Chat with your indexed codebase. All answers are strictly grounded in retrieved evidence.</div>', unsafe_allow_html=True)

    if not st.session_state.rag_engine or st.session_state.rag_engine.count_chunks() == 0:
        st.warning("Please analyze a repository first to enable the Q&A Assistant.")
    else:
        # Prompt Chips
        st.markdown("**Suggested Questions:**")
        chip_cols = st.columns(4)
        q1 = chip_cols[0].button("🏛️ Explain Architecture")
        q2 = chip_cols[1].button("🔒 Detect Security Risks")
        q3 = chip_cols[2].button("⚡ Performance Bottlenecks")
        q4 = chip_cols[3].button("🚀 How do I run this?")

        prompt_to_submit = None
        if q1:
            prompt_to_submit = "Explain the system architecture and module data flow."
        elif q2:
            prompt_to_submit = "What are the most serious security concerns or sensitive data risks?"
        elif q3:
            prompt_to_submit = "Identify any potential performance bottlenecks or memory leaks."
        elif q4:
            prompt_to_submit = "How do I install, configure, and execute this project locally?"

        # Display Chat History
        for msg in st.session_state.chat_history:
            role = msg["role"]
            avatar = "🧑‍💻" if role == "user" else "⚡"
            with st.chat_message(role, avatar=avatar):
                st.markdown(msg["content"])
                if "sources" in msg and msg["sources"]:
                    with st.expander("📚 Cited Source Chunks"):
                        for s in msg["sources"]:
                            st.markdown(f"- `{s['filename']}` (chunk {s['chunk']}) — relevance: {s['score']}")

        # Chat Input
        user_input = st.chat_input("Ask any question about the codebase...")
        target_prompt = prompt_to_submit or user_input

        if target_prompt:
            # Render user message
            st.session_state.chat_history.append({"role": "user", "content": target_prompt})
            with st.chat_message("user", avatar="🧑‍💻"):
                st.markdown(target_prompt)

            # Generate grounded assistant response
            with st.chat_message("assistant", avatar="⚡"):
                with st.spinner("Searching repository chunks & querying Groq..."):
                    retrieved = st.session_state.rag_engine.search(target_prompt, n_results=6)
                    answer = llm_service.answer_repository_question(
                        question=target_prompt,
                        retrieved_chunks=retrieved,
                        conversation_history=st.session_state.chat_history,
                    )
                    st.markdown(answer)

                    sources = [
                        {
                            "filename": c.get("filename", "unknown"),
                            "chunk": c.get("chunk", 0),
                            "score": round(float(c.get("score", 0.0)), 3),
                        }
                        for c in retrieved
                    ]
                    if sources:
                        with st.expander("📚 Cited Source Chunks"):
                            for s in sources:
                                st.markdown(f"- `{s['filename']}` (chunk {s['chunk']}) — relevance: {s['score']}")

                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "content": answer,
                        "sources": sources,
                    })

        col_clr, _ = st.columns([1, 5])
        if col_clr.button("🗑️ Clear Chat History"):
            st.session_state.chat_history.clear()
            st.rerun()


# ============================================================
# PAGE 6: API & USAGE SETTINGS
# ============================================================

elif navigation == "⚙️ API & Settings":
    st.markdown('<div class="hero-title">API & Engine Configuration</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-subtitle">Telemetry, model selection, rate limit monitoring, and connection tests.</div>', unsafe_allow_html=True)

    # Groq Settings Card
    with st.container():
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.subheader("⚡ Groq Provider Configuration")

        is_connected, msg = llm_service.test_connection()
        if is_connected:
            st.success(f"Connection Status: {msg}")
        else:
            st.error(f"Connection Status: {msg}")

        # Model Selector
        available_models = llm_service.get_available_chat_models()
        current_idx = available_models.index(st.session_state.selected_model) if st.session_state.selected_model in available_models else 0
        new_model = st.selectbox(
            "Selected Groq Model",
            available_models,
            index=current_idx,
            help="High-capacity models like 'openai/gpt-oss-120b' or fast models like 'qwen/qwen3.8-27b'.",
        )
        if new_model != st.session_state.selected_model:
            st.session_state.selected_model = new_model
            st.success(f"Model updated to: {new_model}")

        st.markdown('</div>', unsafe_allow_html=True)

    # Token Usage Telemetry
    with st.container():
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.subheader("📊 Session Telemetry & Token Usage")
        stats = llm_service.stats
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("API Requests", stats.total_requests)
        m2.metric("Prompt Tokens", f"{stats.prompt_tokens:,}")
        m3.metric("Completion Tokens", f"{stats.completion_tokens:,}")
        m4.metric("Total Tokens", f"{stats.total_tokens:,}")

        if stats.recent_errors:
            st.markdown("#### Recent Provider Notices & Errors")
            for err in stats.recent_errors:
                st.code(err)
        st.markdown('</div>', unsafe_allow_html=True)

    # GitHub Rate Limits Card
    with st.container():
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.subheader("🐙 GitHub API Authorization Status")
        gh_token = os.getenv("GITHUB_TOKEN", "").strip()
        if gh_token:
            masked = gh_token[:4] + "..." + gh_token[-4:] if len(gh_token) > 8 else "***"
            st.success(f"GITHUB_TOKEN is active ({masked}). Quota: 5,000 requests/hour.")
        else:
            st.warning("No GITHUB_TOKEN configured. Unauthenticated requests are limited to 60 requests/hour per IP.")
        st.markdown('</div>', unsafe_allow_html=True)

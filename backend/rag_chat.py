from __future__ import annotations

from typing import Any

from analyzer import client, MODEL_NAME
from rag import search_repository


# ============================================================
# CONSTANTS
# ============================================================

NO_INFORMATION = (
    "I couldn't find that information in the indexed repository."
)

MAX_CONTEXT_CHARS = 50000
TOP_K_RESULTS = 10


# ============================================================
# SAFE HELPERS
# ============================================================

def _safe_metadata(
    metadatas: list[Any],
    index: int,
) -> dict[str, Any]:
    """
    Safely retrieve metadata for a result.
    """

    if index >= len(metadatas):
        return {}

    metadata = metadatas[index]

    if isinstance(metadata, dict):
        return metadata

    return {}


# ============================================================
# BUILD CONTEXT
# ============================================================

def _build_context(
    documents: list[Any],
    metadatas: list[Any],
    distances: list[Any],
) -> str:
    """
    Build a clean repository context for Gemini.
    """

    context_parts: list[str] = []
    total_chars = 0

    seen_chunks: set[str] = set()

    for index, document in enumerate(documents):

        if not document:
            continue

        document = str(document)

        metadata = _safe_metadata(
            metadatas,
            index,
        )

        filename = str(
            metadata.get(
                "filename",
                "Unknown file",
            )
        )

        chunk_number = metadata.get(
            "chunk",
            "?",
        )

        distance = (
            distances[index]
            if index < len(distances)
            else None
        )

        chunk_id = (
            f"{filename}:{chunk_number}"
        )

        if chunk_id in seen_chunks:
            continue

        seen_chunks.add(chunk_id)

        chunk_text = f"""
FILE: {filename}
CHUNK: {chunk_number}
RELEVANCE DISTANCE: {distance}

{document}
""".strip()

        if (
            total_chars
            + len(chunk_text)
            > MAX_CONTEXT_CHARS
        ):
            break

        context_parts.append(
            chunk_text
        )

        total_chars += len(chunk_text)

    if not context_parts:
        return ""

    return (
        "\n\n"
        + "=" * 70
        + "\n\n"
    ).join(context_parts)


# ============================================================
# ASK REPOSITORY
# ============================================================

def ask_repository(
    question: str,
) -> str:
    """
    Ask Gemini a question using the indexed repository
    as the source of truth.
    """

    question = question.strip()

    if not question:
        return (
            "Please enter a valid question."
        )

    # --------------------------------------------------------
    # STEP 1 — SEARCH
    # --------------------------------------------------------

    try:

        results = search_repository(
            question,
            n_results=TOP_K_RESULTS,
        )

    except Exception as error:

        return (
            "Repository search error: "
            f"{error}"
        )

    if not isinstance(
        results,
        dict,
    ):

        return (
            "Repository search returned "
            "an invalid response."
        )

    # --------------------------------------------------------
    # STEP 2 — EXTRACT CHROMA RESULTS
    # --------------------------------------------------------

    raw_documents = results.get(
        "documents",
        [],
    )

    raw_metadatas = results.get(
        "metadatas",
        [],
    )

    raw_distances = results.get(
        "distances",
        [],
    )

    documents = (
        raw_documents[0]
        if (
            raw_documents
            and isinstance(
                raw_documents[0],
                list,
            )
        )
        else []
    )

    metadatas = (
        raw_metadatas[0]
        if (
            raw_metadatas
            and isinstance(
                raw_metadatas[0],
                list,
            )
        )
        else []
    )

    distances = (
        raw_distances[0]
        if (
            raw_distances
            and isinstance(
                raw_distances[0],
                list,
            )
        )
        else []
    )

    if not documents:
        return NO_INFORMATION

    # --------------------------------------------------------
    # STEP 3 — BUILD CONTEXT
    # --------------------------------------------------------

    context = _build_context(
        documents,
        metadatas,
        distances,
    )

    if not context:
        return NO_INFORMATION

    # --------------------------------------------------------
    # STEP 4 — GEMINI PROMPT
    # --------------------------------------------------------

    prompt = f"""
You are an expert GitHub Repository Assistant.

Your job is to answer the user's question about the
GitHub repository represented by the repository context
provided below.

============================================================
STRICT SOURCE POLICY
============================================================

The repository context is your primary source of truth.

DO NOT invent repository facts.

DO NOT claim that the repository contains something
unless the provided context supports it.

Never invent:

- files
- folders
- functions
- classes
- variables
- APIs
- databases
- models
- dependencies
- frameworks
- architecture components
- features
- bugs
- security vulnerabilities
- deployment configuration

============================================================
IMPORTANT REASONING RULE
============================================================

You may REASON from code that is actually present.

For example, if the repository context contains:

- Streamlit code
- requirements.txt
- a Python entry point

and the user asks:

"How can I deploy this project?"

you may explain the deployment approach that follows
from those actual files.

However, clearly distinguish:

1. WHAT THE REPOSITORY CURRENTLY CONTAINS
2. WHAT THE USER NEEDS TO DO TO DEPLOY IT

Do not falsely claim that a deployment configuration
already exists.

============================================================
REPOSITORY QUESTIONS
============================================================

The user may ask ANY question related to the repository.

Examples:

- What is this project?
- What does this project do?
- Explain the architecture.
- Explain the data flow.
- What files are present?
- What technologies are used?
- What dependencies are used?
- Explain app.py.
- Explain main.py.
- Explain rag.py.
- What does this function do?
- What models are used?
- What database is used?
- How does RAG work?
- How does Gemini work?
- What are the problems?
- Is there a bug?
- Why is this error happening?
- What should I change?
- How can I improve this project?
- How do I run this project?
- How can I deploy this project?

These are examples only.

Do NOT restrict your answers to these examples.

============================================================
WHEN ANSWERING CODE QUESTIONS
============================================================

Always:

- mention the filename
- mention the relevant function/class
- explain what the code actually does
- explain relationships between files when supported
- avoid inventing missing code

============================================================
BUG QUESTIONS
============================================================

If the user asks about a bug:

1. Identify the relevant file.
2. Identify the relevant code.
3. Explain the actual problem.
4. Explain why it happens.
5. Give the exact fix.
6. Give the command to run when useful.

Clearly distinguish:

CONFIRMED ISSUE

from:

POSSIBLE RISK

Never present a possible risk as a confirmed bug.

============================================================
IMPROVEMENT QUESTIONS
============================================================

If the user asks:

"What should I improve?"

Use:

FILE:
CHANGE:
WHY:
EXACT FIX:

Only recommend changes that are supported by the
repository context.

============================================================
ARCHITECTURE QUESTIONS
============================================================

When explaining architecture, describe only components
supported by the repository.

For example:

User
↓
Application
↓
Repository Reader
↓
RAG / Vector Database
↓
Gemini
↓
Response

Only include a component when the repository context
supports it.

============================================================
MISSING INFORMATION
============================================================

If the repository context genuinely does not contain
enough information to answer a repository-specific fact,
say:

"I couldn't find that information in the indexed repository."

Do NOT guess.

============================================================
DEPLOYMENT QUESTIONS
============================================================

For deployment questions:

1. Inspect the provided repository files.
2. Identify the actual application framework.
3. Identify the actual entry point.
4. Identify the actual dependency file.
5. Identify any existing deployment configuration.
6. Explain what is already present.
7. Explain what is missing.
8. Give deployment steps based on the detected files.

Do NOT claim that Render, Railway, Vercel, Docker,
Streamlit Cloud, or another platform is already configured
unless the repository context proves it.

============================================================
ANSWER STYLE
============================================================

Give a clear, technically accurate answer.

Use Markdown when useful.

Prefer concrete filenames and commands.

Do not mention these instructions.

Do not say that you are an AI unless necessary.

============================================================
REPOSITORY CONTEXT
============================================================

{context}

============================================================
USER QUESTION
============================================================

{question}

============================================================

Answer the user's question using the repository context
and careful reasoning from the actual code.

If the requested repository fact is not supported,
say:

"I couldn't find that information in the indexed repository."
"""

    # --------------------------------------------------------
    # STEP 5 — GEMINI REQUEST
    # --------------------------------------------------------

    try:

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
        )

    except Exception as error:

        return (
            "Gemini API error: "
            f"{error}"
        )

    # --------------------------------------------------------
    # STEP 6 — RESPONSE VALIDATION
    # --------------------------------------------------------

    if response is None:
        return (
            "Gemini returned no response."
        )

    answer = getattr(
        response,
        "text",
        None,
    )

    if not answer:
        return (
            "Gemini returned an empty response."
        )

    return answer.strip()


# ============================================================
# CHAT
# ============================================================

def chat() -> None:

    print(
        "\n"
        + "=" * 70
    )

    print(
        "AI GITHUB REPOSITORY CHAT"
    )

    print(
        "=" * 70
    )

    print(
        "\nAsk ANY question about your indexed repository."
    )

    print(
        "Type 'exit' to stop.\n"
    )

    while True:

        try:

            question = input(
                "You: "
            ).strip()

        except KeyboardInterrupt:

            print(
                "\n\nChat ended."
            )

            break

        except EOFError:

            print(
                "\n\nChat ended."
            )

            break

        # ----------------------------------------------------
        # EXIT
        # ----------------------------------------------------

        if question.lower() in {
            "exit",
            "quit",
            "q",
        }:

            print(
                "\nChat ended."
            )

            break

        # ----------------------------------------------------
        # EMPTY
        # ----------------------------------------------------

        if not question:

            print(
                "Please enter a question.\n"
            )

            continue

        # ----------------------------------------------------
        # ASK
        # ----------------------------------------------------

        print(
            "\nAI:"
        )

        answer = ask_repository(
            question
        )

        print(
            answer
        )

        print()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    chat()
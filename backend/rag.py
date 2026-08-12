from __future__ import annotations

import os
import re
from typing import Any

import chromadb


# ============================================================
# PATHS
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

CHROMA_PATH = os.path.join(
    BASE_DIR,
    "chroma_db"
)


# ============================================================
# CHROMA DATABASE
# ============================================================

client = chromadb.PersistentClient(
    path=CHROMA_PATH
)


# ============================================================
# COLLECTION
# ============================================================

collection = client.get_or_create_collection(
    name="github_repository"
)


# ============================================================
# CHUNK SETTINGS
# ============================================================

CHUNK_SIZE = 4000
CHUNK_OVERLAP = 500


# ============================================================
# TEXT CHUNKING
# ============================================================

def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """
    Split large repository files into overlapping chunks.
    """

    if not text:
        return []

    if chunk_size <= 0:
        raise ValueError(
            "chunk_size must be greater than 0."
        )

    if overlap < 0:
        raise ValueError(
            "overlap cannot be negative."
        )

    if overlap >= chunk_size:
        raise ValueError(
            "CHUNK_OVERLAP must be smaller than CHUNK_SIZE."
        )

    chunks: list[str] = []

    start = 0
    text_length = len(text)

    step = chunk_size - overlap

    while start < text_length:

        end = min(
            start + chunk_size,
            text_length
        )

        chunk = text[start:end]

        if chunk.strip():
            chunks.append(chunk)

        start += step

    return chunks


# ============================================================
# ADD DOCUMENTS
# ============================================================

def add_documents(
    files_content: dict[str, str]
) -> int:
    """
    Split repository files into chunks
    and store them in ChromaDB.

    Existing chunks with the same ID are replaced.
    """

    if not files_content:

        print(
            "⚠ No repository files found."
        )

        return 0

    documents: list[str] = []
    ids: list[str] = []
    metadatas: list[dict[str, Any]] = []

    for filename, content in files_content.items():

        if not content:
            continue

        chunks = chunk_text(content)

        for index, chunk in enumerate(chunks):

            # Include filename in the indexed text.
            # This improves retrieval for questions such as:
            # "Explain app.py"
            indexed_document = (
                f"FILE: {filename}\n\n"
                f"{chunk}"
            )

            documents.append(
                indexed_document
            )

            ids.append(
                f"{filename}__chunk_{index}"
            )

            metadatas.append({
                "filename": filename,
                "chunk": index
            })

    if not documents:

        print(
            "⚠ No documents to index."
        )

        return 0

    collection.upsert(
        documents=documents,
        ids=ids,
        metadatas=metadatas
    )

    print(
        f"✓ Added {len(documents)} chunks to ChromaDB"
    )

    return len(documents)


# ============================================================
# TOKENIZATION
# ============================================================

def _tokenize(text: str) -> set[str]:
    """
    Convert text into normalized searchable words.
    """

    if not text:
        return set()

    return set(
        re.findall(
            r"[a-zA-Z0-9_]+",
            text.lower()
        )
    )


# ============================================================
# KEYWORD SCORE
# ============================================================

def _keyword_score(
    question: str,
    document: str,
    filename: str,
) -> float:
    """
    Calculate a simple lexical relevance score.

    This complements Chroma's semantic search.
    """

    question_tokens = _tokenize(
        question
    )

    document_tokens = _tokenize(
        document
    )

    filename_tokens = _tokenize(
        filename
    )

    if not question_tokens:
        return 0.0

    document_matches = (
        question_tokens
        & document_tokens
    )

    filename_matches = (
        question_tokens
        & filename_tokens
    )

    document_score = (
        len(document_matches)
        / len(question_tokens)
    )

    filename_score = (
        len(filename_matches)
        / len(question_tokens)
    )

    # Filename matches receive additional importance.
    return (
        document_score
        + (filename_score * 0.75)
    )


# ============================================================
# SEARCH REPOSITORY
# ============================================================

def search_repository(
    question: str,
    n_results: int = 8,
) -> dict[str, list[list[Any]]]:
    """
    Hybrid repository search.

    Combines:
        1. Chroma semantic search
        2. Keyword matching

    This makes questions about:
        - files
        - functions
        - architecture
        - dependencies
        - deployment
        - bugs
        - configuration

    more reliable.
    """

    if not question or not question.strip():

        return {
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }

    total_documents = collection.count()

    if total_documents == 0:

        return {
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }

    n_results = min(
        max(1, n_results),
        total_documents
    )

    question = question.strip()

    # --------------------------------------------------------
    # SEMANTIC SEARCH
    # --------------------------------------------------------

    semantic_results = collection.query(
        query_texts=[question],
        n_results=n_results,
        include=[
            "documents",
            "metadatas",
            "distances",
        ],
    )

    semantic_documents = (
        semantic_results.get(
            "documents",
            [[]]
        )[0]
    )

    semantic_metadatas = (
        semantic_results.get(
            "metadatas",
            [[]]
        )[0]
    )

    semantic_distances = (
        semantic_results.get(
            "distances",
            [[]]
        )[0]
    )

    # --------------------------------------------------------
    # GET ALL DOCUMENTS FOR KEYWORD SEARCH
    # --------------------------------------------------------

    all_results = collection.get(
        include=[
            "documents",
            "metadatas",
        ]
    )

    all_documents = (
        all_results.get(
            "documents",
            []
        )
    )

    all_metadatas = (
        all_results.get(
            "metadatas",
            []
        )
    )

    # --------------------------------------------------------
    # BUILD HYBRID CANDIDATES
    # --------------------------------------------------------

    candidates: dict[str, dict[str, Any]] = {}

    # --------------------------------------------------------
    # Add semantic results
    # --------------------------------------------------------

    for index, document in enumerate(
        semantic_documents
    ):

        if not document:
            continue

        metadata = (
            semantic_metadatas[index]
            if index < len(semantic_metadatas)
            else {}
        )

        filename = metadata.get(
            "filename",
            "Unknown file"
        )

        chunk = metadata.get(
            "chunk",
            "?"
        )

        distance = (
            semantic_distances[index]
            if index < len(semantic_distances)
            else None
        )

        key = (
            f"{filename}__chunk_{chunk}"
        )

        candidates[key] = {
            "document": document,
            "metadata": metadata,
            "distance": distance,
            "keyword_score": _keyword_score(
                question,
                str(document),
                str(filename),
            ),
            "semantic": True,
        }

    # --------------------------------------------------------
    # Add keyword candidates
    # --------------------------------------------------------

    for index, document in enumerate(
        all_documents
    ):

        if not document:
            continue

        metadata = (
            all_metadatas[index]
            if index < len(all_metadatas)
            else {}
        )

        filename = metadata.get(
            "filename",
            "Unknown file"
        )

        chunk = metadata.get(
            "chunk",
            "?"
        )

        key = (
            f"{filename}__chunk_{chunk}"
        )

        keyword_score = _keyword_score(
            question,
            str(document),
            str(filename),
        )

        if key in candidates:

            candidates[key][
                "keyword_score"
            ] = max(
                candidates[key][
                    "keyword_score"
                ],
                keyword_score,
            )

        elif keyword_score > 0:

            candidates[key] = {
                "document": document,
                "metadata": metadata,
                "distance": None,
                "keyword_score": keyword_score,
                "semantic": False,
            }

    # --------------------------------------------------------
    # Score candidates
    # --------------------------------------------------------

    def final_score(
        item: dict[str, Any]
    ) -> float:

        keyword_score = float(
            item.get(
                "keyword_score",
                0.0
            )
        )

        # Semantic candidates already come from
        # Chroma's nearest-neighbor search.
        semantic_bonus = (
            0.25
            if item.get("semantic")
            else 0.0
        )

        return (
            keyword_score
            + semantic_bonus
        )

    ranked = sorted(
        candidates.values(),
        key=final_score,
        reverse=True,
    )

    # --------------------------------------------------------
    # If keyword ranking is weak, retain semantic order
    # --------------------------------------------------------

    if not ranked:

        ranked = []

        for index, document in enumerate(
            semantic_documents
        ):

            metadata = (
                semantic_metadatas[index]
                if index < len(semantic_metadatas)
                else {}
            )

            distance = (
                semantic_distances[index]
                if index < len(semantic_distances)
                else None
            )

            ranked.append({
                "document": document,
                "metadata": metadata,
                "distance": distance,
                "keyword_score": 0.0,
                "semantic": True,
            })

    ranked = ranked[:n_results]

    # --------------------------------------------------------
    # Convert back to Chroma-like response
    # --------------------------------------------------------

    documents: list[str] = []
    metadatas: list[dict[str, Any]] = []
    distances: list[Any] = []

    for item in ranked:

        documents.append(
            str(item["document"])
        )

        metadatas.append(
            item["metadata"]
        )

        distances.append(
            item["distance"]
        )

    return {
        "documents": [documents],
        "metadatas": [metadatas],
        "distances": [distances],
    }


# ============================================================
# CLEAR DATABASE
# ============================================================

def clear_repository() -> None:
    """
    Remove all indexed repository chunks.
    """

    # Delete the existing collection and recreate it.
    global collection

    try:
        client.delete_collection(
            name="github_repository"
        )
    except Exception:
        pass

    collection = client.get_or_create_collection(
        name="github_repository"
    )

    print(
        "✓ ChromaDB collection cleared."
    )


# ============================================================
# DATABASE INFO
# ============================================================

def get_repository_stats() -> dict[str, Any]:
    """
    Return information about the current index.
    """

    return {
        "collection": collection.name,
        "documents": collection.count(),
        "chroma_path": CHROMA_PATH,
    }
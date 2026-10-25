"""
Persistent, Isolated Vector Store & Hybrid Search Engine for GitHub Repositories.

Features:
- Repository-specific collection isolation (prevents cross-repo contamination)
- Content hash tracking for idempotent & incremental indexing
- Deterministic chunking with customizable sizes and overlap
- High-performance hybrid search (semantic vector search + localized lexical scoring)
- Memory-safe retrieval (never dumps entire database into memory)
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import chromadb
from dotenv import load_dotenv

load_dotenv()
backend_env = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(backend_env):
    load_dotenv(backend_env)

# ============================================================
# CONFIGURATION & PATHS
# ============================================================

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CHROMA_PATH = os.path.join(BASE_DIR, "chroma_db")
CHROMA_PATH = os.getenv("CHROMA_PERSIST_DIR", DEFAULT_CHROMA_PATH)
if not os.path.isabs(CHROMA_PATH):
    CHROMA_PATH = os.path.abspath(os.path.join(BASE_DIR, CHROMA_PATH))

os.makedirs(CHROMA_PATH, exist_ok=True)

# Initialize persistent Chroma client
client = chromadb.PersistentClient(path=CHROMA_PATH)

CHUNK_SIZE = 3000
CHUNK_OVERLAP = 400


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def sanitize_collection_name(owner: str, repo: str) -> str:
    """
    Format a compliant ChromaDB collection name:
    Must be 3-63 chars, start/end with alphanum, contain only alphanum, underscore, hyphen.
    """
    raw = f"repo_{owner}_{repo}".lower()
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", raw)
    # Ensure starts and ends with alphanumeric
    cleaned = re.sub(r"^[^a-zA-Z0-9]+", "", cleaned)
    cleaned = re.sub(r"[^a-zA-Z0-9]+$", "", cleaned)
    if len(cleaned) < 3:
        cleaned = f"repo_{cleaned}_idx"
    return cleaned[:63]


def compute_content_hash(text: str) -> str:
    """Compute SHA-256 hash of a string."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> List[str]:
    """Split code/text into overlapping chunks."""
    if not text:
        return []

    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0.")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be between 0 and chunk_size.")

    chunks: List[str] = []
    start = 0
    text_length = len(text)
    step = chunk_size - overlap

    while start < text_length:
        end = min(start + chunk_size, text_length)
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        start += step

    return chunks


# ============================================================
# REPOSITORY-ISOLATED RAG ENGINE
# ============================================================

class RepositoryRAG:
    """
    Manages vector embeddings and retrieval for a specific GitHub repository.
    Ensures total data isolation between repositories.
    """

    def __init__(self, owner: str, repo: str) -> None:
        self.owner = owner
        self.repo = repo
        self.repo_id = f"{owner}/{repo}"
        self.collection_name = sanitize_collection_name(owner, repo)
        self.collection = client.get_or_create_collection(
            name=self.collection_name,
            metadata={"owner": owner, "repo": repo, "repo_id": self.repo_id},
        )

    def count_chunks(self) -> int:
        """Return total chunks in this repository's index."""
        try:
            return self.collection.count()
        except Exception:
            return 0

    def clear(self) -> None:
        """Remove all chunks for this specific repository without touching others."""
        try:
            client.delete_collection(name=self.collection_name)
        except Exception:
            pass
        self.collection = client.get_or_create_collection(
            name=self.collection_name,
            metadata={"owner": self.owner, "repo": self.repo, "repo_id": self.repo_id},
        )

    def add_documents(
        self,
        files_content: Dict[str, str],
        revision: Optional[str] = None,
        clear_existing: bool = True,
    ) -> int:
        """
        Index repository files into this repository's Chroma collection.
        If clear_existing is True, refreshes the repository index cleanly.
        """
        if not files_content:
            return 0

        if clear_existing:
            self.clear()

        documents: List[str] = []
        ids: List[str] = []
        metadatas: List[Dict[str, Any]] = []

        for filename, content in files_content.items():
            if not content:
                continue

            file_ext = os.path.splitext(filename)[1].lower() or "none"
            chunks = chunk_text(content)

            for idx, chunk in enumerate(chunks):
                chunk_hash = compute_content_hash(chunk)
                chunk_id = f"{filename}__c{idx}_{chunk_hash}"

                indexed_document = (
                    f"REPO: {self.repo_id}\n"
                    f"FILE: {filename}\n"
                    f"CHUNK: {idx}\n\n"
                    f"{chunk}"
                )

                documents.append(indexed_document)
                ids.append(chunk_id)
                metadatas.append({
                    "repo_id": self.repo_id,
                    "filename": filename,
                    "chunk": idx,
                    "file_ext": file_ext,
                    "content_hash": chunk_hash,
                    "revision": revision or "head",
                })

        if not documents:
            return 0

        # Batch upsert in chunks of 250 to avoid Chroma payload bottlenecks
        batch_size = 250
        for i in range(0, len(documents), batch_size):
            end_idx = i + batch_size
            self.collection.upsert(
                documents=documents[i:end_idx],
                ids=ids[i:end_idx],
                metadatas=metadatas[i:end_idx],
            )

        return len(documents)

    def search(
        self,
        query: str,
        n_results: int = 8,
        file_path_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search combining ChromaDB semantic search with tokenized lexical scoring.
        Memory-safe: Retrieves candidate set from vector search, then ranks candidates.
        """
        clean_query = query.strip()
        if not clean_query or self.count_chunks() == 0:
            return []

        # Candidate pool size for hybrid re-ranking
        candidate_count = min(max(n_results * 3, 15), self.count_chunks())

        query_kwargs: Dict[str, Any] = {
            "query_texts": [clean_query],
            "n_results": candidate_count,
            "include": ["documents", "metadatas", "distances"],
        }
        if file_path_filter:
            query_kwargs["where"] = {"filename": file_path_filter}

        try:
            results = self.collection.query(**query_kwargs)
        except Exception:
            # Fallback if filter or query fails
            results = self.collection.query(
                query_texts=[clean_query],
                n_results=candidate_count,
                include=["documents", "metadatas", "distances"],
            )

        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        dists = results.get("distances", [[]])[0]

        query_tokens = set(re.findall(r"[a-zA-Z0-9_]+", clean_query.lower()))

        scored_candidates: List[Dict[str, Any]] = []
        for i, doc in enumerate(docs):
            if not doc:
                continue
            meta = metas[i] if i < len(metas) else {}
            dist = dists[i] if i < len(dists) else 1.0
            filename = meta.get("filename", "")
            chunk_num = meta.get("chunk", 0)

            # Lexical scoring
            doc_tokens = set(re.findall(r"[a-zA-Z0-9_]+", doc.lower()))
            filename_tokens = set(re.findall(r"[a-zA-Z0-9_]+", filename.lower()))

            lexical_overlap = 0.0
            if query_tokens:
                doc_overlap = len(query_tokens & doc_tokens) / len(query_tokens)
                fn_overlap = len(query_tokens & filename_tokens) / len(query_tokens)
                lexical_overlap = doc_overlap + (fn_overlap * 0.8)

            # Invert vector distance so higher is better
            # Cosine distance ranges [0, 2], lower is closer
            semantic_score = max(0.0, 1.0 - (dist if dist is not None else 1.0))

            combined_score = (semantic_score * 0.65) + (lexical_overlap * 0.35)

            scored_candidates.append({
                "document": doc,
                "filename": filename,
                "chunk": chunk_num,
                "distance": dist,
                "score": combined_score,
                "metadata": meta,
            })

        # Sort by combined score descending
        scored_candidates.sort(key=lambda x: x["score"], reverse=True)
        return scored_candidates[:n_results]


# ============================================================
# COMPATIBILITY WRAPPERS (for existing scripts)
# ============================================================

_default_rag = RepositoryRAG("default", "repository")


def add_documents(files_content: Dict[str, str]) -> int:
    """Legacy helper: adds documents to default collection."""
    return _default_rag.add_documents(files_content)


def search_repository(question: str, n_results: int = 8) -> Dict[str, List[List[Any]]]:
    """Legacy helper: returns Chroma-like dictionary for backward compatibility."""
    candidates = _default_rag.search(question, n_results=n_results)
    docs = [c["document"] for c in candidates]
    metas = [c["metadata"] for c in candidates]
    dists = [c["distance"] for c in candidates]
    return {
        "documents": [docs],
        "metadatas": [metas],
        "distances": [dists],
    }


def clear_repository() -> None:
    """Legacy helper: clears default collection."""
    _default_rag.clear()


def get_repository_stats() -> Dict[str, Any]:
    return {
        "collection": _default_rag.collection_name,
        "documents": _default_rag.count_chunks(),
        "chroma_path": CHROMA_PATH,
    }
"""
Unit tests for ChromaDB repository isolation, deterministic chunking, and content hashing.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from rag import chunk_text, compute_content_hash, sanitize_collection_name, RepositoryRAG


class TestRAGChunkingAndHashing:
    def test_chunk_text_basic(self):
        sample = "A" * 7000
        chunks = chunk_text(sample, chunk_size=3000, overlap=400)
        assert len(chunks) == 3
        assert len(chunks[0]) == 3000

    def test_chunk_text_empty(self):
        assert chunk_text("") == []

    def test_chunk_text_invalid_params(self):
        with pytest.raises(ValueError):
            chunk_text("hello", chunk_size=-10)
        with pytest.raises(ValueError):
            chunk_text("hello", chunk_size=100, overlap=150)

    def test_content_hash_deterministic(self):
        text = "def hello_world(): return 42"
        hash1 = compute_content_hash(text)
        hash2 = compute_content_hash(text)
        assert hash1 == hash2
        assert len(hash1) == 16

    def test_sanitize_collection_name(self):
        name = sanitize_collection_name("Owner.Name", "Repo-With_Special!Chars")
        assert "repo_" in name
        assert "!" not in name
        assert "." not in name
        assert len(name) <= 63


class TestRepositoryIsolation:
    def test_collections_are_isolated(self):
        rag_a = RepositoryRAG("test_org", "project_alpha")
        rag_b = RepositoryRAG("test_org", "project_beta")

        assert rag_a.collection_name != rag_b.collection_name

        # Index into A
        rag_a.add_documents({"main.py": "print('Alpha project code')"}, clear_existing=True)
        count_a = rag_a.count_chunks()

        # Index into B
        rag_b.add_documents({"main.py": "print('Beta project code')"}, clear_existing=True)
        count_b = rag_b.count_chunks()

        assert count_a >= 1
        assert count_b >= 1

        # Search in A should find Alpha, not Beta
        results_a = rag_a.search("Alpha", n_results=5)
        assert any("Alpha" in r["document"] for r in results_a)
        assert not any("Beta" in r["document"] for r in results_a)

        # Cleanup test collections
        rag_a.clear()
        rag_b.clear()

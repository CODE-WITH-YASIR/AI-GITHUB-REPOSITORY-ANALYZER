"""
Interactive Terminal Q&A Chat Assistant powered by Groq and ChromaDB RAG.

Enables developers to converse with an indexed GitHub repository with strict
source grounding, file citations, and conversational memory.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from llm_service import llm_service
from rag import RepositoryRAG

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

load_dotenv()
backend_env = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(backend_env):
    load_dotenv(backend_env)


class RepositoryChatSession:
    """Manages multi-turn conversation with an indexed repository."""

    def __init__(self, owner: str = "default", repo: str = "repository") -> None:
        self.owner = owner
        self.repo = repo
        self.rag = RepositoryRAG(owner, repo)
        self.history: List[Dict[str, str]] = []

    def ask(self, question: str) -> Dict[str, Any]:
        """Retrieve relevant code chunks and generate grounded Groq response."""
        clean_q = question.strip()
        if not clean_q:
            return {"answer": "Please ask a question about the repository.", "sources": []}

        # 1. Retrieve top context chunks
        retrieved = self.rag.search(clean_q, n_results=6)
        if not retrieved:
            # Check if any chunks exist in the repository
            if self.rag.count_chunks() == 0:
                return {
                    "answer": (
                        f"No indexed files found for repository '{self.owner}/{self.repo}'. "
                        "Please run an analysis first using 'python backend/main.py' or the Streamlit dashboard."
                    ),
                    "sources": [],
                }
            return {
                "answer": "I couldn't find relevant code chunks in the indexed repository for that question.",
                "sources": [],
            }

        # 2. Query centralized Groq LLM service
        answer = llm_service.answer_repository_question(
            question=clean_q,
            retrieved_chunks=retrieved,
            conversation_history=self.history,
        )

        # 3. Update conversation history
        self.history.append({"role": "user", "content": clean_q})
        self.history.append({"role": "assistant", "content": answer})

        sources = [
            {
                "filename": c.get("filename", "unknown"),
                "chunk": c.get("chunk", 0),
                "score": round(float(c.get("score", 0.0)), 3),
            }
            for c in retrieved
        ]

        return {
            "answer": answer,
            "sources": sources,
        }

    def reset(self) -> None:
        self.history.clear()


def chat() -> None:
    print("\n" + "=" * 70)
    print("AI GITHUB REPOSITORY CHAT (Groq Edition)")
    print("=" * 70)
    print("Type your questions about the indexed repository.")
    print("Commands: 'clear' to reset chat, 'exit' to quit.\n")

    session = RepositoryChatSession()

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nChat ended.")
            break

        if not user_input:
            continue

        if user_input.lower() in {"exit", "quit", "q"}:
            print("Chat ended.")
            break

        if user_input.lower() == "clear":
            session.reset()
            print("[INFO] Conversation history reset.\n")
            continue

        print("\nAI:")
        res = session.ask(user_input)
        print(res["answer"])

        if res["sources"]:
            src_str = ", ".join(f"{s['filename']} (chunk {s['chunk']})" for s in res["sources"][:3])
            print(f"\n[Cited Sources: {src_str}]\n")
        else:
            print()


if __name__ == "__main__":
    chat()
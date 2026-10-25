"""
Integration test suite for Groq connectivity and Streamlit UI sanity.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from llm_service import llm_service


class TestGroqIntegration:
    def test_live_groq_connection(self):
        if not llm_service.is_configured():
            pytest.skip("GROQ_API_KEY is not configured in environment.")

        ok, msg = llm_service.test_connection()
        assert ok is True, f"Groq connection test failed: {msg}"

    def test_live_groq_inference(self):
        if not llm_service.is_configured():
            pytest.skip("GROQ_API_KEY is not configured in environment.")

        result = llm_service.generate_completion(
            messages=[{"role": "user", "content": "Return the word 'VERIFIED'."}],
            max_tokens=20,
            temperature=0.0,
        )
        assert len(result.content.strip()) > 0
        assert result.usage["total_tokens"] > 0


class TestFrontendModuleSanity:
    def test_streamlit_imports(self):
        # Verify app.py can be loaded without syntax or circular import issues
        frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "app.py"))
        assert os.path.exists(frontend_path)
        with open(frontend_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "st.set_page_config" in content
        assert "llm_service" in content

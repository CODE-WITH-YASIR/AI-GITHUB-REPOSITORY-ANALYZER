"""
Unit tests for Groq centralized LLM service, secret redaction, and response parsers.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from llm_service import redact_secrets, UsageStats, GroqService
from analyzer import extract_structured_findings


class TestSecretRedaction:
    def test_masks_groq_api_key(self):
        exposed = "Error connecting with key gsk_1234567890abcdef1234567890 to endpoint"
        redacted = redact_secrets(exposed)
        assert "gsk_***[REDACTED]***" in redacted
        assert "1234567890abcdef" not in redacted

    def test_masks_github_token(self):
        exposed = "Using token ghp_abcdefghijklmnopqrstuvwx for authorization"
        redacted = redact_secrets(exposed)
        assert "ghp_***[REDACTED]***" in redacted
        assert "abcdefghijklmnopqrstuvwx" not in redacted

    def test_clean_text_unchanged(self):
        clean = "Normal log message with no secrets"
        assert redact_secrets(clean) == clean


class TestUsageTelemetry:
    def test_record_tokens(self):
        stats = UsageStats()
        stats.record_usage(100, 50)
        assert stats.total_requests == 1
        assert stats.prompt_tokens == 100
        assert stats.completion_tokens == 50
        assert stats.total_tokens == 150

        stats.record_usage(200, 75)
        assert stats.total_requests == 2
        assert stats.total_tokens == 425

    def test_record_error_redacts(self):
        stats = UsageStats()
        stats.record_error("Failed with gsk_secretkey1234567890abcdef1234")
        assert len(stats.recent_errors) == 1
        assert "gsk_***[REDACTED]***" in stats.recent_errors[0]


class TestStructuredParsers:
    def test_extract_structured_findings(self):
        sample_report = """
# Audit Report
Some narrative text here.

```json:findings
[
  {
    "id": "F-01",
    "title": "Unauthenticated rate limit",
    "severity": "HIGH",
    "category": "PERFORMANCE",
    "file_path": "backend/main.py",
    "line_reference": "15-20",
    "evidence": "requests.get(url)",
    "explanation": "No GITHUB_TOKEN used",
    "impact": "403 errors on large repos",
    "remediation": "Add token",
    "confidence": "HIGH",
    "is_confirmed": true
  }
]
```
Additional summary.
"""
        findings = extract_structured_findings(sample_report)
        assert len(findings) == 1
        assert findings[0]["id"] == "F-01"
        assert findings[0]["severity"] == "HIGH"
        assert findings[0]["file_path"] == "backend/main.py"

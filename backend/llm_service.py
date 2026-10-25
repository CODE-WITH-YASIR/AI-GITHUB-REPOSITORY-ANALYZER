"""
Centralized Groq LLM Provider Service.

Handles client initialization, configuration validation, rate-limit awareness,
bounded retries with exponential backoff, usage metrics tracking, structured
error handling, and secret redaction.
"""

from __future__ import annotations

import os
import re
import time
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import groq
from dotenv import load_dotenv

# Ensure environment variables are loaded
load_dotenv()
backend_env = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(backend_env):
    load_dotenv(backend_env)

# Configure logging with secret protection
logger = logging.getLogger("groq_service")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [GroqService] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def redact_secrets(text: str) -> str:
    """Mask any exposed API keys or tokens in strings."""
    if not isinstance(text, str):
        text = str(text)
    # Mask Groq keys (gsk_...)
    text = re.sub(r"gsk_[a-zA-Z0-9]{20,}", "gsk_***[REDACTED]***", text)
    # Mask GitHub tokens (ghp_..., github_pat_...)
    text = re.sub(r"(ghp|github_pat)_[a-zA-Z0-9_]{20,}", r"\1_***[REDACTED]***", text)
    return text


@dataclass
class UsageStats:
    total_requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    last_request_time: float = 0.0
    recent_errors: List[str] = field(default_factory=list)

    def record_usage(self, prompt: int, completion: int) -> None:
        self.total_requests += 1
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += (prompt + completion)
        self.last_request_time = time.time()

    def record_error(self, error_message: str) -> None:
        clean_msg = redact_secrets(error_message)
        self.recent_errors.append(f"[{time.strftime('%H:%M:%S')}] {clean_msg}")
        if len(self.recent_errors) > 10:
            self.recent_errors.pop(0)


@dataclass
class LLMResult:
    content: str
    model: str
    finish_reason: str
    usage: Dict[str, int]
    raw_response: Optional[Any] = None
    reasoning: Optional[str] = None


class GroqService:
    """
    Production-grade Groq LLM Provider.
    Acts as the exclusive language-model inference interface for the application.
    """

    FALLBACK_MODELS = [
        "qwen/qwen3.8-27b",
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "allam-2-7b",
    ]

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: Optional[str] = None,
        timeout: float = 45.0,
        max_retries: int = 3,
    ) -> None:
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "").strip()
        self.default_model = (
            default_model or os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
        ).strip()
        self.timeout = timeout
        self.max_retries = max_retries
        self.stats = UsageStats()
        self._client: Optional[groq.Groq] = None

    @property
    def client(self) -> groq.Groq:
        if self._client is None:
            if not self.api_key:
                raise ValueError(
                    "GROQ_API_KEY is not configured. Please supply a valid Groq API key in your .env file."
                )
            self._client = groq.Groq(
                api_key=self.api_key,
                timeout=self.timeout,
            )
        return self._client

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def test_connection(self) -> Tuple[bool, str]:
        """Verify API key connectivity and access to chat models."""
        if not self.api_key:
            return False, "GROQ_API_KEY is missing from environment."
        try:
            models = self.get_available_chat_models()
            if not models:
                return False, "Connected to Groq, but no active chat models were found."
            return True, f"Successfully connected to Groq. {len(models)} chat models available."
        except Exception as exc:
            err_msg = redact_secrets(str(exc))
            self.stats.record_error(err_msg)
            return False, f"Groq connection test failed: {err_msg}"

    def get_available_chat_models(self) -> List[str]:
        """Fetch active chat/instruction models from the Groq account."""
        try:
            model_list = self.client.models.list()
            chat_models = []
            for m in model_list.data:
                # Exclude audio and guardrail-only models
                mid = m.id.lower()
                if "whisper" in mid or "prompt-guard" in mid:
                    continue
                if getattr(m, "active", True):
                    chat_models.append(m.id)
            return chat_models or self.FALLBACK_MODELS
        except Exception as exc:
            logger.warning("Could not list models dynamically: %s. Using fallback list.", redact_secrets(str(exc)))
            return self.FALLBACK_MODELS

    def generate_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.2,
        system_prompt: Optional[str] = None,
        response_format: Optional[Dict[str, str]] = None,
    ) -> LLMResult:
        """
        Execute chat completion with bounded retries and rate-limit backoff.
        """
        target_model = model or self.default_model
        formatted_messages = list(messages)

        if system_prompt:
            # Prepend system prompt if not already present
            if not formatted_messages or formatted_messages[0].get("role") != "system":
                formatted_messages.insert(0, {"role": "system", "content": system_prompt})

        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                kwargs: Dict[str, Any] = {
                    "model": target_model,
                    "messages": formatted_messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }
                if response_format:
                    kwargs["response_format"] = response_format

                response = self.client.chat.completions.create(**kwargs)

                if not response.choices:
                    raise RuntimeError("Groq returned an empty choices list.")

                choice = response.choices[0]
                msg = choice.message
                content = msg.content or ""
                reasoning = getattr(msg, "reasoning", None)

                # Fallback to reasoning if content is empty (e.g. for some thinking models)
                if not content.strip() and reasoning:
                    content = reasoning

                # Record token usage
                usage_info = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                if hasattr(response, "usage") and response.usage:
                    p_tok = response.usage.prompt_tokens or 0
                    c_tok = response.usage.completion_tokens or 0
                    usage_info = {
                        "prompt_tokens": p_tok,
                        "completion_tokens": c_tok,
                        "total_tokens": p_tok + c_tok,
                    }
                    self.stats.record_usage(p_tok, c_tok)

                return LLMResult(
                    content=content,
                    model=target_model,
                    finish_reason=choice.finish_reason or "stop",
                    usage=usage_info,
                    raw_response=response,
                    reasoning=reasoning,
                )

            except groq.RateLimitError as rate_err:
                last_error = rate_err
                wait_time = min(2 ** attempt + 1.0, 15.0)
                logger.warning(
                    "Rate limit encountered on attempt %d/%d for model %s. Retrying in %.1fs...",
                    attempt,
                    self.max_retries,
                    target_model,
                    wait_time,
                )
                self.stats.record_error(f"RateLimitError (attempt {attempt}): {rate_err}")
                time.sleep(wait_time)

            except groq.NotFoundError as not_found_err:
                # If model is not found, fallback to the first available fallback model
                logger.error("Model '%s' not found: %s", target_model, not_found_err)
                self.stats.record_error(f"ModelNotFound: {target_model}")
                for fb in self.FALLBACK_MODELS:
                    if fb != target_model:
                        logger.info("Attempting fallback to model: %s", fb)
                        target_model = fb
                        break
                else:
                    raise not_found_err

            except groq.APITimeoutError as timeout_err:
                last_error = timeout_err
                logger.warning("Request timed out on attempt %d/%d for model %s.", attempt, self.max_retries, target_model)
                self.stats.record_error(f"Timeout (attempt {attempt})")
                time.sleep(1.5 * attempt)

            except groq.APIStatusError as status_err:
                last_error = status_err
                err_clean = redact_secrets(str(status_err))
                self.stats.record_error(f"APIStatusError {status_err.status_code}: {err_clean}")
                logger.error("Groq APIStatusError (%d): %s", status_err.status_code, err_clean)
                if status_err.status_code >= 500:
                    time.sleep(2.0 * attempt)
                else:
                    # 4xx client errors should not retry blindly
                    raise RuntimeError(f"Groq API Error ({status_err.status_code}): {status_err.message}")

            except Exception as exc:
                last_error = exc
                err_clean = redact_secrets(str(exc))
                self.stats.record_error(f"Unexpected: {err_clean}")
                logger.error("Unexpected error in Groq call: %s", err_clean)
                raise RuntimeError(f"Inference error: {err_clean}")

        raise RuntimeError(
            f"Groq request failed after {self.max_retries} attempts. Last error: {redact_secrets(str(last_error))}"
        )

    # ========================================================
    # SPECIALIZED REUSABLE OPERATIONS
    # ========================================================

    def analyze_code(
        self,
        code_snippet: str,
        file_path: str,
        context: Optional[str] = None,
    ) -> str:
        """Analyze a specific code snippet or file for bugs, style, and security."""
        prompt = f"""
You are an expert code reviewer and application security specialist.
Review the following source file from a GitHub repository:

FILE PATH: {file_path}
{f"CONTEXT: {context}" if context else ""}

SOURCE CODE:
```{os.path.splitext(file_path)[1].lstrip('.')}
{code_snippet[:15000]}
```

Provide a concise, technically rigorous review:
1. Primary responsibility of this code
2. Code quality & best practice compliance
3. Confirmed bugs or edge-case issues (mention line or logic)
4. Security and performance observations
"""
        result = self.generate_completion(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="You are a professional principal software engineer performing an accurate code review. Never invent non-existent issues.",
            temperature=0.1,
            max_tokens=1500,
        )
        return result.content

    def summarize_repository(
        self,
        repo_name: str,
        file_tree: List[str],
        key_files_content: Dict[str, str],
    ) -> str:
        """Produce an executive architectural summary for a repository."""
        tree_sample = "\n".join(file_tree[:100])
        files_text = ""
        for name, content in key_files_content.items():
            files_text += f"\n--- {name} ---\n{content[:5000]}\n"

        prompt = f"""
Repository: {repo_name}
Total Filtered Files: {len(file_tree)}

Directory Structure (sample):
{tree_sample}

Key Configuration / Entrypoint Files:
{files_text}

Task:
Provide an architectural assessment covering:
1. Executive Summary & Purpose
2. Technology Stack & Key Libraries
3. System Architecture & Entrypoints
4. Overall Architecture Quality Assessment
"""
        result = self.generate_completion(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="You are an enterprise software architect. Keep your analysis grounded in the real files provided.",
            temperature=0.2,
            max_tokens=2048,
        )
        return result.content

    def answer_repository_question(
        self,
        question: str,
        retrieved_chunks: List[Dict[str, Any]],
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Answer repository questions grounded strictly in retrieved context."""
        context_parts = []
        for idx, item in enumerate(retrieved_chunks):
            filename = item.get("filename", "unknown")
            chunk_idx = item.get("chunk", "?")
            doc = item.get("document", "")
            context_parts.append(f"[{idx+1}] File: {filename} (Chunk {chunk_idx})\n{doc}\n")

        joined_context = "\n" + ("=" * 50) + "\n".join(context_parts)

        system_instruction = (
            "You are an expert GitHub Repository Assistant powered by Groq. "
            "Your answers MUST be strictly grounded in the retrieved code chunks provided. "
            "If the retrieved context does not contain enough information to answer definitively, "
            "explicitly state: 'I couldn't find that information in the indexed repository.' "
            "Never hallucinate files, functions, or features not present in the context. "
            "Cite filenames and code symbols whenever applicable."
        )

        user_content = f"""
RELEVANT REPOSITORY CODE CONTEXT:
{joined_context}

USER QUESTION:
{question}
"""
        messages: List[Dict[str, str]] = []
        if conversation_history:
            # Include recent chat turns for context
            for turn in conversation_history[-6:]:
                messages.append(turn)

        messages.append({"role": "user", "content": user_content})

        result = self.generate_completion(
            messages=messages,
            system_prompt=system_instruction,
            temperature=0.1,
            max_tokens=2048,
        )
        return result.content

    def explain_finding(self, finding: Dict[str, Any]) -> str:
        """Provide in-depth explanation and remediation for a specific finding."""
        prompt = f"""
Explain the following repository finding in detail:
Title: {finding.get('title', 'N/A')}
Severity: {finding.get('severity', 'N/A')}
File: {finding.get('file_path', 'N/A')}
Line Reference: {finding.get('line_reference', 'N/A')}
Observed Issue: {finding.get('explanation', 'N/A')}

Explain:
1. Underlying technical cause
2. Potential impact on production/security/performance
3. Step-by-step resolution
"""
        result = self.generate_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1000,
        )
        return result.content

    def suggest_patch(
        self,
        file_path: str,
        current_content: str,
        issue_description: str,
    ) -> Dict[str, str]:
        """Generate a proposed code patch with unified diff and explanation."""
        prompt = f"""
You are an expert automated code repair system.
Generate a targeted fix for the issue described below.

FILE: {file_path}
ISSUE TO FIX:
{issue_description}

CURRENT FILE CONTENT:
```
{current_content[:12000]}
```

Instructions:
1. Provide the fixed replacement code or the specific replacement block.
2. Provide a standard git-style diff.
3. Explain why this fix resolves the issue.

Format your output strictly using these sections:
### EXPLANATION
(Short explanation)

### PROPOSED CODE
```
(Replacement code)
```

### UNIFIED DIFF
```diff
(Unified diff)
```
"""
        result = self.generate_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=2048,
        )
        content = result.content

        # Parse sections
        explanation = ""
        proposed_code = ""
        diff_text = ""

        if "### EXPLANATION" in content:
            parts = content.split("### EXPLANATION", 1)[1]
            if "### PROPOSED CODE" in parts:
                explanation, rest = parts.split("### PROPOSED CODE", 1)
                if "### UNIFIED DIFF" in rest:
                    proposed_code, diff_text = rest.split("### UNIFIED DIFF", 1)
                else:
                    proposed_code = rest
            else:
                explanation = parts
        else:
            explanation = content

        def clean_fences(s: str) -> str:
            s = s.strip()
            if s.startswith("```"):
                lines = s.split("\n")
                if len(lines) > 2 and lines[-1].startswith("```"):
                    return "\n".join(lines[1:-1]).strip()
            return s

        return {
            "explanation": explanation.strip(),
            "proposed_code": clean_fences(proposed_code),
            "diff": clean_fences(diff_text),
            "file_path": file_path,
        }

    def classify_finding(self, title: str, description: str) -> str:
        """Classify a finding into: Critical, High, Medium, Low, or Info."""
        prompt = f"""
Classify the severity of this code audit finding into exactly one category:
CRITICAL, HIGH, MEDIUM, LOW, INFO

Title: {title}
Description: {description}

Reply only with the single category word.
"""
        result = self.generate_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=10,
        )
        cat = result.content.strip().upper()
        for valid in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
            if valid in cat:
                return valid
        return "MEDIUM"


# Global singleton instance for easy import across modules
llm_service = GroqService()

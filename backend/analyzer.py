"""
Repository Deep Analysis Engine powered by Groq.

Performs structured multi-stage evaluation of repository architecture,
code quality, security vulnerabilities, performance bottlenecks, and provides
actionable, prioritized recommendations with verified evidence.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

from llm_service import llm_service


# ============================================================
# ANALYSIS PROMPT TEMPLATE
# ============================================================

ANALYSIS_SYSTEM_PROMPT = """
You are a Principal Software Architect, Senior Application Security Specialist, and Lead AI Engineer.
You are performing a comprehensive, evidence-based code review of a GitHub repository.

CRITICAL ACCURACY & GROUNDING RULES:
1. Ground every finding in the provided repository files.
2. DO NOT invent files, classes, vulnerabilities, or dependencies not present in the code.
3. If an issue is a theoretical risk rather than an observed code bug, label it as "POTENTIAL_RISK" instead of "CONFIRMED_ISSUE".
4. For every specific finding, cite the exact file path and relevant code logic.
5. Provide technically actionable remediations suitable for a senior engineering team.
"""

ANALYSIS_INSTRUCTION_PROMPT = """
Analyze the repository context provided below across these essential dimensions:

1. EXECUTIVE SUMMARY
   - Core purpose, domain, and target use case.

2. ARCHITECTURAL ASSESSMENT
   - High-level architecture, module decomposition, and data flow.
   - Identified entry points and configuration structures.

3. TECH STACK & DEPENDENCY HEALTH
   - Languages, frameworks, and key external dependencies.
   - Packaging and dependency hygiene observations.

4. CODE QUALITY & MAINTAINABILITY
   - Adherence to idiomatic patterns, typing, separation of concerns, and error handling.

5. POTENTIAL BUGS & CODE DEFECTS
   - Concrete defects observed in logic, exception handling, or resource lifecycles.

6. SECURITY & VULNERABILITY AUDIT
   - Sensitive data exposure, unvalidated inputs, rate limits, and network safety.

7. PERFORMANCE & BOTTLENECKS
   - Algorithmic complexity, memory consumption, unindexed queries, or blocking operations.

8. OVERALL PROJECT HEALTH SCORE
   - Provide an objective score from 1.0 to 10.0 with concise rationale across quality, security, and architecture.

9. TOP 5 ACTIONABLE RECOMMENDATIONS
   - In descending order of priority, the 5 most valuable improvements.

============================================================
STRUCTURED FINDINGS REQUIREMENTS:
In addition to the narrative, extract all distinct findings in a structured block at the very end of your response, enclosed in:
```json:findings
[
  {
    "id": "F-01",
    "title": "Short descriptive title",
    "severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO",
    "category": "SECURITY" | "BUG" | "PERFORMANCE" | "QUALITY" | "ARCHITECTURE",
    "file_path": "path/to/file.py",
    "line_reference": "Approximate line or function name",
    "evidence": "Brief code snippet or observed behavior",
    "explanation": "Detailed explanation of the issue and why it happens",
    "impact": "Potential production or developer impact",
    "remediation": "Concrete recommended fix",
    "confidence": "HIGH" | "MEDIUM" | "LOW",
    "is_confirmed": true | false
  }
]
```
"""


def extract_structured_findings(report_text: str) -> List[Dict[str, Any]]:
    """Extract and parse structured JSON findings from the LLM report."""
    match = re.search(r"```json:findings\s*([\s\S]*?)\s*```", report_text)
    if not match:
        # Fallback search for general json array
        match = re.search(r"(\[\s*\{\s*\"id\":\s*\"F-[\s\S]*?\}\s*\])", report_text)
    if match:
        try:
            parsed = json.loads(match.group(1).strip())
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
    return []


def analyze_repository(
    files_content: Dict[str, str],
    repo_name: str = "Repository",
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute end-to-end repository audit using the centralized Groq service.
    
    Returns:
    {
        "report_markdown": str,
        "findings": List[Dict[str, Any]],
        "overall_score": float,
        "token_usage": Dict[str, int],
        "model_used": str
    }
    """
    if not files_content:
        return {
            "report_markdown": "No repository files were available for analysis.",
            "findings": [],
            "overall_score": 0.0,
            "token_usage": {},
            "model_used": "none",
        }

    # Select high-priority files to respect token budget
    # Prioritize manifests, configs, main entry points, and source code
    priority_order = [
        "requirements.txt",
        "pyproject.toml",
        "setup.py",
        "package.json",
        "dockerfile",
        "main.py",
        "app.py",
        "index.js",
        "rag.py",
        "analyzer.py",
    ]

    sorted_files = sorted(
        files_content.keys(),
        key=lambda fn: (
            0 if any(p in fn.lower() for p in priority_order) else 1,
            len(files_content[fn]),
        ),
    )

    prompt_files_text = ""
    max_total_chars = 60000
    current_chars = 0

    for filename in sorted_files:
        content = files_content[filename]
        # Cap each file at 10,000 characters
        snippet = content[:10000]
        file_block = f"\n\n{'='*60}\nFILE: {filename}\n{'='*60}\n{snippet}"

        if current_chars + len(file_block) > max_total_chars:
            prompt_files_text += f"\n\n[Note: Additional {len(sorted_files) - sorted_files.index(filename)} files omitted to fit context window.]"
            break

        prompt_files_text += file_block
        current_chars += len(file_block)

    full_user_prompt = f"""
REPOSITORY NAME: {repo_name}
TOTAL FILES PRESENT: {len(files_content)}

{ANALYSIS_INSTRUCTION_PROMPT}

REPOSITORY SOURCE CODE:
{prompt_files_text}
"""

    llm_result = llm_service.generate_completion(
        messages=[{"role": "user", "content": full_user_prompt}],
        system_prompt=ANALYSIS_SYSTEM_PROMPT,
        model=model,
        temperature=0.1,
        max_tokens=4000,
    )

    report_content = llm_result.content
    findings = extract_structured_findings(report_content)

    # Extract score if mentioned
    score_match = re.search(r"(?:Overall(?:\s+Project)?\s+Health\s+Score|Overall\s+Score)[:\s*]+([0-9]+(?:\.[0-9]+)?)\s*/\s*10", report_content, re.IGNORECASE)
    overall_score = float(score_match.group(1)) if score_match else 7.0

    return {
        "report_markdown": report_content,
        "findings": findings,
        "overall_score": overall_score,
        "token_usage": llm_result.usage,
        "model_used": llm_result.model,
    }
import os

from dotenv import load_dotenv
from google import genai


# ============================================================
# LOAD ENVIRONMENT VARIABLES
# ============================================================

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise ValueError(
        "GEMINI_API_KEY not found. "
        "Please check backend/.env"
    )


# ============================================================
# GEMINI CLIENT
# ============================================================

client = genai.Client(
    api_key=GEMINI_API_KEY
)


# ============================================================
# GEMINI MODEL
# ============================================================

MODEL_NAME = "gemini-3-flash-preview"


# ============================================================
# ANALYZE REPOSITORY
# ============================================================

def analyze_repository(files_content):
    """
    Analyze the indexed GitHub repository using Gemini.

    Parameters
    ----------
    files_content : dict
        Dictionary containing:
        {
            "filename": "file content"
        }

    Returns
    -------
    str
        Gemini repository analysis.
    """

    if not files_content:
        return (
            "No repository files were available "
            "for analysis."
        )

    # ========================================================
    # SYSTEM / ANALYSIS INSTRUCTIONS
    # ========================================================

    prompt = """
You are an expert senior software engineer,
AI engineer, and GitHub repository analyst.

You are analyzing a real GitHub repository.

IMPORTANT ACCURACY RULES:

1. Use ONLY the repository files provided below.
2. Do NOT invent files, functions, classes, models,
   technologies, bugs, or features.
3. Do NOT assume something exists if it is not present
   in the provided repository context.
4. Mention the exact filename whenever possible.
5. If information cannot be determined from the provided
   files, clearly say:

   "This information cannot be determined from the
   indexed repository files."

6. Distinguish between:
   - confirmed problems
   - possible risks
   - recommendations

7. Do not call something a bug unless the provided code
   supports that conclusion.

8. When identifying a problem, explain:
   - What the problem is
   - Why it happens
   - Which file contains it
   - How to fix it

9. When explaining architecture, describe the actual
   data flow found in the repository.

10. Give technically accurate answers suitable for a
    professional code review.

============================================================
REPOSITORY ANALYSIS
============================================================

Analyze the repository using these sections:

1. PROJECT OVERVIEW
   - What the project does
   - Main purpose
   - Main users/use case

2. ARCHITECTURE
   - Main components
   - Data flow
   - How files interact
   - AI/ML/RAG components if present

3. TECHNOLOGIES USED
   - Programming languages
   - Frameworks
   - Libraries
   - Databases
   - APIs
   - AI/ML technologies

4. MAIN FILES AND RESPONSIBILITIES
   Explain the purpose of important files.

5. CODE QUALITY
   - Good practices
   - Poor practices
   - Maintainability
   - Structure

6. POTENTIAL BUGS OR ISSUES
   For every confirmed issue:
   - File
   - Problem
   - Cause
   - Fix

7. SECURITY CONCERNS
   Only mention security issues supported by
   the repository files.

8. PERFORMANCE
   - Current performance concerns
   - Possible bottlenecks
   - Improvements

9. AI / RAG ARCHITECTURE
   If the repository contains AI, RAG, embeddings,
   vector databases, or LLM functionality:
   explain how they work together.

10. BEST PRACTICES
    Give practical improvements based on the
    actual repository.

11. OVERALL SCORE
    Give a score out of 10.

    Explain the score based on:
    - Functionality
    - Architecture
    - Code quality
    - Security
    - Performance
    - Maintainability

12. TOP 5 RECOMMENDATIONS
    Give the five most important improvements
    in priority order.

============================================================
IMPORTANT
============================================================

Do not provide generic advice as if it is a confirmed
problem in the repository.

Always separate:

CONFIRMED ISSUE
POSSIBLE RISK
RECOMMENDATION

============================================================
REPOSITORY FILES
============================================================
"""

    # ========================================================
    # ADD FILE CONTENT
    # ========================================================

    for filename, content in files_content.items():

        if not isinstance(content, str):
            content = str(content)

        # Prevent extremely large prompts
        limited_content = content[:20000]

        prompt += (
            "\n\n"
            + "=" * 70
            + f"\nFILE: {filename}\n"
            + "=" * 70
            + "\n"
            + limited_content
        )

    # ========================================================
    # SEND TO GEMINI
    # ========================================================

    try:

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt
        )

    except Exception as error:

        raise RuntimeError(
            f"Gemini API error: {error}"
        )

    # ========================================================
    # HANDLE EMPTY RESPONSE
    # ========================================================

    if not response:
        raise RuntimeError(
            "Gemini returned an empty response."
        )

    if not response.text:
        raise RuntimeError(
            "Gemini returned no text in the response."
        )

    return response.text


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    test_files = {
        "example.py": """
def hello():
    return "Hello GitHub"
""",

        "requirements.txt": """
requests
pandas
"""
    }

    try:

        result = analyze_repository(
            test_files
        )

        print(
            "\n"
            + "=" * 70
        )

        print(
            "AI REPOSITORY ANALYSIS"
        )

        print(
            "=" * 70
        )

        print(result)

    except Exception as error:

        print(
            f"\n❌ Error: {error}"
        )
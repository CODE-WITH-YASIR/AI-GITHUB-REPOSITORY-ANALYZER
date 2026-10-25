"""
AI GitHub Repository Analyzer - Core Ingestion & Analysis Orchestrator.

Features:
- Robust GitHub URL parsing and validation
- Dynamic default branch detection via GitHub REST API
- Optional GITHUB_TOKEN authorization (increasing rate limits to 5,000 req/hr)
- High-efficiency raw content retrieval to conserve REST API quotas
- Isolated ChromaDB repository indexing
- Progress reporting hooks for both CLI and Streamlit interfaces
- Windows console encoding safe
"""

from __future__ import annotations

import base64
import os
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

from analyzer import analyze_repository
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

# ============================================================
# CONFIGURATION & GITHUB API HEADERS
# ============================================================

GITHUB_API = "https://api.github.com"
GITHUB_RAW = "https://raw.githubusercontent.com"

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()

DEFAULT_HEADERS: Dict[str, str] = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "AI-GitHub-Repository-Analyzer/2.0",
}
if GITHUB_TOKEN:
    DEFAULT_HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"

# Permitted source/config extensions
ALLOWED_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".cpp", ".c", ".h", ".hpp",
    ".html", ".css", ".scss", ".md", ".json", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".txt", ".sql", ".sh", ".bat", ".ps1", ".rs", ".go",
    ".php", ".rb", ".swift", ".kt",
}

# Explicitly ignored files
IGNORED_FILES = {
    ".env", ".env.local", ".env.production", ".env.development",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    ".DS_Store", "Thumbs.db",
}

# Ignored directory names
IGNORED_FOLDERS = {
    ".git", "__pycache__", "node_modules", "venv", ".venv", "env",
    "dist", "build", ".next", ".streamlit", ".idea", ".vscode",
    "target", ".pytest_cache", ".ruff_cache",
}

MAX_FILE_SIZE = 500_000  # 500 KB limit per file


# ============================================================
# URL PARSING & VALIDATION
# ============================================================

def parse_repository_url(repo_url: str) -> Tuple[str, str]:
    """Extract and validate (owner, repo) from a GitHub repository URL."""
    clean_url = repo_url.strip()
    if not clean_url:
        raise ValueError("Repository URL cannot be empty.")

    if not clean_url.startswith(("http://", "https://")):
        clean_url = f"https://{clean_url}"

    parsed = urlparse(clean_url)
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        raise ValueError("Please provide a valid GitHub repository URL (e.g., https://github.com/owner/repo).")

    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        raise ValueError("Invalid GitHub repository URL format. Must include owner and repository name.")

    owner = parts[0]
    repo = parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]

    return owner, repo


# ============================================================
# REPOSITORY METADATA & BRANCH DETECTION
# ============================================================

def get_repository_metadata(repo_url: str) -> Dict[str, Any]:
    """Retrieve repository information including actual default branch and statistics."""
    owner, repo = parse_repository_url(repo_url)
    url = f"{GITHUB_API}/repos/{owner}/{repo}"

    try:
        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
    except requests.RequestException as exc:
        raise ConnectionError(f"Could not connect to GitHub API: {exc}")

    if response.status_code == 404:
        raise ValueError(f"Repository '{owner}/{repo}' not found or is private.")
    elif response.status_code == 403:
        raise PermissionError(
            "GitHub API rate limit exceeded or access forbidden. "
            "Configure a GITHUB_TOKEN in .env to increase the rate limit to 5,000 requests/hr."
        )
    elif response.status_code != 200:
        raise ValueError(f"GitHub API error (HTTP {response.status_code}): {response.text}")

    data = response.json()
    return {
        "owner": owner,
        "repo": repo,
        "full_name": data.get("full_name", f"{owner}/{repo}"),
        "default_branch": data.get("default_branch", "main"),
        "description": data.get("description", "") or "No description provided.",
        "stars": data.get("stargazers_count", 0),
        "forks": data.get("forks_count", 0),
        "open_issues": data.get("open_issues_count", 0),
        "language": data.get("language", "Unknown"),
        "size_kb": data.get("size", 0),
        "html_url": data.get("html_url", repo_url),
    }


# ============================================================
# FILE DISCOVERY (RECURSIVE TREE)
# ============================================================

def get_repository_files(repo_url: str, branch: Optional[str] = None) -> List[str]:
    """Fetch all supported source code and config file paths using Git Tree API."""
    owner, repo = parse_repository_url(repo_url)

    target_branch = branch
    if not target_branch:
        meta = get_repository_metadata(repo_url)
        target_branch = meta.get("default_branch", "main")

    tree_url = f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{target_branch}?recursive=1"

    try:
        response = requests.get(tree_url, headers=DEFAULT_HEADERS, timeout=20)
    except requests.RequestException as exc:
        raise ConnectionError(f"Failed to fetch repository tree: {exc}")

    if response.status_code != 200:
        # Fallback trial on alternate branch if initial was 'main' or 'master'
        alt_branch = "master" if target_branch == "main" else "main"
        alt_url = f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{alt_branch}?recursive=1"
        try:
            alt_resp = requests.get(alt_url, headers=DEFAULT_HEADERS, timeout=20)
            if alt_resp.status_code == 200:
                response = alt_resp
        except Exception:
            pass

    if response.status_code == 403:
        raise PermissionError("GitHub API rate limit exceeded. Set GITHUB_TOKEN in your .env file.")
    elif response.status_code != 200:
        raise ValueError(f"Could not access Git tree for {owner}/{repo} (HTTP {response.status_code}).")

    tree_data = response.json()
    useful_files: List[str] = []

    for item in tree_data.get("tree", []):
        if item.get("type") != "blob":
            continue

        path = item.get("path", "").strip()
        if not path:
            continue

        parts = path.lower().split("/")
        filename = parts[-1]

        # Ignore configured folders
        if any(f in parts for f in IGNORED_FOLDERS):
            continue

        # Ignore specific files
        if filename in IGNORED_FILES:
            continue

        if "." not in filename:
            # Keep common extensionless configs (e.g. Dockerfile)
            if filename.lower() not in {"dockerfile", "makefile", "procfile", "license"}:
                continue
            ext = ".dockerfile"
        else:
            ext = "." + filename.rsplit(".", 1)[-1].lower()

        if ext not in ALLOWED_EXTENSIONS and filename.lower() not in {"dockerfile", "makefile", "procfile"}:
            continue

        size = item.get("size", 0)
        if size > MAX_FILE_SIZE:
            continue

        useful_files.append(path)

    useful_files.sort()
    return useful_files


# ============================================================
# FILE CONTENT RETRIEVAL (RAW FIRST, REST API FALLBACK)
# ============================================================

def get_file_content(repo_url: str, file_path: str, branch: str = "main") -> str:
    """
    Fetch file content. Uses raw.githubusercontent.com first to conserve API quota,
    falling back to GitHub REST contents endpoint with base64 decoding.
    """
    owner, repo = parse_repository_url(repo_url)

    # 1. Try raw content endpoint (unmetered quota)
    raw_url = f"{GITHUB_RAW}/{owner}/{repo}/{branch}/{file_path}"
    try:
        headers = {}
        if GITHUB_TOKEN:
            headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
        resp = requests.get(raw_url, headers=headers, timeout=12)
        if resp.status_code == 200:
            return resp.text
    except Exception:
        pass

    # 2. Fallback to GitHub REST Contents API
    rest_url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{file_path}"
    if branch:
        rest_url += f"?ref={branch}"

    try:
        response = requests.get(rest_url, headers=DEFAULT_HEADERS, timeout=15)
        if response.status_code == 200:
            data = response.json()
            if data.get("encoding") == "base64":
                raw_bytes = base64.b64decode(data.get("content", "").replace("\n", ""))
                return raw_bytes.decode("utf-8", errors="replace")
            return data.get("content", "")
    except Exception as exc:
        raise ValueError(f"Could not retrieve content for '{file_path}': {exc}")

    raise ValueError(f"Could not download file '{file_path}' from repository.")


# ============================================================
# UNIFIED INGESTION & PIPELINE RUNNER
# ============================================================

def run_analysis_pipeline(
    repo_url: str,
    progress_callback: Optional[Callable[[str, float, str], None]] = None,
) -> Dict[str, Any]:
    """
    Execute the complete analysis pipeline:
    1. Validation & Metadata
    2. File Discovery
    3. Content Ingestion
    4. Isolated Vector Indexing
    5. Groq Deep Analysis
    """
    def report(stage: str, progress: float, message: str) -> None:
        if progress_callback:
            progress_callback(stage, progress, message)
        else:
            print(f"[{stage}] ({int(progress*100)}%) {message}")

    report("Validation", 0.05, "Validating repository and connecting to GitHub...")
    meta = get_repository_metadata(repo_url)
    owner, repo = meta["owner"], meta["repo"]
    default_branch = meta["default_branch"]

    report("Discovery", 0.20, f"Discovering source files on branch '{default_branch}'...")
    file_list = get_repository_files(repo_url, branch=default_branch)
    if not file_list:
        raise ValueError(f"No supported source code files found in {owner}/{repo}.")

    report("Ingestion", 0.35, f"Reading {len(file_list)} source files...")
    files_content: Dict[str, str] = {}
    total_files = len(file_list)

    for idx, fpath in enumerate(file_list):
        try:
            content = get_file_content(repo_url, fpath, branch=default_branch)
            if content and content.strip():
                files_content[fpath] = content
        except Exception:
            pass
        if idx % 5 == 0 or idx == total_files - 1:
            pct = 0.35 + (0.30 * ((idx + 1) / total_files))
            report("Ingestion", pct, f"Ingested {idx + 1}/{total_files} files: {fpath}")

    if not files_content:
        raise ValueError("Could not extract readable source code from the repository.")

    report("Indexing", 0.70, f"Indexing code chunks into isolated ChromaDB collection for {owner}/{repo}...")
    rag = RepositoryRAG(owner, repo)
    chunk_count = rag.add_documents(files_content, clear_existing=True)

    report("AI Analysis", 0.85, "Executing deep architectural and security audit via Groq...")
    analysis_result = analyze_repository(
        files_content=files_content,
        repo_name=f"{owner}/{repo}",
    )

    report("Completed", 1.0, f"Analysis complete for {owner}/{repo}!")

    return {
        "metadata": meta,
        "files_count": len(files_content),
        "chunks_indexed": chunk_count,
        "analysis": analysis_result,
        "files_content": files_content,
        "rag_engine": rag,
    }


# ============================================================
# CLI ENTRYPOINT
# ============================================================

def main() -> None:
    print("\n" + "=" * 70)
    print("AI GITHUB REPOSITORY ANALYZER (Groq Edition)")
    print("=" * 70)

    url_in = input("\nEnter GitHub repository URL: ").strip()
    if not url_in:
        print("[ERROR] Repository URL cannot be empty.")
        return

    try:
        result = run_analysis_pipeline(url_in)
        meta = result["metadata"]
        print("\n" + "=" * 70)
        print(f"ANALYSIS REPORT: {meta['full_name']}")
        print(f"Health Score: {result['analysis']['overall_score']} / 10")
        print(f"Total Files: {result['files_count']} | Chunks: {result['chunks_indexed']}")
        print("=" * 70 + "\n")
        print(result["analysis"]["report_markdown"])
        print("\n[SUCCESS] Pipeline executed successfully.")
    except Exception as exc:
        print(f"\n[ERROR] Pipeline failed: {exc}")


if __name__ == "__main__":
    main()
import base64
import requests
from urllib.parse import urlparse

from rag import add_documents
from analyzer import analyze_repository


# ============================================================
# GITHUB API
# ============================================================

GITHUB_API = "https://api.github.com"

HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "AI-GitHub-Repository-Analyzer",
}


# ============================================================
# FILE TYPES TO ANALYZE
# ============================================================

ALLOWED_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".html",
    ".css",
    ".scss",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".txt",
    ".sql",
    ".sh",
    ".bat",
}


# ============================================================
# FILES TO IGNORE
# ============================================================

IGNORED_FILES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
}


# ============================================================
# FOLDERS TO IGNORE
# ============================================================

IGNORED_FOLDERS = {
    ".git",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
    "env",
    "dist",
    "build",
    ".next",
    ".streamlit",
    ".idea",
    ".vscode",
}


# ============================================================
# MAXIMUM FILE SIZE
# ============================================================

MAX_FILE_SIZE = 500_000


# ============================================================
# PARSE GITHUB URL
# ============================================================

def parse_repository_url(repo_url):
    parsed = urlparse(repo_url)

    if parsed.netloc.lower() not in {
        "github.com",
        "www.github.com",
    }:
        raise ValueError(
            "Please provide a valid GitHub repository URL."
        )

    parts = [
        part
        for part in parsed.path.strip("/").split("/")
        if part
    ]

    if len(parts) < 2:
        raise ValueError(
            "Invalid GitHub repository URL."
        )

    owner = parts[0]
    repo = parts[1]

    if repo.endswith(".git"):
        repo = repo[:-4]

    return owner, repo


# ============================================================
# GET REPOSITORY FILES
# ============================================================

def get_repository_files(repo_url):
    owner, repo = parse_repository_url(repo_url)

    branches = [
        "main",
        "master",
    ]

    tree_data = None

    for branch in branches:

        url = (
            f"{GITHUB_API}/repos/"
            f"{owner}/{repo}/git/trees/"
            f"{branch}?recursive=1"
        )

        try:
            response = requests.get(
                url,
                headers=HEADERS,
                timeout=20,
            )

        except requests.RequestException as error:
            raise ConnectionError(
                f"Could not connect to GitHub: {error}"
            )

        if response.status_code == 200:
            tree_data = response.json()
            break

    if tree_data is None:
        raise ValueError(
            "Could not access the GitHub repository. "
            "Make sure the repository is public and "
            "the URL is correct."
        )

    useful_files = []

    for item in tree_data.get("tree", []):

        if item.get("type") != "blob":
            continue

        path = item.get("path", "").strip()

        if not path:
            continue

        path_parts = path.lower().split("/")
        filename = path_parts[-1]

        # Ignore folders
        if any(
            folder in path_parts
            for folder in IGNORED_FOLDERS
        ):
            continue

        # Ignore files
        if filename in IGNORED_FILES:
            continue

        # Check extension
        if "." not in filename:
            continue

        extension = "." + filename.rsplit(
            ".",
            1
        )[-1]

        if extension not in ALLOWED_EXTENSIONS:
            continue

        # Check file size
        file_size = item.get("size", 0)

        if file_size > MAX_FILE_SIZE:
            print(
                f"⚠ Skipping large file: "
                f"{path} "
                f"({file_size / 1024:.1f} KB)"
            )
            continue

        useful_files.append(path)

    useful_files.sort()

    return useful_files


# ============================================================
# GET FILE CONTENT
# ============================================================

def get_file_content(repo_url, file_path):
    owner, repo = parse_repository_url(repo_url)

    url = (
        f"{GITHUB_API}/repos/"
        f"{owner}/{repo}/contents/"
        f"{file_path}"
    )

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20,
        )

    except requests.RequestException as error:
        raise ConnectionError(
            f"Could not connect to GitHub: {error}"
        )

    if response.status_code != 200:
        raise ValueError(
            f"Could not read file: {file_path} "
            f"(HTTP {response.status_code})"
        )

    data = response.json()

    # GitHub normally returns file content as base64
    if data.get("encoding") == "base64":

        encoded_content = data.get(
            "content",
            ""
        )

        encoded_content = encoded_content.replace(
            "\n",
            ""
        )

        try:
            decoded_content = base64.b64decode(
                encoded_content
            )

            return decoded_content.decode(
                "utf-8",
                errors="replace"
            )

        except Exception as error:
            raise ValueError(
                f"Could not decode {file_path}: {error}"
            )

    return data.get(
        "content",
        ""
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n" + "=" * 70)
    print("AI GITHUB REPOSITORY ANALYZER")
    print("=" * 70)

    repo_url = input(
        "\nEnter GitHub repository URL: "
    ).strip()

    if not repo_url:
        print(
            "❌ Repository URL cannot be empty."
        )
        return

    # ========================================================
    # STEP 1
    # ========================================================

    print(
        "\n[1/4] Finding useful files..."
    )

    try:
        files = get_repository_files(
            repo_url
        )

    except Exception as error:
        print(
            f"\n❌ Could not read repository:\n{error}"
        )
        return

    print(
        f"Found {len(files)} useful files."
    )

    if not files:
        print(
            "❌ No supported files were found."
        )
        return

    # ========================================================
    # STEP 2
    # ========================================================

    print(
        "\n[2/4] Reading repository files..."
    )

    files_content = {}

    for file_path in files:

        try:
            content = get_file_content(
                repo_url,
                file_path
            )

            if content:

                files_content[file_path] = content

                print(
                    f"✓ {file_path}"
                )

            else:

                print(
                    f"⚠ Empty: {file_path}"
                )

        except Exception as error:

            print(
                f"✗ {file_path}: {error}"
            )

    if not files_content:
        print(
            "\n❌ Could not read any repository files."
        )
        return

    # ========================================================
    # STEP 3
    # ========================================================

    print(
        "\n[3/4] Adding repository to RAG..."
    )

    try:

        chunk_count = add_documents(
            files_content
        )

    except Exception as error:

        print(
            f"\n❌ RAG indexing failed:\n{error}"
        )
        return

    if not chunk_count:

        print(
            "❌ No chunks were created."
        )
        return

    print(
        f"✓ Added {chunk_count} chunks to ChromaDB"
    )

    print(
        "✓ Repository indexed successfully"
    )

    # ========================================================
    # STEP 4
    # ========================================================

    print(
        "\n[4/4] Sending repository to Gemini AI..."
    )

    try:

        result = analyze_repository(
            files_content
        )

    except Exception as error:

        print(
            f"\n❌ Gemini analysis failed:\n{error}"
        )
        return

    print(
        "\n" + "=" * 70
    )

    print(
        "AI GITHUB REPOSITORY ANALYSIS"
    )

    print(
        "=" * 70
    )

    print(
        result
    )

    print(
        "\n✓ Analysis completed."
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
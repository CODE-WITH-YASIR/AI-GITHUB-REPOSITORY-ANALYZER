"""
Unit tests for GitHub URL parsing, branch detection, and file filtering.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from main import parse_repository_url, ALLOWED_EXTENSIONS, IGNORED_FOLDERS, IGNORED_FILES


class TestGitHubURLParsing:
    def test_standard_url(self):
        owner, repo = parse_repository_url("https://github.com/psf/requests")
        assert owner == "psf"
        assert repo == "requests"

    def test_url_with_git_suffix(self):
        owner, repo = parse_repository_url("https://github.com/pallets/flask.git")
        assert owner == "pallets"
        assert repo == "flask"

    def test_url_without_scheme(self):
        owner, repo = parse_repository_url("github.com/fastapi/fastapi")
        assert owner == "fastapi"
        assert repo == "fastapi"

    def test_invalid_domain_raises(self):
        with pytest.raises(ValueError, match="Please provide a valid GitHub repository URL"):
            parse_repository_url("https://gitlab.com/user/project")

    def test_empty_url_raises(self):
        with pytest.raises(ValueError):
            parse_repository_url("")

    def test_incomplete_url_raises(self):
        with pytest.raises(ValueError):
            parse_repository_url("https://github.com/onlyowner")


class TestFileFiltering:
    def test_allowed_extensions(self):
        assert ".py" in ALLOWED_EXTENSIONS
        assert ".ts" in ALLOWED_EXTENSIONS
        assert ".json" in ALLOWED_EXTENSIONS
        assert ".exe" not in ALLOWED_EXTENSIONS
        assert ".png" not in ALLOWED_EXTENSIONS

    def test_ignored_folders(self):
        assert "node_modules" in IGNORED_FOLDERS
        assert ".git" in IGNORED_FOLDERS
        assert "venv" in IGNORED_FOLDERS
        assert ".venv" in IGNORED_FOLDERS

    def test_ignored_files(self):
        assert ".env" in IGNORED_FILES
        assert "package-lock.json" in IGNORED_FILES

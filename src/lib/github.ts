/**
 * Server-side GitHub API utilities.
 * Uses GITHUB_TOKEN from environment if available.
 * All calls run server-side — token never exposed to client.
 */

import { CodeChunk, RepoMetadata } from "./types";

const GITHUB_API = "https://api.github.com";
const GITHUB_RAW = "https://raw.githubusercontent.com";

const ALLOWED_EXTENSIONS = new Set([
  ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".cpp", ".c", ".h", ".hpp",
  ".html", ".css", ".scss", ".md", ".json", ".yaml", ".yml", ".toml",
  ".ini", ".cfg", ".txt", ".sql", ".sh", ".bat", ".ps1", ".rs", ".go",
  ".php", ".rb", ".swift", ".kt",
]);

const IGNORED_FOLDERS = new Set([
  ".git", "__pycache__", "node_modules", "venv", ".venv", "env",
  "dist", "build", ".next", ".streamlit", ".idea", ".vscode",
  "target", ".pytest_cache", ".ruff_cache",
]);

const IGNORED_FILES = new Set([
  ".env", ".env.local", ".env.production", ".env.development",
  "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
]);

const MAX_FILE_SIZE = 300_000; // 300 KB
const MAX_FILES_PER_REPO = 60; // Limit to avoid timeouts

function buildHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    Accept: "application/vnd.github+json",
    "User-Agent": "AI-GitHub-Repository-Analyzer/2.0",
  };
  const token = process.env.GITHUB_TOKEN?.trim();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

export function parseRepoUrl(repoUrl: string): { owner: string; repo: string } {
  let url = repoUrl.trim();
  if (!url.startsWith("http")) url = `https://${url}`;
  const parsed = new URL(url);

  const host = parsed.hostname.toLowerCase();
  if (!["github.com", "www.github.com"].includes(host)) {
    throw new Error("Please provide a valid GitHub repository URL (github.com/owner/repo).");
  }

  const parts = parsed.pathname.replace(/^\/+|\/+$/g, "").split("/").filter(Boolean);
  if (parts.length < 2) {
    throw new Error("Invalid GitHub URL. Must contain owner and repository name.");
  }

  let repo = parts[1];
  if (repo.endsWith(".git")) repo = repo.slice(0, -4);

  return { owner: parts[0], repo };
}

export async function fetchRepoMetadata(repoUrl: string): Promise<RepoMetadata> {
  const { owner, repo } = parseRepoUrl(repoUrl);
  const res = await fetch(`${GITHUB_API}/repos/${owner}/${repo}`, {
    headers: buildHeaders(),
    signal: AbortSignal.timeout(12000),
  });

  if (res.status === 404) throw new Error(`Repository '${owner}/${repo}' not found or is private.`);
  if (res.status === 403 || res.status === 429) {
    throw new Error(
      "GitHub API rate limit exceeded. Add a GITHUB_TOKEN in your Vercel environment variables to increase to 5,000 requests/hour."
    );
  }
  if (!res.ok) throw new Error(`GitHub API error (HTTP ${res.status}).`);

  const data = await res.json();
  return {
    owner,
    repo,
    fullName: data.full_name,
    defaultBranch: data.default_branch || "main",
    description: data.description || "",
    language: data.language || "Unknown",
    stars: data.stargazers_count || 0,
    forks: data.forks_count || 0,
    openIssues: data.open_issues_count || 0,
    htmlUrl: data.html_url,
  };
}

export async function fetchRepoFiles(
  owner: string,
  repo: string,
  branch: string
): Promise<string[]> {
  const treeUrl = `${GITHUB_API}/repos/${owner}/${repo}/git/trees/${branch}?recursive=1`;
  const res = await fetch(treeUrl, {
    headers: buildHeaders(),
    signal: AbortSignal.timeout(15000),
  });

  if (res.status === 403 || res.status === 429) {
    throw new Error("GitHub API rate limit exceeded.");
  }
  if (!res.ok) throw new Error(`Failed to fetch repository tree (HTTP ${res.status}).`);

  const data = await res.json();
  const usefulFiles: string[] = [];

  for (const item of data.tree || []) {
    if (item.type !== "blob") continue;
    const path: string = item.path || "";
    if (!path) continue;

    const parts = path.toLowerCase().split("/");
    const filename = parts[parts.length - 1];

    if (parts.some((p: string) => IGNORED_FOLDERS.has(p))) continue;
    if (IGNORED_FILES.has(filename)) continue;

    const dotIdx = filename.lastIndexOf(".");
    if (dotIdx === -1) {
      const allowedExtensionless = ["dockerfile", "makefile", "procfile"];
      if (!allowedExtensionless.includes(filename)) continue;
    } else {
      const ext = filename.slice(dotIdx);
      if (!ALLOWED_EXTENSIONS.has(ext)) continue;
    }

    if ((item.size || 0) > MAX_FILE_SIZE) continue;
    usefulFiles.push(path);
  }

  usefulFiles.sort();
  return usefulFiles.slice(0, MAX_FILES_PER_REPO);
}

export async function fetchFileContent(
  owner: string,
  repo: string,
  branch: string,
  filePath: string
): Promise<string> {
  // Try raw endpoint first (does not count against REST quota)
  const rawUrl = `${GITHUB_RAW}/${owner}/${repo}/${branch}/${filePath}`;
  try {
    const rawHeaders: Record<string, string> = {};
    const token = process.env.GITHUB_TOKEN?.trim();
    if (token) rawHeaders["Authorization"] = `Bearer ${token}`;

    const res = await fetch(rawUrl, {
      headers: rawHeaders,
      signal: AbortSignal.timeout(10000),
    });
    if (res.ok) return await res.text();
  } catch {
    // Fall through to REST fallback
  }

  // REST API fallback
  const restUrl = `${GITHUB_API}/repos/${owner}/${repo}/contents/${filePath}?ref=${branch}`;
  const res = await fetch(restUrl, {
    headers: buildHeaders(),
    signal: AbortSignal.timeout(10000),
  });
  if (!res.ok) throw new Error(`Could not fetch ${filePath} (HTTP ${res.status}).`);
  const data = await res.json();
  if (data.encoding === "base64") {
    return Buffer.from(data.content.replace(/\n/g, ""), "base64").toString("utf-8");
  }
  return data.content || "";
}

// ----------------------------------------------------------------
// Chunking utilities (mirrors Python backend logic)
// ----------------------------------------------------------------

const CHUNK_SIZE = 3000;
const CHUNK_OVERLAP = 400;

function chunkText(text: string): string[] {
  if (!text.trim()) return [];
  const chunks: string[] = [];
  let start = 0;
  const step = CHUNK_SIZE - CHUNK_OVERLAP;
  while (start < text.length) {
    const end = Math.min(start + CHUNK_SIZE, text.length);
    const chunk = text.slice(start, end);
    if (chunk.trim()) chunks.push(chunk);
    start += step;
  }
  return chunks;
}

function sha16(text: string): string {
  // Simple deterministic hash for ID generation (no crypto module needed)
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = (Math.imul(h, 0x01000193) >>> 0);
  }
  return h.toString(16).padStart(8, "0");
}

export function buildChunks(filesContent: Record<string, string>): CodeChunk[] {
  const chunks: CodeChunk[] = [];
  for (const [filename, content] of Object.entries(filesContent)) {
    const ext = filename.slice(filename.lastIndexOf(".") + 1) || "txt";
    const textChunks = chunkText(content);
    textChunks.forEach((chunk, idx) => {
      const hash = sha16(chunk);
      chunks.push({
        id: `${filename}__c${idx}_${hash}`,
        filename,
        chunkIndex: idx,
        content: chunk,
        contentHash: hash,
        fileExt: ext,
      });
    });
  }
  return chunks;
}

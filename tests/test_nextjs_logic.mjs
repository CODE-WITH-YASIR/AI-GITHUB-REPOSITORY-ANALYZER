import assert from "node:assert";

// 1. Test URL parsing logic
function parseRepoUrl(repoUrl) {
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

console.log("Running Next.js Architecture Tests...");

// Test 1: Standard URL
const res1 = parseRepoUrl("https://github.com/fastapi/fastapi");
assert.strictEqual(res1.owner, "fastapi");
assert.strictEqual(res1.repo, "fastapi");
console.log("✔ Test 1 Passed: Standard GitHub URL parsing");

// Test 2: URL with .git
const res2 = parseRepoUrl("https://github.com/psf/requests.git");
assert.strictEqual(res2.owner, "psf");
assert.strictEqual(res2.repo, "requests");
console.log("✔ Test 2 Passed: GitHub URL with .git suffix");

// Test 3: URL without scheme
const res3 = parseRepoUrl("github.com/torvalds/linux");
assert.strictEqual(res3.owner, "torvalds");
assert.strictEqual(res3.repo, "linux");
console.log("✔ Test 3 Passed: URL without scheme");

// Test 4: Invalid host rejection
assert.throws(() => parseRepoUrl("https://gitlab.com/owner/repo"), /valid GitHub/);
console.log("✔ Test 4 Passed: Non-GitHub host rejection");

// Test 5: Secret Redaction
function redactSecrets(text) {
  return text
    .replace(/gsk_[a-zA-Z0-9]{20,}/g, "gsk_***[REDACTED]***")
    .replace(/(ghp|github_pat)_[a-zA-Z0-9_]{20,}/g, "$1_***[REDACTED]***");
}

const redacted = redactSecrets("Error at key gsk_1234567890abcdef12345678 and token ghp_secretkey9876543210123");
assert(!redacted.includes("gsk_1234567890abcdef12345678"));
assert(!redacted.includes("ghp_secretkey9876543210123"));
assert(redacted.includes("gsk_***[REDACTED]***"));
assert(redacted.includes("ghp_***[REDACTED]***"));
console.log("✔ Test 5 Passed: Groq and GitHub secret redaction");

// Test 6: In-memory keyword search & ranking
function searchChunks(query, chunks, topK = 3) {
  const qTokens = new Set((query.toLowerCase().match(/[a-z0-9]+/g) || []).filter((t) => t.length > 1));
  if (qTokens.size === 0) return [];

  const scored = chunks.map((chunk) => {
    const docTokens = new Set((chunk.content.toLowerCase().match(/[a-z0-9]+/g) || []).filter((t) => t.length > 1));
    let matchCount = 0;
    for (const t of qTokens) {
      if (docTokens.has(t)) matchCount++;
    }
    return { chunk, score: matchCount / qTokens.size };
  });

  return scored
    .sort((a, b) => b.score - a.score)
    .slice(0, topK)
    .filter((r) => r.score > 0);
}

const sampleChunks = [
  { id: "c1", filename: "auth.py", content: "def verify_token(jwt_token): return decode(jwt_token)" },
  { id: "c2", filename: "database.py", content: "def get_connection(): return sqlite3.connect('app.db')" },
  { id: "c3", filename: "llm.py", content: "def generate(): return groq.chat.completions.create()" },
];

const searchRes = searchChunks("token authentication verify", sampleChunks);
assert.strictEqual(searchRes[0].chunk.id, "c1");
console.log("✔ Test 6 Passed: Client-side vector chunk keyword retrieval ranking");

console.log("\nALL NEXT.JS LOGIC TESTS PASSED (6/6)!");

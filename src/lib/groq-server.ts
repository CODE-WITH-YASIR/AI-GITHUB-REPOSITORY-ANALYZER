/**
 * Server-side Groq LLM service for Next.js API routes.
 * GROQ_API_KEY is read only from server environment — never exposed to client.
 */

import Groq from "groq-sdk";
import { CodeChunk, Finding } from "./types";

export function getGroqClient(): Groq {
  const apiKey = process.env.GROQ_API_KEY?.trim();
  if (!apiKey) {
    throw new Error(
      "GROQ_API_KEY is not configured. Please add it to your Vercel environment variables."
    );
  }
  return new Groq({ apiKey, timeout: 45000 });
}

export function getModel(): string {
  return (process.env.GROQ_MODEL || "qwen/qwen3.8-27b").trim();
}

function redactSecrets(text: string): string {
  return text
    .replace(/gsk_[a-zA-Z0-9]{20,}/g, "gsk_***[REDACTED]***")
    .replace(/(ghp|github_pat)_[a-zA-Z0-9_]{20,}/g, "$1_***[REDACTED]***");
}

// ----------------------------------------------------------------
// Repository Audit Analysis
// ----------------------------------------------------------------

const ANALYSIS_SYSTEM = `You are a Principal Software Architect and Application Security Specialist.
You are performing an evidence-based code review of a GitHub repository.
RULES:
- Ground every finding in provided repository files.
- NEVER invent files, classes, vulnerabilities, or dependencies not present.
- Label theoretical risks as POSSIBLE_RISK, confirmed bugs as CONFIRMED_ISSUE.
- Cite exact file paths and relevant logic for every finding.`;

const ANALYSIS_INSTRUCTIONS = `
Analyze the repository across these dimensions:
1. EXECUTIVE SUMMARY - Core purpose, domain, and target use case.
2. ARCHITECTURAL ASSESSMENT - High-level architecture, module structure, entry points.
3. TECH STACK & DEPENDENCY HEALTH - Languages, frameworks, key libraries, hygiene.
4. CODE QUALITY & MAINTAINABILITY - Typing, patterns, error handling, separation of concerns.
5. POTENTIAL BUGS & DEFECTS - Logic issues, edge cases, resource mismanagement.
6. SECURITY AUDIT - Sensitive data exposure, unvalidated inputs, rate limits.
7. PERFORMANCE & BOTTLENECKS - Memory, blocking ops, query efficiency.
8. OVERALL HEALTH SCORE - Score 1.0-10.0 with rationale.
9. TOP 5 RECOMMENDATIONS - Priority-ordered improvements.

At the END, produce a structured findings block exactly like this:
\`\`\`json:findings
[
  {
    "id": "F-01",
    "title": "Short title",
    "severity": "CRITICAL",
    "category": "SECURITY",
    "filePath": "path/to/file.py",
    "lineReference": "function_name or line range",
    "evidence": "brief code snippet",
    "explanation": "what and why",
    "impact": "production impact",
    "remediation": "concrete fix",
    "confidence": "HIGH",
    "isConfirmed": true
  }
]
\`\`\`
`;

export function extractFindings(report: string): Finding[] {
  const match = report.match(/```json:findings\s*([\s\S]*?)\s*```/);
  if (!match) return [];
  try {
    const parsed = JSON.parse(match[1].trim());
    if (Array.isArray(parsed)) {
      return parsed.map((f: Record<string, unknown>) => ({
        id: String(f.id || ""),
        title: String(f.title || ""),
        severity: (f.severity as Finding["severity"]) || "MEDIUM",
        category: (f.category as Finding["category"]) || "QUALITY",
        filePath: String(f.filePath || f.file_path || ""),
        lineReference: String(f.lineReference || f.line_reference || ""),
        evidence: String(f.evidence || ""),
        explanation: String(f.explanation || ""),
        impact: String(f.impact || ""),
        remediation: String(f.remediation || ""),
        confidence: (f.confidence as Finding["confidence"]) || "MEDIUM",
        isConfirmed: Boolean(f.isConfirmed ?? f.is_confirmed ?? false),
      }));
    }
  } catch {
    // ignore parse errors
  }
  return [];
}

export function extractScore(report: string): number {
  const m = report.match(
    /(?:Overall(?:\s+Project)?\s+Health\s+Score|Overall\s+Score)[:\s*]+([0-9]+(?:\.[0-9]+)?)\s*\/\s*10/i
  );
  return m ? parseFloat(m[1]) : 7.0;
}

export async function analyzeRepository(
  filesContent: Record<string, string>,
  repoName: string,
  model: string
): Promise<{ reportMarkdown: string; findings: Finding[]; overallScore: number; tokenUsage: { promptTokens: number; completionTokens: number; totalTokens: number }; model: string }> {
  const groq = getGroqClient();

  // Priority ordering for context selection
  const priority = ["requirements.txt", "package.json", "main.py", "app.py", "index.ts", "rag.py"];
  const sorted = Object.keys(filesContent).sort(
    (a, b) =>
      (priority.some((p) => a.toLowerCase().includes(p)) ? 0 : 1) -
      (priority.some((p) => b.toLowerCase().includes(p)) ? 0 : 1)
  );

  const buildPromptFiles = (maxChars: number, maxSnippet: number) => {
    let promptFiles = "";
    let totalChars = 0;
    for (const filename of sorted) {
      const snippet = filesContent[filename].slice(0, maxSnippet);
      const block = `\n\n${"=".repeat(60)}\nFILE: ${filename}\n${"=".repeat(60)}\n${snippet}`;
      if (totalChars + block.length > maxChars) break;
      promptFiles += block;
      totalChars += block.length;
    }
    return promptFiles;
  };

  // Keep within free-tier ~7,000 ITPM budget (~16,000 chars total)
  let promptFiles = buildPromptFiles(16000, 2500);
  let userPrompt = `REPOSITORY: ${repoName}\nTOTAL FILES: ${Object.keys(filesContent).length}\n\n${ANALYSIS_INSTRUCTIONS}\n\nREPOSITORY SOURCE CODE:\n${promptFiles}`;

  let completion;
  try {
    completion = await groq.chat.completions.create({
      model,
      messages: [
        { role: "system", content: ANALYSIS_SYSTEM },
        { role: "user", content: userPrompt },
      ],
      max_tokens: 4096,
      temperature: 0.1,
    });
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    if (errMsg.includes("413") || errMsg.includes("rate_limit") || errMsg.includes("too large")) {
      // Fallback with minimal context if token limit hit
      promptFiles = buildPromptFiles(7000, 1200);
      userPrompt = `REPOSITORY: ${repoName}\nTOTAL FILES: ${Object.keys(filesContent).length}\n\n${ANALYSIS_INSTRUCTIONS}\n\nREPOSITORY SOURCE CODE:\n${promptFiles}`;
      completion = await groq.chat.completions.create({
        model,
        messages: [
          { role: "system", content: ANALYSIS_SYSTEM },
          { role: "user", content: userPrompt },
        ],
        max_tokens: 3000,
        temperature: 0.1,
      });
    } else {
      throw err;
    }
  }

  const content = completion.choices[0]?.message?.content || "";
  const usage = completion.usage;

  return {
    reportMarkdown: content,
    findings: extractFindings(content),
    overallScore: extractScore(content),
    tokenUsage: {
      promptTokens: usage?.prompt_tokens || 0,
      completionTokens: usage?.completion_tokens || 0,
      totalTokens: usage?.total_tokens || 0,
    },
    model,
  };
}

// ----------------------------------------------------------------
// Grounded RAG Chat
// ----------------------------------------------------------------

export async function chatWithRepository(
  question: string,
  retrievedChunks: CodeChunk[],
  conversationHistory: Array<{ role: "user" | "assistant"; content: string }>,
  model: string
): Promise<string> {
  const groq = getGroqClient();

  const contextParts = retrievedChunks
    .slice(0, 5)
    .map(
      (c, i) =>
        `[${i + 1}] File: ${c.filename} (Chunk ${c.chunkIndex})\n${c.content.slice(0, 1500)}`
    )
    .join(`\n\n${"=".repeat(50)}\n`);

  const systemPrompt = `You are an expert GitHub Repository Assistant.
Answer ONLY from the provided code context. Never hallucinate.
If context is insufficient, say: "I couldn't find that information in the indexed repository."
Always cite filenames and function names from the context.`;

  const userContent = `REPOSITORY CODE CONTEXT:\n${contextParts}\n\nUSER QUESTION:\n${question}`;

  const messages: Groq.Chat.Completions.ChatCompletionMessageParam[] = [
    ...conversationHistory.slice(-6).map((m) => ({
      role: m.role,
      content: m.content,
    })),
    { role: "user", content: userContent },
  ];

  const completion = await groq.chat.completions.create({
    model,
    messages: [{ role: "system", content: systemPrompt }, ...messages],
    max_tokens: 2048,
    temperature: 0.1,
  });

  return (
    completion.choices[0]?.message?.content ||
    "I couldn't find that information in the indexed repository."
  );
}

// ----------------------------------------------------------------
// Patch generation
// ----------------------------------------------------------------

export async function generatePatch(
  filePath: string,
  currentContent: string,
  issueDescription: string,
  model: string
): Promise<{ explanation: string; proposedCode: string; diff: string }> {
  const groq = getGroqClient();

  const prompt = `Generate a targeted code fix for the issue described.

FILE: ${filePath}
ISSUE: ${issueDescription}

CURRENT CODE:
\`\`\`
${currentContent.slice(0, 10000)}
\`\`\`

Respond with exactly these three sections:
### EXPLANATION
(brief explanation)
### PROPOSED CODE
\`\`\`
(replacement code)
\`\`\`
### UNIFIED DIFF
\`\`\`diff
(unified diff)
\`\`\``;

  const completion = await groq.chat.completions.create({
    model,
    messages: [
      { role: "system", content: "You are an expert automated code repair system." },
      { role: "user", content: prompt },
    ],
    max_tokens: 2048,
    temperature: 0.1,
  });

  const content = completion.choices[0]?.message?.content || "";

  const stripFences = (s: string) => {
    const lines = s.trim().split("\n");
    if (lines[0].startsWith("```") && lines[lines.length - 1].startsWith("```")) {
      return lines.slice(1, -1).join("\n").trim();
    }
    return s.trim();
  };

  let explanation = "";
  let proposedCode = "";
  let diff = "";

  if (content.includes("### EXPLANATION")) {
    const ep = content.split("### EXPLANATION")[1];
    if (ep.includes("### PROPOSED CODE")) {
      const [e, rest] = ep.split("### PROPOSED CODE");
      explanation = e.trim();
      if (rest.includes("### UNIFIED DIFF")) {
        const [p, d] = rest.split("### UNIFIED DIFF");
        proposedCode = stripFences(p);
        diff = stripFences(d);
      } else {
        proposedCode = stripFences(rest);
      }
    } else {
      explanation = ep.trim();
    }
  } else {
    explanation = content;
  }

  return { explanation, proposedCode, diff };
}

export { redactSecrets };

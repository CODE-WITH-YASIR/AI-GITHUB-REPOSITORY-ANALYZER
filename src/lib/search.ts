/**
 * Client-side keyword search for RAG.
 * Runs entirely in the browser on stored chunks — no API calls needed.
 */

import type { CodeChunk, SearchResult } from "./types";

function tokenize(text: string): Set<string> {
  // Split on any non-alphanumeric character (including underscores) and extract sub-tokens
  const rawTokens = text.toLowerCase().match(/[a-z0-9]+/g) || [];
  return new Set(rawTokens.filter((t) => t.length > 1));
}

function intersection<T>(a: Set<T>, b: Set<T>): Set<T> {
  const result = new Set<T>();
  for (const item of a) if (b.has(item)) result.add(item);
  return result;
}

export function searchChunks(
  query: string,
  chunks: CodeChunk[],
  topK: number = 6
): SearchResult[] {
  if (!query.trim() || chunks.length === 0) return [];

  const queryTokens = tokenize(query);
  if (queryTokens.size === 0) return [];

  const scored: SearchResult[] = chunks.map((chunk) => {
    const docTokens = tokenize(chunk.content);
    const fnTokens = tokenize(chunk.filename);

    const docOverlap =
      intersection(queryTokens, docTokens).size / queryTokens.size;
    const fnOverlap =
      intersection(queryTokens, fnTokens).size / queryTokens.size;

    const score = docOverlap + fnOverlap * 0.8;
    return { chunk, score };
  });

  return scored
    .sort((a, b) => b.score - a.score)
    .slice(0, topK)
    .filter((r) => r.score > 0);
}

export function filterChunksByFile(
  chunks: CodeChunk[],
  filePattern: string
): CodeChunk[] {
  if (!filePattern.trim()) return chunks;
  const lower = filePattern.toLowerCase();
  return chunks.filter((c) => c.filename.toLowerCase().includes(lower));
}

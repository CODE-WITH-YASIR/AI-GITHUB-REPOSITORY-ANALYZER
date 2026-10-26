/**
 * POST /api/analyze
 * Streams Server-Sent Events for real-time pipeline progress.
 * Fetches GitHub files, runs Groq analysis, returns chunks + findings.
 * GROQ_API_KEY and GITHUB_TOKEN are read server-side only.
 */
import { NextRequest } from "next/server";
import {
  fetchRepoMetadata,
  fetchRepoFiles,
  fetchFileContent,
  buildChunks,
} from "@/lib/github";
import {
  analyzeRepository,
  getModel,
  redactSecrets,
} from "@/lib/groq-server";
import type { StreamEvent } from "@/lib/types";

export const maxDuration = 60; // Vercel Pro: up to 300s; Hobby: capped at 60s

export async function POST(request: NextRequest) {
  const { repoUrl } = (await request.json()) as { repoUrl: string };

  const encoder = new TextEncoder();

  const stream = new ReadableStream({
    async start(controller) {
      const send = (event: StreamEvent) => {
        try {
          controller.enqueue(
            encoder.encode(`data: ${JSON.stringify(event)}\n\n`)
          );
        } catch {
          // controller may be closed
        }
      };

      try {
        if (!repoUrl?.trim()) {
          send({ stage: "error", progress: 0, message: "Repository URL is required.", error: "Empty URL" });
          controller.close();
          return;
        }

        // Stage 1: Validation & Metadata
        send({ stage: "validation", progress: 5, message: "Connecting to GitHub and validating repository..." });
        const meta = await fetchRepoMetadata(repoUrl);

        send({ stage: "validation", progress: 15, message: `Repository found: ${meta.fullName} (branch: ${meta.defaultBranch})` });

        // Stage 2: File Discovery
        send({ stage: "discovery", progress: 20, message: `Discovering source files on branch '${meta.defaultBranch}'...` });
        const fileList = await fetchRepoFiles(meta.owner, meta.repo, meta.defaultBranch);

        if (fileList.length === 0) {
          send({ stage: "error", progress: 0, message: "No supported source files found in this repository.", error: "No files" });
          controller.close();
          return;
        }

        send({ stage: "discovery", progress: 30, message: `Found ${fileList.length} source files. Beginning content ingestion...` });

        // Stage 3: Content Ingestion (parallel batches)
        const filesContent: Record<string, string> = {};
        const batchSize = 8;

        for (let i = 0; i < fileList.length; i += batchSize) {
          const batch = fileList.slice(i, i + batchSize);
          const results = await Promise.allSettled(
            batch.map((fpath) =>
              fetchFileContent(meta.owner, meta.repo, meta.defaultBranch, fpath)
            )
          );

          results.forEach((res, idx) => {
            if (res.status === "fulfilled" && res.value?.trim()) {
              filesContent[batch[idx]] = res.value;
            }
          });

          const pct = 30 + Math.floor((35 * (i + batch.length)) / fileList.length);
          send({
            stage: "ingestion",
            progress: pct,
            message: `Ingested ${Object.keys(filesContent).length} files so far...`,
          });
        }

        if (Object.keys(filesContent).length === 0) {
          send({ stage: "error", progress: 0, message: "Could not read any file contents from this repository.", error: "No content" });
          controller.close();
          return;
        }

        // Stage 4: Chunking
        send({ stage: "ingestion", progress: 68, message: `Building ${Object.keys(filesContent).length} file index...` });
        const chunks = buildChunks(filesContent);

        // Stage 5: Groq Analysis
        const model = getModel();
        send({ stage: "analysis", progress: 72, message: `Executing deep audit with Groq (${model})...` });

        const analysis = await analyzeRepository(filesContent, meta.fullName, model);

        send({
          stage: "complete",
          progress: 100,
          message: `Analysis complete! ${Object.keys(filesContent).length} files, ${chunks.length} chunks, ${analysis.findings.length} findings.`,
          result: {
            metadata: meta,
            chunks,
            filesCount: Object.keys(filesContent).length,
            analysis: {
              reportMarkdown: analysis.reportMarkdown,
              findings: analysis.findings,
              overallScore: analysis.overallScore,
              model: analysis.model,
              tokenUsage: analysis.tokenUsage,
            },
          },
        });

        controller.close();
      } catch (err: unknown) {
        const msg = redactSecrets(err instanceof Error ? err.message : String(err));
        send({ stage: "error", progress: 0, message: msg, error: msg });
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}

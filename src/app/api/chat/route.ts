/**
 * POST /api/chat
 * Grounded RAG Chat with Groq.
 * Accepts user question, retrieved code chunks, and conversation history.
 */
import { NextRequest, NextResponse } from "next/server";
import { chatWithRepository, getModel, redactSecrets } from "@/lib/groq-server";
import type { CodeChunk } from "@/lib/types";

export const maxDuration = 30;

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { question, chunks, history, model } = body as {
      question: string;
      chunks: CodeChunk[];
      history?: Array<{ role: "user" | "assistant"; content: string }>;
      model?: string;
    };

    if (!question?.trim()) {
      return NextResponse.json({ error: "Question is required." }, { status: 400 });
    }

    const selectedModel = model?.trim() || getModel();
    const answer = await chatWithRepository(
      question,
      chunks || [],
      history || [],
      selectedModel
    );

    return NextResponse.json({
      answer: redactSecrets(answer),
      model: selectedModel,
      sourcesCount: (chunks || []).length,
    });
  } catch (err: unknown) {
    const msg = redactSecrets(err instanceof Error ? err.message : String(err));
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}

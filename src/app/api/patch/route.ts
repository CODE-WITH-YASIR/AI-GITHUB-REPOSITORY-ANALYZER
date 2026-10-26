/**
 * POST /api/patch
 * Automated Patch Generation with Groq.
 * Takes a file path, current snippet/content, issue description, and generates a structured diff and remediation.
 */
import { NextRequest, NextResponse } from "next/server";
import { generatePatch, getModel, redactSecrets } from "@/lib/groq-server";

export const maxDuration = 30;

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { filePath, currentContent, issueDescription, model } = body as {
      filePath: string;
      currentContent: string;
      issueDescription: string;
      model?: string;
    };

    if (!filePath || !issueDescription) {
      return NextResponse.json(
        { error: "filePath and issueDescription are required." },
        { status: 400 }
      );
    }

    const selectedModel = model?.trim() || getModel();
    const patch = await generatePatch(
      filePath,
      currentContent || "",
      issueDescription,
      selectedModel
    );

    return NextResponse.json({
      explanation: redactSecrets(patch.explanation),
      proposedCode: redactSecrets(patch.proposedCode),
      diff: redactSecrets(patch.diff),
      model: selectedModel,
    });
  } catch (err: unknown) {
    const msg = redactSecrets(err instanceof Error ? err.message : String(err));
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}

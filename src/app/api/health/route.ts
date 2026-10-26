// Health check API route
import { NextResponse } from "next/server";

export async function GET() {
  const groqKey = process.env.GROQ_API_KEY;
  const githubToken = process.env.GITHUB_TOKEN;

  return NextResponse.json({
    status: "ok",
    timestamp: new Date().toISOString(),
    groq: {
      configured: Boolean(groqKey && groqKey.length > 10),
      model: process.env.GROQ_MODEL || "qwen/qwen3.8-27b",
    },
    github: {
      authenticated: Boolean(githubToken && githubToken.length > 10),
    },
  });
}

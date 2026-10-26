// ====================================================================
// TypeScript Types for AI GitHub Repository Analyzer
// ====================================================================

export interface RepoMetadata {
  owner: string;
  repo: string;
  fullName: string;
  defaultBranch: string;
  description: string;
  language: string;
  stars: number;
  forks: number;
  openIssues: number;
  htmlUrl: string;
}

export interface CodeChunk {
  id: string;
  filename: string;
  chunkIndex: number;
  content: string;
  contentHash: string;
  fileExt: string;
}

export interface Finding {
  id: string;
  title: string;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";
  category: "SECURITY" | "BUG" | "PERFORMANCE" | "QUALITY" | "ARCHITECTURE";
  filePath: string;
  lineReference: string;
  evidence: string;
  explanation: string;
  impact: string;
  remediation: string;
  confidence: "HIGH" | "MEDIUM" | "LOW";
  isConfirmed: boolean;
}

export interface AnalysisResult {
  reportMarkdown: string;
  findings: Finding[];
  overallScore: number;
  model: string;
  tokenUsage: { promptTokens: number; completionTokens: number; totalTokens: number };
}

export interface AnalysisPayload {
  metadata: RepoMetadata;
  chunks: CodeChunk[];
  filesCount: number;
  analysis: AnalysisResult;
}

export interface StreamEvent {
  stage: "validation" | "discovery" | "ingestion" | "analysis" | "complete" | "error";
  progress: number;
  message: string;
  result?: AnalysisPayload;
  error?: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  sources?: Array<{ filename: string; chunkIndex: number; score: number }>;
  timestamp: number;
}

export interface SearchResult {
  chunk: CodeChunk;
  score: number;
}

export type AppPage =
  | "overview"
  | "analysis"
  | "report"
  | "explorer"
  | "chat"
  | "settings";

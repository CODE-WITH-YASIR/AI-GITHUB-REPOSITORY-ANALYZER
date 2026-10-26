"use client";

import React, { useState, useEffect, useRef } from "react";
import type {
  RepoMetadata,
  CodeChunk,
  Finding,
  AnalysisPayload,
  StreamEvent,
  ChatMessage,
  AppPage,
} from "@/lib/types";
import { searchChunks, filterChunksByFile } from "@/lib/search";

export default function Home() {
  // Navigation & View
  const [activeTab, setActiveTab] = useState<AppPage>("overview");

  // Repository input & state
  const [repoUrl, setRepoUrl] = useState<string>("");
  const [isAnalyzing, setIsAnalyzing] = useState<boolean>(false);
  const [pipelineProgress, setPipelineProgress] = useState<number>(0);
  const [pipelineStatus, setPipelineStatus] = useState<string>("");
  const [errorMessage, setErrorMessage] = useState<string>("");

  // Analyzed Repository Data
  const [metadata, setMetadata] = useState<RepoMetadata | null>(null);
  const [chunks, setChunks] = useState<CodeChunk[]>([]);
  const [analysisResult, setAnalysisResult] = useState<AnalysisPayload["analysis"] | null>(null);
  const [filesCount, setFilesCount] = useState<number>(0);

  // Findings Filters
  const [severityFilter, setSeverityFilter] = useState<string>("ALL");
  const [categoryFilter, setCategoryFilter] = useState<string>("ALL");
  const [searchFilter, setSearchFilter] = useState<string>("");
  const [expandedFindings, setExpandedFindings] = useState<Record<string, boolean>>({});

  // Patch State
  const [patchLoadingId, setPatchLoadingId] = useState<string | null>(null);
  const [activePatch, setActivePatch] = useState<{
    id: string;
    explanation: string;
    proposedCode: string;
    diff: string;
  } | null>(null);

  // RAG Explorer
  const [explorerQuery, setExplorerQuery] = useState<string>("");
  const [explorerFileFilter, setExplorerFileFilter] = useState<string>("");

  // Chat State
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState<string>("");
  const [isChatLoading, setIsChatLoading] = useState<boolean>(false);
  const chatBottomRef = useRef<HTMLDivElement>(null);

  // Telemetry & Health
  const [healthStatus, setHealthStatus] = useState<Record<string, unknown> | null>(null);
  const [selectedModel, setSelectedModel] = useState<string>("qwen/qwen3.8-27b");

  // Check health on mount
  useEffect(() => {
    fetch("/api/health")
      .then((res) => res.json())
      .then((data) => {
        setHealthStatus(data);
        if (data.groq?.model) setSelectedModel(data.groq.model);
      })
      .catch(() => {});
  }, []);

  // Scroll chat to bottom
  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages, isChatLoading]);

  // Handle repository analysis via SSE
  const handleAnalyze = async (urlToAnalyze?: string) => {
    const targetUrl = (urlToAnalyze || repoUrl).trim();
    if (!targetUrl) {
      setErrorMessage("Please enter a valid GitHub repository URL.");
      return;
    }

    setErrorMessage("");
    setIsAnalyzing(true);
    setPipelineProgress(5);
    setPipelineStatus("Connecting to repository...");

    try {
      const response = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repoUrl: targetUrl }),
      });

      if (!response.ok || !response.body) {
        throw new Error(`Server returned error HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (trimmed.startsWith("data:")) {
            try {
              const eventData: StreamEvent = JSON.parse(trimmed.slice(5).trim());
              setPipelineProgress(eventData.progress);
              setPipelineStatus(eventData.message);

              if (eventData.stage === "complete" && eventData.result) {
                const res = eventData.result;
                setMetadata(res.metadata);
                setChunks(res.chunks);
                setFilesCount(res.filesCount);
                setAnalysisResult(res.analysis);
                setActiveTab("overview");
                setIsAnalyzing(false);
              } else if (eventData.stage === "error") {
                setErrorMessage(eventData.error || eventData.message);
                setIsAnalyzing(false);
              }
            } catch {
              // ignore partial json
            }
          }
        }
      }
    } catch (err: unknown) {
      setErrorMessage(err instanceof Error ? err.message : "Failed to analyze repository.");
      setIsAnalyzing(false);
    }
  };

  // Handle RAG Chat
  const handleSendMessage = async (e?: React.FormEvent, directMessage?: string) => {
    if (e) e.preventDefault();
    const query = (directMessage || chatInput).trim();
    if (!query || isChatLoading) return;

    setChatInput("");
    const newHistory: ChatMessage[] = [
      ...chatMessages,
      { role: "user", content: query, timestamp: Date.now() },
    ];
    setChatMessages(newHistory);
    setIsChatLoading(true);

    try {
      // Retrieve top chunks from client-side vector store
      const retrieved = searchChunks(query, chunks, 6);
      const retrievedChunks = retrieved.map((r) => r.chunk);

      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: query,
          chunks: retrievedChunks,
          history: newHistory.slice(-6).map((m) => ({ role: m.role, content: m.content })),
          model: selectedModel,
        }),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed to get response");

      setChatMessages([
        ...newHistory,
        {
          role: "assistant",
          content: data.answer,
          sources: retrieved.map((r) => ({
            filename: r.chunk.filename,
            chunkIndex: r.chunk.chunkIndex,
            score: Math.round(r.score * 100) / 100,
          })),
          timestamp: Date.now(),
        },
      ]);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Error generating answer";
      setChatMessages([
        ...newHistory,
        { role: "assistant", content: `⚠️ Error: ${msg}`, timestamp: Date.now() },
      ]);
    } finally {
      setIsChatLoading(false);
    }
  };

  // Generate automated patch
  const handleGeneratePatch = async (finding: Finding) => {
    setPatchLoadingId(finding.id);
    try {
      const fileChunk = chunks.find((c) => c.filename === finding.filePath);
      const res = await fetch("/api/patch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          filePath: finding.filePath,
          currentContent: fileChunk?.content || finding.evidence,
          issueDescription: `${finding.title}: ${finding.explanation}. Remediation: ${finding.remediation}`,
          model: selectedModel,
        }),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Patch generation failed");

      setActivePatch({
        id: finding.id,
        explanation: data.explanation,
        proposedCode: data.proposedCode,
        diff: data.diff,
      });
    } catch (err: unknown) {
      alert(`Patch error: ${err instanceof Error ? err.message : "Unknown error"}`);
    } finally {
      setPatchLoadingId(null);
    }
  };

  // Filtered Findings
  const filteredFindings = (analysisResult?.findings || []).filter((f) => {
    if (severityFilter !== "ALL" && f.severity !== severityFilter) return false;
    if (categoryFilter !== "ALL" && f.category !== categoryFilter) return false;
    if (searchFilter) {
      const q = searchFilter.toLowerCase();
      return (
        f.title.toLowerCase().includes(q) ||
        f.filePath.toLowerCase().includes(q) ||
        f.explanation.toLowerCase().includes(q)
      );
    }
    return true;
  });

  // Filtered RAG chunks
  const searchedChunks = explorerQuery
    ? searchChunks(explorerQuery, filterChunksByFile(chunks, explorerFileFilter), 12).map(
        (r) => r.chunk
      )
    : filterChunksByFile(chunks, explorerFileFilter).slice(0, 15);

  return (
    <div style={{ maxWidth: 1280, margin: "0 auto", padding: "24px 20px 80px" }}>
      {/* HEADER NAVBAR */}
      <header
        className="glass-panel"
        style={{
          padding: "16px 24px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 24,
          flexWrap: "wrap",
          gap: 16,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div
            style={{
              width: 42,
              height: 42,
              borderRadius: 12,
              background: "linear-gradient(135deg, #06b6d4 0%, #6366f1 100%)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 22,
              boxShadow: "0 0 20px rgba(99, 102, 241, 0.4)",
            }}
          >
            🛡️
          </div>
          <div>
            <h1 style={{ fontSize: "1.25rem", fontWeight: 800, letterSpacing: "-0.02em" }}>
              AI GitHub Repository Analyzer
            </h1>
            <p style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
              Deep Code & Security Audits • Powered by Groq LPU
            </p>
          </div>
        </div>

        {/* Global Navigation Tabs */}
        <nav style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {[
            { id: "overview", label: "Overview", icon: "📊" },
            { id: "analysis", label: `Findings (${analysisResult?.findings.length || 0})`, icon: "🔍" },
            { id: "report", label: "Full Audit Report", icon: "📑" },
            { id: "explorer", label: `Code Explorer (${chunks.length})`, icon: "🧩" },
            { id: "chat", label: "Repository Chat", icon: "💬" },
            { id: "settings", label: "Telemetry", icon: "⚙️" },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as AppPage)}
              style={{
                background: activeTab === tab.id ? "rgba(99, 102, 241, 0.25)" : "transparent",
                border:
                  activeTab === tab.id
                    ? "1px solid rgba(99, 102, 241, 0.5)"
                    : "1px solid transparent",
                color: activeTab === tab.id ? "#ffffff" : "var(--text-secondary)",
                borderRadius: 10,
                padding: "8px 14px",
                fontSize: "0.85rem",
                fontWeight: 600,
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                transition: "all 0.15s ease",
              }}
            >
              <span>{tab.icon}</span>
              <span>{tab.label}</span>
            </button>
          ))}
        </nav>
      </header>

      {/* INPUT & ANALYZE HERO */}
      <section className="glass-panel" style={{ padding: 28, marginBottom: 28 }}>
        <h2 style={{ fontSize: "1.1rem", fontWeight: 700, marginBottom: 8 }}>
          🔗 Enter a GitHub Repository
        </h2>
        <p style={{ fontSize: "0.88rem", color: "var(--text-secondary)", marginBottom: 16 }}>
          Analyze public repositories for architecture flaws, security vulnerabilities, code smells,
          and performance bottlenecks.
        </p>

        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <input
            type="text"
            className="glass-input"
            style={{ flex: 1, minWidth: 280 }}
            placeholder="https://github.com/owner/repository"
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            disabled={isAnalyzing}
            onKeyDown={(e) => e.key === "Enter" && handleAnalyze()}
          />
          <button
            className="glass-button"
            onClick={() => handleAnalyze()}
            disabled={isAnalyzing}
            style={{ minWidth: 180 }}
          >
            {isAnalyzing ? "Analyzing Repository..." : "🚀 Analyze Repository"}
          </button>
        </div>

        {/* Quick Sample Selectors */}
        <div style={{ display: "flex", gap: 8, marginTop: 14, alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>Quick samples:</span>
          {[
            "https://github.com/CODE-WITH-YASIR/AI-GITHUB-REPOSITORY-ANALYZER",
            "https://github.com/fastapi/fastapi",
            "https://github.com/psf/requests",
          ].map((sample) => (
            <button
              key={sample}
              onClick={() => {
                setRepoUrl(sample);
                handleAnalyze(sample);
              }}
              disabled={isAnalyzing}
              className="glass-button-secondary"
              style={{
                fontSize: "0.75rem",
                padding: "4px 10px",
                borderRadius: 8,
                cursor: "pointer",
              }}
            >
              {sample.split("/").slice(-2).join("/")}
            </button>
          ))}
        </div>

        {/* Real-time Streaming Progress */}
        {isAnalyzing && (
          <div style={{ marginTop: 24 }}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                marginBottom: 6,
                fontSize: "0.85rem",
              }}
            >
              <span style={{ color: "var(--accent-cyan)", fontWeight: 600 }}>
                {pipelineStatus || "Processing..."}
              </span>
              <span style={{ color: "var(--text-muted)" }}>{pipelineProgress}%</span>
            </div>
            <div
              style={{
                width: "100%",
                height: 8,
                background: "rgba(255, 255, 255, 0.08)",
                borderRadius: 4,
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: `${pipelineProgress}%`,
                  height: "100%",
                  background: "linear-gradient(90deg, #06b6d4, #6366f1, #8b5cf6)",
                  transition: "width 0.3s ease",
                }}
              />
            </div>
          </div>
        )}

        {/* Error notification */}
        {errorMessage && (
          <div
            style={{
              marginTop: 16,
              padding: "12px 16px",
              borderRadius: 10,
              background: "rgba(244, 63, 94, 0.15)",
              border: "1px solid rgba(244, 63, 94, 0.3)",
              color: "#fb7185",
              fontSize: "0.88rem",
            }}
          >
            ⚠️ {errorMessage}
          </div>
        )}
      </section>

      {/* REPOSITORY METADATA STATS BANNER */}
      {metadata && (
        <section
          className="glass-panel"
          style={{
            padding: "20px 24px",
            marginBottom: 28,
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
            gap: 20,
          }}
        >
          <div>
            <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>
              Repository
            </span>
            <div style={{ fontSize: "1.1rem", fontWeight: 700, marginTop: 4 }}>
              <a
                href={metadata.htmlUrl}
                target="_blank"
                rel="noreferrer"
                style={{ color: "var(--accent-cyan)", textDecoration: "none" }}
              >
                {metadata.fullName} ↗
              </a>
            </div>
            <span style={{ fontSize: "0.8rem", color: "var(--text-secondary)" }}>
              branch: <code>{metadata.defaultBranch}</code>
            </span>
          </div>

          <div>
            <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>
              Audit Health Score
            </span>
            <div
              style={{
                fontSize: "1.5rem",
                fontWeight: 800,
                marginTop: 2,
                color:
                  (analysisResult?.overallScore || 0) >= 8
                    ? "var(--accent-emerald)"
                    : (analysisResult?.overallScore || 0) >= 6
                    ? "var(--accent-amber)"
                    : "var(--accent-rose)",
              }}
            >
              {analysisResult?.overallScore.toFixed(1)} / 10.0
            </div>
            <span style={{ fontSize: "0.78rem", color: "var(--text-secondary)" }}>
              Based on {analysisResult?.findings.length || 0} findings
            </span>
          </div>

          <div>
            <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>
              Files & Indexing
            </span>
            <div style={{ fontSize: "1.2rem", fontWeight: 700, marginTop: 4 }}>
              {filesCount} files analyzed
            </div>
            <span style={{ fontSize: "0.78rem", color: "var(--text-secondary)" }}>
              {chunks.length} RAG vectors indexed
            </span>
          </div>

          <div>
            <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase" }}>
              GitHub Activity
            </span>
            <div style={{ fontSize: "0.95rem", fontWeight: 600, marginTop: 6 }}>
              ⭐ {metadata.stars.toLocaleString()} • 🍴 {metadata.forks.toLocaleString()} • ⚠️{" "}
              {metadata.openIssues} issues
            </div>
            <span style={{ fontSize: "0.78rem", color: "var(--text-secondary)" }}>
              Language: {metadata.language}
            </span>
          </div>
        </section>
      )}

      {/* TAB 1: OVERVIEW */}
      {activeTab === "overview" && (
        <div>
          {!metadata ? (
            <div
              className="glass-panel"
              style={{ padding: 48, textAlign: "center", color: "var(--text-secondary)" }}
            >
              <div style={{ fontSize: 48, marginBottom: 16 }}>🚀</div>
              <h3 style={{ fontSize: "1.2rem", color: "var(--text-primary)", marginBottom: 8 }}>
                No Repository Analyzed Yet
              </h3>
              <p style={{ maxWidth: 500, margin: "0 auto", fontSize: "0.9rem" }}>
                Enter a GitHub repository URL above and click <strong>Analyze Repository</strong> to
                perform an architectural and security audit.
              </p>
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 24 }}>
              {/* Executive Summary Card */}
              <div className="glass-panel" style={{ padding: 24 }}>
                <h3 style={{ fontSize: "1.1rem", fontWeight: 700, marginBottom: 12 }}>
                  📋 Executive Overview
                </h3>
                <p style={{ color: "var(--text-secondary)", lineHeight: 1.6, fontSize: "0.95rem" }}>
                  {metadata.description || "No public repository description provided on GitHub."}
                </p>
              </div>

              {/* Findings Summary Matrix */}
              <div className="glass-panel" style={{ padding: 24 }}>
                <h3 style={{ fontSize: "1.1rem", fontWeight: 700, marginBottom: 16 }}>
                  🛡️ Audit Findings Summary
                </h3>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
                    gap: 12,
                  }}
                >
                  {[
                    {
                      label: "Critical",
                      count: (analysisResult?.findings || []).filter((f) => f.severity === "CRITICAL")
                        .length,
                      cls: "badge-critical",
                    },
                    {
                      label: "High",
                      count: (analysisResult?.findings || []).filter((f) => f.severity === "HIGH")
                        .length,
                      cls: "badge-high",
                    },
                    {
                      label: "Medium",
                      count: (analysisResult?.findings || []).filter((f) => f.severity === "MEDIUM")
                        .length,
                      cls: "badge-medium",
                    },
                    {
                      label: "Low",
                      count: (analysisResult?.findings || []).filter((f) => f.severity === "LOW")
                        .length,
                      cls: "badge-low",
                    },
                    {
                      label: "Info",
                      count: (analysisResult?.findings || []).filter((f) => f.severity === "INFO")
                        .length,
                      cls: "badge-info",
                    },
                  ].map((s) => (
                    <div
                      key={s.label}
                      style={{
                        padding: 16,
                        background: "rgba(255, 255, 255, 0.03)",
                        borderRadius: 12,
                        border: "1px solid rgba(255, 255, 255, 0.06)",
                        textAlign: "center",
                      }}
                    >
                      <span className={`badge ${s.cls}`}>{s.label}</span>
                      <div style={{ fontSize: "1.6rem", fontWeight: 800, marginTop: 8 }}>
                        {s.count}
                      </div>
                    </div>
                  ))}
                </div>
                <div style={{ marginTop: 20, textAlign: "right" }}>
                  <button
                    className="glass-button"
                    onClick={() => setActiveTab("analysis")}
                    style={{ fontSize: "0.85rem", padding: "8px 16px" }}
                  >
                    View All Findings →
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB 2: FINDINGS (SECURITY & BUGS) */}
      {activeTab === "analysis" && (
        <div>
          {/* Filter Bar */}
          <div
            className="glass-panel"
            style={{
              padding: 16,
              marginBottom: 20,
              display: "flex",
              gap: 12,
              flexWrap: "wrap",
              alignItems: "center",
            }}
          >
            <input
              type="text"
              placeholder="Filter findings by keyword..."
              className="glass-input"
              style={{ flex: 1, minWidth: 200, padding: "8px 12px", fontSize: "0.85rem" }}
              value={searchFilter}
              onChange={(e) => setSearchFilter(e.target.value)}
            />

            <select
              className="glass-input"
              style={{ width: "auto", padding: "8px 12px", fontSize: "0.85rem" }}
              value={severityFilter}
              onChange={(e) => setSeverityFilter(e.target.value)}
            >
              <option value="ALL">All Severities</option>
              <option value="CRITICAL">Critical</option>
              <option value="HIGH">High</option>
              <option value="MEDIUM">Medium</option>
              <option value="LOW">Low</option>
              <option value="INFO">Info</option>
            </select>

            <select
              className="glass-input"
              style={{ width: "auto", padding: "8px 12px", fontSize: "0.85rem" }}
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
            >
              <option value="ALL">All Categories</option>
              <option value="SECURITY">Security</option>
              <option value="BUG">Bug</option>
              <option value="PERFORMANCE">Performance</option>
              <option value="QUALITY">Quality</option>
              <option value="ARCHITECTURE">Architecture</option>
            </select>
          </div>

          {/* Findings List */}
          {filteredFindings.length === 0 ? (
            <div className="glass-panel" style={{ padding: 40, textAlign: "center", color: "var(--text-secondary)" }}>
              No findings match your filter criteria.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              {filteredFindings.map((finding) => {
                const isExpanded = Boolean(expandedFindings[finding.id]);
                const badgeClass =
                  finding.severity === "CRITICAL"
                    ? "badge-critical"
                    : finding.severity === "HIGH"
                    ? "badge-high"
                    : finding.severity === "MEDIUM"
                    ? "badge-medium"
                    : finding.severity === "LOW"
                    ? "badge-low"
                    : "badge-info";

                return (
                  <div
                    key={finding.id}
                    className="glass-panel glass-panel-hover"
                    style={{ padding: 20 }}
                  >
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "flex-start",
                        gap: 12,
                        cursor: "pointer",
                      }}
                      onClick={() =>
                        setExpandedFindings((prev) => ({ ...prev, [finding.id]: !isExpanded }))
                      }
                    >
                      <div>
                        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
                          <span className={`badge ${badgeClass}`}>{finding.severity}</span>
                          <span className="badge badge-category">{finding.category}</span>
                          {finding.isConfirmed && (
                            <span
                              style={{
                                fontSize: "0.7rem",
                                color: "var(--accent-rose)",
                                fontWeight: 600,
                              }}
                            >
                              ● Confirmed Issue
                            </span>
                          )}
                        </div>
                        <h4 style={{ fontSize: "1rem", fontWeight: 700, color: "#ffffff" }}>
                          {finding.title}
                        </h4>
                        <div
                          style={{
                            fontSize: "0.8rem",
                            color: "var(--accent-cyan)",
                            marginTop: 4,
                            fontFamily: "var(--font-mono)",
                          }}
                        >
                          {finding.filePath} {finding.lineReference ? `(${finding.lineReference})` : ""}
                        </div>
                      </div>

                      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <button
                          className="glass-button-secondary"
                          style={{ fontSize: "0.75rem", padding: "6px 12px", borderRadius: 8 }}
                          onClick={(e) => {
                            e.stopPropagation();
                            handleGeneratePatch(finding);
                          }}
                          disabled={patchLoadingId === finding.id}
                        >
                          {patchLoadingId === finding.id ? "Generating..." : "⚡ Generate AI Patch"}
                        </button>
                        <span style={{ color: "var(--text-muted)", fontSize: "1.2rem" }}>
                          {isExpanded ? "▲" : "▼"}
                        </span>
                      </div>
                    </div>

                    {/* Expandable details */}
                    {isExpanded && (
                      <div
                        style={{
                          marginTop: 16,
                          paddingTop: 16,
                          borderTop: "1px solid rgba(255, 255, 255, 0.08)",
                          display: "flex",
                          flexDirection: "column",
                          gap: 12,
                        }}
                      >
                        <div>
                          <strong style={{ fontSize: "0.85rem", color: "var(--text-primary)" }}>
                            Explanation:
                          </strong>
                          <p style={{ fontSize: "0.88rem", color: "var(--text-secondary)", marginTop: 4 }}>
                            {finding.explanation}
                          </p>
                        </div>

                        {finding.evidence && (
                          <div>
                            <strong style={{ fontSize: "0.85rem", color: "var(--text-primary)" }}>
                              Code Evidence:
                            </strong>
                            <pre style={{ marginTop: 4 }}>{finding.evidence}</pre>
                          </div>
                        )}

                        {finding.impact && (
                          <div>
                            <strong style={{ fontSize: "0.85rem", color: "var(--accent-amber)" }}>
                              Production Impact:
                            </strong>
                            <p style={{ fontSize: "0.88rem", color: "var(--text-secondary)", marginTop: 4 }}>
                              {finding.impact}
                            </p>
                          </div>
                        )}

                        {finding.remediation && (
                          <div
                            style={{
                              padding: 12,
                              borderRadius: 8,
                              background: "rgba(16, 185, 129, 0.1)",
                              border: "1px solid rgba(16, 185, 129, 0.25)",
                            }}
                          >
                            <strong style={{ fontSize: "0.85rem", color: "var(--accent-emerald)" }}>
                              Suggested Remediation:
                            </strong>
                            <p style={{ fontSize: "0.88rem", color: "#e2e8f0", marginTop: 4 }}>
                              {finding.remediation}
                            </p>
                          </div>
                        )}

                        {/* Active Patch Display */}
                        {activePatch?.id === finding.id && (
                          <div
                            style={{
                              marginTop: 12,
                              padding: 16,
                              borderRadius: 12,
                              background: "rgba(99, 102, 241, 0.1)",
                              border: "1px solid rgba(99, 102, 241, 0.3)",
                            }}
                          >
                            <div
                              style={{
                                display: "flex",
                                justifyContent: "space-between",
                                alignItems: "center",
                                marginBottom: 8,
                              }}
                            >
                              <strong style={{ color: "var(--accent-indigo)", fontSize: "0.9rem" }}>
                                ⚡ Groq Generated Remediation Patch
                              </strong>
                              <button
                                onClick={() => setActivePatch(null)}
                                style={{
                                  background: "none",
                                  border: "none",
                                  color: "var(--text-muted)",
                                  cursor: "pointer",
                                }}
                              >
                                ✕
                              </button>
                            </div>
                            <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: 8 }}>
                              {activePatch.explanation}
                            </p>
                            {activePatch.diff && (
                              <pre style={{ background: "rgba(0, 0, 0, 0.6)" }}>
                                {activePatch.diff}
                              </pre>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* TAB 3: FULL REPORT */}
      {activeTab === "report" && (
        <div className="glass-panel" style={{ padding: 28 }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 16,
            }}
          >
            <h3 style={{ fontSize: "1.1rem", fontWeight: 700 }}>📑 Complete Audit Report</h3>
            {analysisResult?.reportMarkdown && (
              <button
                className="glass-button-secondary"
                style={{ fontSize: "0.8rem", padding: "6px 14px", borderRadius: 8 }}
                onClick={() => {
                  navigator.clipboard.writeText(analysisResult.reportMarkdown);
                  alert("Report copied to clipboard!");
                }}
              >
                📋 Copy Report Markdown
              </button>
            )}
          </div>

          {analysisResult?.reportMarkdown ? (
            <pre
              style={{
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                fontSize: "0.9rem",
                lineHeight: 1.6,
                padding: 20,
              }}
            >
              {analysisResult.reportMarkdown}
            </pre>
          ) : (
            <p style={{ color: "var(--text-secondary)" }}>
              No analysis report available. Run an analysis from the Overview tab.
            </p>
          )}
        </div>
      )}

      {/* TAB 4: RAG CODE EXPLORER */}
      {activeTab === "explorer" && (
        <div>
          <div
            className="glass-panel"
            style={{
              padding: 16,
              marginBottom: 20,
              display: "flex",
              gap: 12,
              flexWrap: "wrap",
            }}
          >
            <input
              type="text"
              placeholder="Search code chunks (e.g. 'token', 'auth', 'database')..."
              className="glass-input"
              style={{ flex: 1, minWidth: 260 }}
              value={explorerQuery}
              onChange={(e) => setExplorerQuery(e.target.value)}
            />
            <input
              type="text"
              placeholder="Filter by filename (e.g. '.py', 'main')..."
              className="glass-input"
              style={{ width: 220 }}
              value={explorerFileFilter}
              onChange={(e) => setExplorerFileFilter(e.target.value)}
            />
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {searchedChunks.length === 0 ? (
              <div className="glass-panel" style={{ padding: 32, textAlign: "center", color: "var(--text-secondary)" }}>
                No code chunks match your query.
              </div>
            ) : (
              searchedChunks.map((chunk) => (
                <div key={chunk.id} className="glass-panel" style={{ padding: 20 }}>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      marginBottom: 10,
                    }}
                  >
                    <div>
                      <span
                        style={{
                          fontFamily: "var(--font-mono)",
                          fontWeight: 700,
                          color: "var(--accent-cyan)",
                        }}
                      >
                        {chunk.filename}
                      </span>
                      <span
                        style={{
                          fontSize: "0.75rem",
                          color: "var(--text-muted)",
                          marginLeft: 8,
                        }}
                      >
                        (chunk {chunk.chunkIndex} • {chunk.fileExt})
                      </span>
                    </div>
                    <span className="badge badge-category">{chunk.contentHash}</span>
                  </div>
                  <pre style={{ maxHeight: 280, fontSize: "0.82rem" }}>{chunk.content}</pre>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* TAB 5: REPOSITORY CHAT (RAG) */}
      {activeTab === "chat" && (
        <div
          className="glass-panel"
          style={{
            display: "flex",
            flexDirection: "column",
            height: "70vh",
            padding: 20,
          }}
        >
          {/* Messages Area */}
          <div
            style={{
              flex: 1,
              overflowY: "auto",
              display: "flex",
              flexDirection: "column",
              gap: 16,
              paddingRight: 8,
              marginBottom: 16,
            }}
          >
            {chatMessages.length === 0 ? (
              <div
                style={{
                  margin: "auto",
                  textAlign: "center",
                  color: "var(--text-secondary)",
                  maxWidth: 480,
                }}
              >
                <div style={{ fontSize: 40, marginBottom: 12 }}>💬</div>
                <h4 style={{ color: "var(--text-primary)", marginBottom: 6 }}>
                  Ask Anything About This Repository
                </h4>
                <p style={{ fontSize: "0.85rem", marginBottom: 16 }}>
                  Answers are grounded strictly in the indexed repository code with citations.
                </p>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {[
                    "How does the core workflow of this repository work?",
                    "Are there any hardcoded secrets or unredacted credentials?",
                    "What are the main dependencies and entry points?",
                  ].map((preset) => (
                    <button
                      key={preset}
                      onClick={() => handleSendMessage(undefined, preset)}
                      className="glass-button-secondary"
                      style={{
                        padding: "8px 12px",
                        fontSize: "0.8rem",
                        textAlign: "left",
                        cursor: "pointer",
                      }}
                    >
                      💡 {preset}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              chatMessages.map((msg, idx) => (
                <div
                  key={idx}
                  style={{
                    alignSelf: msg.role === "user" ? "flex-end" : "flex-start",
                    maxWidth: "85%",
                    background:
                      msg.role === "user"
                        ? "linear-gradient(135deg, var(--accent-indigo) 0%, var(--accent-violet) 100%)"
                        : "rgba(18, 24, 40, 0.8)",
                    border:
                      msg.role === "user"
                        ? "1px solid rgba(255, 255, 255, 0.2)"
                        : "1px solid rgba(255, 255, 255, 0.08)",
                    padding: "14px 18px",
                    borderRadius: 14,
                    color: "#ffffff",
                    fontSize: "0.92rem",
                    lineHeight: 1.5,
                  }}
                >
                  <div style={{ whiteSpace: "pre-wrap" }}>{msg.content}</div>

                  {msg.sources && msg.sources.length > 0 && (
                    <div
                      style={{
                        marginTop: 10,
                        paddingTop: 8,
                        borderTop: "1px solid rgba(255, 255, 255, 0.1)",
                        fontSize: "0.75rem",
                        color: "var(--text-secondary)",
                      }}
                    >
                      <strong>📚 Sources Cited:</strong>
                      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 4 }}>
                        {msg.sources.map((s, si) => (
                          <span
                            key={si}
                            style={{
                              background: "rgba(0, 0, 0, 0.3)",
                              padding: "2px 6px",
                              borderRadius: 4,
                              fontFamily: "var(--font-mono)",
                            }}
                          >
                            {s.filename} (chunk {s.chunkIndex})
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))
            )}
            {isChatLoading && (
              <div
                style={{
                  alignSelf: "flex-start",
                  background: "rgba(18, 24, 40, 0.8)",
                  padding: "12px 18px",
                  borderRadius: 14,
                  fontSize: "0.85rem",
                  color: "var(--accent-cyan)",
                }}
              >
                Thinking with Groq...
              </div>
            )}
            <div ref={chatBottomRef} />
          </div>

          {/* Chat Input */}
          <form onSubmit={handleSendMessage} style={{ display: "flex", gap: 10 }}>
            <input
              type="text"
              placeholder="Ask a question about this repository's codebase..."
              className="glass-input"
              style={{ flex: 1 }}
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              disabled={isChatLoading || chunks.length === 0}
            />
            <button
              type="submit"
              className="glass-button"
              disabled={isChatLoading || chunks.length === 0 || !chatInput.trim()}
              style={{ padding: "0 24px" }}
            >
              Send
            </button>
          </form>
        </div>
      )}

      {/* TAB 6: TELEMETRY & SETTINGS */}
      {activeTab === "settings" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 20 }}>
          <div className="glass-panel" style={{ padding: 24 }}>
            <h3 style={{ fontSize: "1.1rem", fontWeight: 700, marginBottom: 16 }}>
              ⚙️ Groq Inference Settings
            </h3>
            <div style={{ maxWidth: 400 }}>
              <label style={{ fontSize: "0.85rem", color: "var(--text-secondary)", display: "block", marginBottom: 6 }}>
                Active Groq Model
              </label>
              <select
                className="glass-input"
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
              >
                <option value="qwen/qwen3.8-27b">qwen/qwen3.8-27b (Fast & Analytical)</option>
                <option value="openai/gpt-oss-120b">openai/gpt-oss-120b (Deep Reasoning)</option>
                <option value="openai/gpt-oss-20b">openai/gpt-oss-20b (Ultra Low Latency)</option>
              </select>
            </div>
          </div>

          <div className="glass-panel" style={{ padding: 24 }}>
            <h3 style={{ fontSize: "1.1rem", fontWeight: 700, marginBottom: 16 }}>
              📊 Cumulative Token Telemetry
            </h3>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                gap: 16,
              }}
            >
              <div style={{ padding: 16, background: "rgba(255, 255, 255, 0.03)", borderRadius: 12 }}>
                <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>Prompt Tokens</span>
                <div style={{ fontSize: "1.4rem", fontWeight: 700, marginTop: 4 }}>
                  {analysisResult?.tokenUsage?.promptTokens.toLocaleString() || 0}
                </div>
              </div>
              <div style={{ padding: 16, background: "rgba(255, 255, 255, 0.03)", borderRadius: 12 }}>
                <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>Completion Tokens</span>
                <div style={{ fontSize: "1.4rem", fontWeight: 700, marginTop: 4 }}>
                  {analysisResult?.tokenUsage?.completionTokens.toLocaleString() || 0}
                </div>
              </div>
              <div style={{ padding: 16, background: "rgba(255, 255, 255, 0.03)", borderRadius: 12 }}>
                <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>Total Tokens</span>
                <div style={{ fontSize: "1.4rem", fontWeight: 700, marginTop: 4, color: "var(--accent-indigo)" }}>
                  {analysisResult?.tokenUsage?.totalTokens.toLocaleString() || 0}
                </div>
              </div>
            </div>
          </div>

          <div className="glass-panel" style={{ padding: 24 }}>
            <h3 style={{ fontSize: "1.1rem", fontWeight: 700, marginBottom: 16 }}>
              🏥 System Health Status
            </h3>
            <pre style={{ fontSize: "0.85rem" }}>
              {JSON.stringify(healthStatus, null, 2)}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

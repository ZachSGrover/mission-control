"use client";

// Next.js route-level error boundary.
// Catches render errors in the /app directory tree.

import { useEffect } from "react";
import { logSystemAction, writeAutoJournal } from "@/lib/action-logger";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  // Log every render error to memory so it shows up in journal
  useEffect(() => {
    logSystemAction(
      "error",
      "App render error caught by boundary",
      error.message || error.digest || "Unknown render error",
    );
    writeAutoJournal({ priority: true }); // render crashes always journal immediately
  }, [error]);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "100vh",
        gap: "12px",
        padding: "32px",
        background: "var(--bg, #0f1117)",
        color: "var(--text, #e2e8f0)",
        fontFamily: "system-ui, sans-serif",
      }}
    >
      <p style={{ fontSize: "16px", fontWeight: 600, color: "#f87171" }}>
        Something went wrong
      </p>
      {error.message && (
        <p
          style={{
            fontSize: "13px",
            color: "var(--text-muted, #94a3b8)",
            maxWidth: "420px",
            textAlign: "center",
            lineHeight: 1.5,
          }}
        >
          {error.message}
        </p>
      )}
      <div style={{ display: "flex", gap: "8px", marginTop: "4px" }}>
        <button
          onClick={reset}
          style={{
            padding: "8px 18px",
            borderRadius: "8px",
            background: "var(--accent, #6366f1)",
            color: "#fff",
            fontSize: "13px",
            fontWeight: 500,
            cursor: "pointer",
            border: "none",
          }}
        >
          Try again
        </button>
        <button
          onClick={() => window.location.reload()}
          style={{
            padding: "8px 18px",
            borderRadius: "8px",
            background: "transparent",
            color: "var(--text-muted, #94a3b8)",
            fontSize: "13px",
            fontWeight: 500,
            cursor: "pointer",
            border: "1px solid var(--border, #2a2e3a)",
          }}
        >
          Reload app
        </button>
      </div>
    </div>
  );
}

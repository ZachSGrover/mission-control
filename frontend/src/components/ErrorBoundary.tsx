"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("[ErrorBoundary] Caught render error:", error.message);
    console.error("[ErrorBoundary] Component stack:", info.componentStack);
  }

  private handleReset = (): void => {
    this.setState({ hasError: false, error: undefined });
  };

  render(): ReactNode {
    if (!this.state.hasError) return this.props.children;

    if (this.props.fallback) return this.props.fallback;

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
        {this.state.error?.message && (
          <p
            style={{
              fontSize: "13px",
              color: "var(--text-muted, #94a3b8)",
              maxWidth: "420px",
              textAlign: "center",
              lineHeight: 1.5,
            }}
          >
            {this.state.error.message}
          </p>
        )}
        <div style={{ display: "flex", gap: "8px", marginTop: "4px" }}>
          <button
            onClick={this.handleReset}
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
}

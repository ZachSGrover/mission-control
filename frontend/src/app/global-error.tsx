"use client";

// Next.js global error boundary — replaces the root layout on catastrophic errors.
// Must include <html> and <body>.

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en" className="dark">
      <body
        style={{
          margin: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          minHeight: "100vh",
          gap: "12px",
          padding: "32px",
          background: "#0f1117",
          color: "#e2e8f0",
          fontFamily: "system-ui, sans-serif",
        }}
      >
        <p style={{ fontSize: "16px", fontWeight: 600, color: "#f87171" }}>
          Digidle OS encountered an unexpected error
        </p>
        {error.message && (
          <p
            style={{
              fontSize: "13px",
              color: "#94a3b8",
              maxWidth: "420px",
              textAlign: "center",
              lineHeight: 1.5,
            }}
          >
            {error.message}
          </p>
        )}
        <button
          onClick={reset}
          style={{
            marginTop: "4px",
            padding: "8px 20px",
            borderRadius: "8px",
            background: "#6366f1",
            color: "#fff",
            fontSize: "13px",
            fontWeight: 500,
            cursor: "pointer",
            border: "none",
          }}
        >
          Reload
        </button>
      </body>
    </html>
  );
}

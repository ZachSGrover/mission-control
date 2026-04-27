// Instant shell skeleton — shown by Next.js while the route segment loads.
// Must be a Server Component (no "use client") so it renders without JS.
// Matches the exact layout of DashboardShell so there is zero layout shift.

export default function Loading() {
  return (
    <div
      style={{
        height: "100vh",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        background: "var(--bg)",
        color: "var(--text)",
      }}
    >
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <header
        style={{
          flexShrink: 0,
          display: "flex",
          alignItems: "center",
          height: "64px",
          background: "var(--surface)",
          borderBottom: "1px solid var(--border)",
        }}
      >
        {/* Brand zone */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            paddingLeft: "96px",
            paddingRight: "16px",
            width: "220px",
            flexShrink: 0,
          }}
        >
          {/* Brandmark — "Digidle OS" wordmark replica */}
          <span
            style={{
              fontFamily: "var(--font-heading, sans-serif)",
              fontWeight: 600,
              fontSize: "15px",
              letterSpacing: "-0.01em",
              color: "var(--text)",
              opacity: 0.9,
            }}
          >
            Digidle OS
          </span>
        </div>

        {/* Spacer */}
        <div style={{ flex: 1 }} />

        {/* Right-side placeholder */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "12px",
            paddingRight: "20px",
          }}
        >
          {/* Status dot placeholder */}
          <div
            style={{
              height: "6px",
              width: "6px",
              borderRadius: "50%",
              background: "var(--border-strong)",
            }}
          />
          {/* Avatar placeholder */}
          <div
            style={{
              height: "28px",
              width: "28px",
              borderRadius: "50%",
              background: "var(--surface-strong)",
              border: "1px solid var(--border)",
            }}
          />
        </div>
      </header>

      {/* ── Body ───────────────────────────────────────────────────────── */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        {/* Sidebar skeleton */}
        <aside
          style={{
            flexShrink: 0,
            width: "220px",
            background: "var(--surface)",
            borderRight: "1px solid var(--border)",
            padding: "20px 12px",
            display: "flex",
            flexDirection: "column",
            gap: "20px",
          }}
        >
          {/* Nav section skeletons */}
          {[
            { label: "Chat",       rows: 5 },
            { label: "Memory",     rows: 3 },
            { label: "Automation", rows: 5 },
          ].map(({ label, rows }) => (
            <div key={label} style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
              {/* Section label */}
              <div
                style={{
                  height: "8px",
                  width: "40px",
                  borderRadius: "4px",
                  background: "var(--border-strong)",
                  marginBottom: "6px",
                  marginLeft: "12px",
                }}
              />
              {Array.from({ length: rows }, (_, i) => (
                <div
                  key={i}
                  style={{
                    height: "32px",
                    borderRadius: "8px",
                    background: i === 0 ? "var(--accent-soft)" : "transparent",
                    display: "flex",
                    alignItems: "center",
                    gap: "10px",
                    padding: "0 12px",
                  }}
                >
                  <div
                    style={{
                      height: "14px",
                      width: "14px",
                      borderRadius: "3px",
                      background: "var(--border-strong)",
                      flexShrink: 0,
                    }}
                  />
                  <div
                    style={{
                      height: "10px",
                      width: `${48 + (i * 11) % 32}px`,
                      borderRadius: "4px",
                      background: "var(--border-strong)",
                    }}
                  />
                </div>
              ))}
            </div>
          ))}
        </aside>

        {/* Main content skeleton */}
        <main style={{ flex: 1, overflow: "hidden", background: "var(--bg)" }} />
      </div>
    </div>
  );
}

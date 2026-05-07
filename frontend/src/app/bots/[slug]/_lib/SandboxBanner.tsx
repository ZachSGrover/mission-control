"use client";

import { ShieldAlert } from "lucide-react";

/**
 * Always-visible banner that asserts the RT BOT MVP runs in sandbox
 * mode only — no live writes, no AdsPower, no Playwright, no X.com
 * traffic.  Rendered on every RT BOT page so operators / owners are
 * never unsure which lane they're operating in.
 */
export function SandboxBanner() {
  return (
    <div
      className="rounded-xl px-4 py-3 text-xs flex items-center gap-2"
      style={{
        background: "rgba(168,85,247,0.10)",
        border: "1px solid rgba(168,85,247,0.30)",
        color: "var(--text-muted)",
      }}
    >
      <ShieldAlert className="h-4 w-4" style={{ color: "#c084fc" }} />
      <span>
        <strong style={{ color: "#c084fc" }}>SANDBOX MODE</strong> — live
        writes are disabled in this MVP. No AdsPower, no Playwright, no
        X.com traffic, no real DMs are sent. Run output is a redacted
        dry-run only.
      </span>
    </div>
  );
}

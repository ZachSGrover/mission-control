"use client";

import { Info } from "lucide-react";

/**
 * Default callout shown when no provider has live admin credentials wired
 * up.  Phrased to be founder-friendly — no jargon, no fear.
 */
export function SetupCallout() {
  return (
    <div
      className="rounded-xl px-4 py-3 flex gap-3 items-start"
      style={{
        background: "rgba(59,130,246,0.08)",
        border: "1px solid rgba(59,130,246,0.25)",
      }}
    >
      <Info
        className="h-4 w-4 shrink-0 mt-0.5"
        style={{ color: "#3b82f6" }}
      />
      <div className="text-sm space-y-1" style={{ color: "var(--text)" }}>
        <p className="font-medium">
          Provider admin usage is not configured yet.
        </p>
        <p style={{ color: "var(--text-muted)" }}>
          Add an admin key and organization ID in{" "}
          <a
            href="/usage/settings"
            className="underline"
            style={{ color: "#3b82f6" }}
          >
            Settings
          </a>{" "}
          to enable live usage snapshots from OpenAI and Anthropic.  Internal
          calls are tracked automatically when agents start logging usage.
        </p>
      </div>
    </div>
  );
}

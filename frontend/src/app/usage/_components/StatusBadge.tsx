"use client";

import type { ProviderStatus, SnapshotSource } from "../_lib/types";

const STATUS_TEXT: Record<ProviderStatus, string> = {
  ok: "Live",
  error: "Error",
  not_configured: "Not configured",
};

const STATUS_STYLE: Record<ProviderStatus, { bg: string; color: string }> = {
  ok: { bg: "rgba(34,197,94,0.12)", color: "#22c55e" },
  error: { bg: "rgba(239,68,68,0.12)", color: "#ef4444" },
  not_configured: { bg: "var(--surface)", color: "var(--text-quiet)" },
};

const SOURCE_TEXT: Record<SnapshotSource, string> = {
  live: "live",
  manual: "manual",
  placeholder: "placeholder",
};

const SOURCE_STYLE: Record<SnapshotSource, { bg: string; color: string }> = {
  live: { bg: "rgba(59,130,246,0.12)", color: "#3b82f6" },
  manual: { bg: "rgba(139,92,246,0.12)", color: "#8b5cf6" },
  placeholder: { bg: "var(--surface)", color: "var(--text-quiet)" },
};

export function StatusBadge({ status }: { status: ProviderStatus }) {
  const style = STATUS_STYLE[status];
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium"
      style={{ background: style.bg, color: style.color }}
    >
      {STATUS_TEXT[status]}
    </span>
  );
}

export function SourceBadge({ source }: { source: SnapshotSource | null }) {
  if (!source) return null;
  const style = SOURCE_STYLE[source];
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide"
      style={{ background: style.bg, color: style.color }}
    >
      {SOURCE_TEXT[source]}
    </span>
  );
}

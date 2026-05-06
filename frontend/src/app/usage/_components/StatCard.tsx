"use client";

import type { ReactNode } from "react";

interface StatCardProps {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "default" | "warn" | "danger" | "muted";
}

const TONE_STYLES: Record<NonNullable<StatCardProps["tone"]>, { color: string }> = {
  default: { color: "var(--text)" },
  warn: { color: "#f59e0b" },
  danger: { color: "#ef4444" },
  muted: { color: "var(--text-muted)" },
};

/** Compact KPI tile used across Overview and Alerts. */
export function StatCard({ label, value, hint, tone = "default" }: StatCardProps) {
  return (
    <div
      className="rounded-xl px-4 py-4 space-y-1"
      style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}
    >
      <p
        className="text-[11px] font-semibold uppercase tracking-widest"
        style={{ color: "var(--text-quiet)" }}
      >
        {label}
      </p>
      <p
        className="text-2xl font-semibold tabular-nums"
        style={TONE_STYLES[tone]}
      >
        {value}
      </p>
      {hint && (
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          {hint}
        </p>
      )}
    </div>
  );
}

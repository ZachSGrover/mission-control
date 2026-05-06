import type { AlertStatus } from "@/lib/hermes-client";

const STYLES: Record<AlertStatus, { bg: string; fg: string; label: string }> = {
  healthy:      { bg: "rgba(34, 197, 94, 0.15)",  fg: "#4ade80", label: "Healthy" },
  degraded:     { bg: "rgba(234, 179, 8, 0.15)",  fg: "#facc15", label: "Degraded" },
  failed:       { bg: "rgba(239, 68, 68, 0.18)",  fg: "#f87171", label: "Failed" },
  blocked:      { bg: "rgba(249, 115, 22, 0.15)", fg: "#fb923c", label: "Blocked" },
  rate_limited: { bg: "rgba(168, 85, 247, 0.15)", fg: "#c084fc", label: "Rate-limited" },
  disconnected: { bg: "rgba(239, 68, 68, 0.15)",  fg: "#f87171", label: "Disconnected" },
  unknown:      { bg: "rgba(148, 163, 184, 0.2)", fg: "#cbd5e1", label: "Unknown" },
  resolved:     { bg: "rgba(34, 197, 94, 0.15)",  fg: "#86efac", label: "Resolved" },
};

export function StatusBadge({ status }: { status: AlertStatus }) {
  const s = STYLES[status];
  return (
    <span
      className="inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium"
      style={{ backgroundColor: s.bg, color: s.fg }}
    >
      {s.label}
    </span>
  );
}

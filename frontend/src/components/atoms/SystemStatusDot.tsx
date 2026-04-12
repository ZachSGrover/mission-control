"use client";

/**
 * SystemStatusDot — compact system health indicator for the header.
 *
 * Reads from useSystemHealth() (no props needed).
 *
 * Appearance:
 *   unknown  → hidden (nothing rendered until first check completes)
 *   healthy  → small green dot, no text (silent / non-distracting)
 *   degraded → amber dot + "Degraded" label
 *   failing  → red pulsing dot + "Failing" label
 *
 * Tooltip shows: status · last check time · consecutive failures (if > 0)
 */

import { useSystemHealth } from "@/hooks/use-system-health";

const STATUS_COLOR: Record<string, string> = {
  healthy:  "#22c55e",
  degraded: "#f59e0b",
  failing:  "#ef4444",
};

const STATUS_LABEL: Record<string, string> = {
  healthy:  "System healthy",
  degraded: "System degraded",
  failing:  "System failing",
};

export function SystemStatusDot() {
  const {
    status,
    lastCheck,
    consecutiveFailures,
    cleanTicksSinceFailure,
    lastErrorTimestamps,
    weightedErrorScore,
    lastRecoveryTimestamp,
    detail,
  } = useSystemHealth();

  // Hide until the first check has completed
  if (status === "unknown") return null;

  const color = STATUS_COLOR[status] ?? "#94a3b8";
  const label = STATUS_LABEL[status] ?? status;

  const fmt = (iso: string) =>
    new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  const lastCheckLabel = lastCheck ? fmt(lastCheck) : "Not yet checked";

  const lastErrorLabel =
    lastErrorTimestamps.length > 0
      ? `Last error: ${fmt(lastErrorTimestamps[0])}`
      : null;

  const recoveryLabel =
    status === "degraded" && cleanTicksSinceFailure > 0
      ? `Stabilizing (${cleanTicksSinceFailure}/2 clean ticks)`
      : null;

  const recoveredLabel =
    lastRecoveryTimestamp && status === "healthy"
      ? `Last recovery: ${fmt(lastRecoveryTimestamp)}`
      : null;

  const tooltip = [
    label,
    `Last check: ${lastCheckLabel}`,
    weightedErrorScore > 0 ? `Error score: ${weightedErrorScore.toFixed(1)}` : null,
    consecutiveFailures > 0 ? `${consecutiveFailures} consecutive failure(s)` : null,
    lastErrorLabel,
    recoveryLabel,
    recoveredLabel,
    detail,
  ]
    .filter(Boolean)
    .join("  ·  ");

  return (
    <div
      title={tooltip}
      className="flex items-center gap-1.5 select-none"
      style={{
        cursor: "default",
        WebkitAppRegion: "no-drag",
      } as React.CSSProperties}
    >
      {/* Dot — uses ping animation when failing */}
      <span className="relative flex h-2 w-2 shrink-0">
        {status === "failing" && (
          <span
            className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75"
            style={{ background: color }}
          />
        )}
        <span
          className="relative inline-flex rounded-full h-2 w-2"
          style={{ background: color }}
        />
      </span>

      {/* Label — only shown when not healthy */}
      {status !== "healthy" && (
        <span
          className="text-[11px] font-medium leading-none"
          style={{ color }}
        >
          {status === "degraded" ? "Degraded" : "Failing"}
        </span>
      )}
    </div>
  );
}

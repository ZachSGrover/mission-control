"use client";

/**
 * SystemStatusDot — production-grade system health indicator for the header.
 *
 * States:
 *   unknown  → nothing rendered (first 15 s while monitor settles)
 *   healthy  → solid green dot, no label, silent
 *   degraded → amber dot + "Degraded" label
 *   failing  → red dot with pulse animation + "Failing" label
 *
 * Hover reveals a structured dark tooltip panel with:
 *   • Status + last check time
 *   • Provider rows (OpenAI / Gemini)
 *   • Weighted error score + error count
 *   • Rising risk warning (when trend detected)
 *   • Stabilizing progress (during recovery)
 *   • Last recovery timestamp (when healthy after recovery)
 *
 * Dot colour transitions smoothly via CSS — no flash on status change.
 * Pulse animation is only active on "failing".
 */

import { useState } from "react";
import { useSystemHealth } from "@/hooks/use-system-health";

// ── Colours ───────────────────────────────────────────────────────────────────

const DOT_COLOR: Record<string, string> = {
  healthy:  "#22c55e",
  degraded: "#f59e0b",
  failing:  "#ef4444",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// ── Tooltip panel ─────────────────────────────────────────────────────────────

interface TooltipProps {
  status: string;
  lastCheck: string | null;
  openaiOk: boolean | null;
  geminiOk: boolean | null;
  weightedErrorScore: number;
  errorCount: number;
  risingRisk: boolean;
  consecutiveRisingRisk: number;
  consecutiveDegraded: number;
  cleanTicksSinceFailure: number;
  lastRecoveryTimestamp: string | null;
}

function TooltipPanel({
  status,
  lastCheck,
  openaiOk,
  geminiOk,
  weightedErrorScore,
  errorCount,
  risingRisk,
  consecutiveRisingRisk,
  consecutiveDegraded,
  cleanTicksSinceFailure,
  lastRecoveryTimestamp,
}: TooltipProps) {
  const statusLabel = status === "healthy"
    ? "Healthy"
    : status === "degraded"
    ? "Degraded"
    : "Failing";

  const statusColor = DOT_COLOR[status] ?? "#94a3b8";
  const isRecovering      = status === "degraded" && cleanTicksSinceFailure > 0;
  const isDegradedAlert   = consecutiveDegraded   >= 3;
  const isRisingAlert     = consecutiveRisingRisk >= 3;

  return (
    <div
      style={{
        position:        "absolute",
        top:             "calc(100% + 8px)",
        right:           0,
        width:           220,
        background:      "#0f1117",
        border:          "1px solid rgba(255,255,255,0.08)",
        borderRadius:    10,
        padding:         "10px 12px",
        boxShadow:       "0 8px 24px rgba(0,0,0,0.5)",
        zIndex:          9999,
        fontFamily:      "system-ui, sans-serif",
        fontSize:        12,
        lineHeight:      1.5,
        color:           "#e2e8f0",
        pointerEvents:   "none",
        userSelect:      "none",
      }}
    >
      {/* Status row */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <span style={{ fontWeight: 600, fontSize: 13, color: statusColor }}>{statusLabel}</span>
        {lastCheck && (
          <span style={{ color: "#64748b", fontSize: 11 }}>{fmtTime(lastCheck)}</span>
        )}
      </div>

      {/* Divider */}
      <div style={{ height: 1, background: "rgba(255,255,255,0.06)", marginBottom: 8 }} />

      {/* Providers */}
      <div style={{ display: "flex", flexDirection: "column", gap: 3, marginBottom: 8 }}>
        <ProviderRow name="OpenAI" ok={openaiOk} />
        <ProviderRow name="Gemini" ok={geminiOk} />
      </div>

      {/* Divider */}
      <div style={{ height: 1, background: "rgba(255,255,255,0.06)", marginBottom: 8 }} />

      {/* Error metrics */}
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        <MetricRow
          label="Errors (10 min)"
          value={errorCount === 0 ? "None" : String(errorCount)}
          valueColor={errorCount > 0 ? "#f59e0b" : "#22c55e"}
        />
        <MetricRow
          label="Error score"
          value={weightedErrorScore.toFixed(1)}
          valueColor={
            weightedErrorScore >= 6   ? "#ef4444"
            : weightedErrorScore >= 1.5 ? "#f59e0b"
            : "#64748b"
          }
        />
      </div>

      {/* Alerts */}
      {(risingRisk || isRisingAlert || isDegradedAlert || isRecovering || lastRecoveryTimestamp) && (
        <>
          <div style={{ height: 1, background: "rgba(255,255,255,0.06)", margin: "8px 0" }} />
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {isRisingAlert && (
              <AlertRow icon="🔔" text={`Alert: rising risk (${consecutiveRisingRisk} ticks)`} color="#ef4444" />
            )}
            {risingRisk && !isRisingAlert && (
              <AlertRow icon="⚠️" text={`Rising risk (${consecutiveRisingRisk}/3 ticks)`} color="#f59e0b" />
            )}
            {isDegradedAlert && (
              <AlertRow icon="🔔" text={`Alert: degraded ${consecutiveDegraded} ticks`} color="#f59e0b" />
            )}
            {isRecovering && (
              <AlertRow
                icon="🔄"
                text={`Stabilizing (${cleanTicksSinceFailure}/2 clean ticks)`}
                color="#94a3b8"
              />
            )}
            {lastRecoveryTimestamp && status === "healthy" && !isRecovering && (
              <AlertRow
                icon="✓"
                text={`Recovered at ${fmtTime(lastRecoveryTimestamp)}`}
                color="#22c55e"
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}

function ProviderRow({ name, ok }: { name: string; ok: boolean | null }) {
  const label = ok === null ? "Disabled" : ok ? "OK" : "Down";
  const color = ok === null ? "#475569" : ok ? "#22c55e" : "#ef4444";
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
      <span style={{ color: "#94a3b8" }}>{name}</span>
      <span style={{ fontWeight: 500, color, fontVariantNumeric: "tabular-nums" }}>
        {label}
      </span>
    </div>
  );
}

function MetricRow({ label, value, valueColor }: { label: string; value: string; valueColor: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
      <span style={{ color: "#64748b" }}>{label}</span>
      <span style={{ fontWeight: 500, color: valueColor, fontVariantNumeric: "tabular-nums" }}>
        {value}
      </span>
    </div>
  );
}

function AlertRow({ icon, text, color }: { icon: string; text: string; color: string }) {
  return (
    <div style={{ display: "flex", gap: 5, alignItems: "center" }}>
      <span style={{ fontSize: 11 }}>{icon}</span>
      <span style={{ color, fontSize: 11 }}>{text}</span>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function SystemStatusDot() {
  const {
    status,
    lastCheck,
    openaiOk,
    geminiOk,
    weightedErrorScore,
    lastErrorTimestamps,
    risingRisk,
    consecutiveRisingRisk,
    consecutiveDegraded,
    cleanTicksSinceFailure,
    lastRecoveryTimestamp,
  } = useSystemHealth();

  const [hovered, setHovered] = useState(false);

  // Hidden until first check completes — prevents "unknown" flash
  if (status === "unknown") return null;

  const dotColor = DOT_COLOR[status] ?? "#94a3b8";

  return (
    <div
      style={{ position: "relative", display: "inline-flex", alignItems: "center" }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* Dot + label */}
      <div
        className="flex items-center gap-1.5 select-none"
        style={{
          cursor:            "default",
          WebkitAppRegion:   "no-drag",
        } as React.CSSProperties}
      >
        {/* Dot wrapper */}
        <span className="relative flex h-2 w-2 shrink-0">
          {/* Pulse ring — failing only */}
          {status === "failing" && (
            <span
              className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-60"
              style={{ background: dotColor }}
            />
          )}
          {/* Solid dot — smooth colour transition between states */}
          <span
            className="relative inline-flex rounded-full h-2 w-2"
            style={{
              background:  dotColor,
              transition:  "background-color 0.4s ease",
            }}
          />
        </span>

        {/* Label — degraded and failing only */}
        {status !== "healthy" && (
          <span
            className="text-[11px] font-medium leading-none"
            style={{
              color:      dotColor,
              transition: "color 0.4s ease",
            }}
          >
            {status === "degraded" ? "Degraded" : "Failing"}
          </span>
        )}
      </div>

      {/* Tooltip panel — rendered on hover */}
      {hovered && (
        <TooltipPanel
          status={status}
          lastCheck={lastCheck}
          openaiOk={openaiOk}
          geminiOk={geminiOk}
          weightedErrorScore={weightedErrorScore}
          errorCount={lastErrorTimestamps.length}
          risingRisk={risingRisk}
          consecutiveRisingRisk={consecutiveRisingRisk}
          consecutiveDegraded={consecutiveDegraded}
          cleanTicksSinceFailure={cleanTicksSinceFailure}
          lastRecoveryTimestamp={lastRecoveryTimestamp}
        />
      )}
    </div>
  );
}

import type { Severity } from "@/lib/hermes-client";

const STYLES: Record<Severity, { bg: string; fg: string; border: string; emoji: string }> = {
  LOW:      { bg: "rgba(59, 130, 246, 0.15)", fg: "#60a5fa", border: "rgba(59, 130, 246, 0.4)", emoji: "🔵" },
  MEDIUM:   { bg: "rgba(234, 179, 8, 0.15)",  fg: "#facc15", border: "rgba(234, 179, 8, 0.4)",  emoji: "🟡" },
  HIGH:     { bg: "rgba(249, 115, 22, 0.15)", fg: "#fb923c", border: "rgba(249, 115, 22, 0.4)", emoji: "🟠" },
  CRITICAL: { bg: "rgba(239, 68, 68, 0.15)",  fg: "#f87171", border: "rgba(239, 68, 68, 0.4)",  emoji: "🔴" },
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  const s = STYLES[severity];
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-semibold tracking-wide uppercase"
      style={{ backgroundColor: s.bg, color: s.fg, borderColor: s.border }}
    >
      <span aria-hidden="true">{s.emoji}</span>
      {severity}
    </span>
  );
}

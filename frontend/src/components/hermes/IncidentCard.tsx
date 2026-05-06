import Link from "next/link";

import { CopyButton } from "@/components/hermes/CopyButton";
import { SeverityBadge } from "@/components/hermes/SeverityBadge";
import { StatusBadge } from "@/components/hermes/StatusBadge";
import { type HermesIncident, formatTimestamp } from "@/lib/hermes-client";

interface IncidentCardProps {
  incident: HermesIncident;
  /** When true, the card links to the Repair Center for this alert. */
  showRepairLink?: boolean;
}

const SECTION_LABEL =
  "text-xs font-semibold uppercase tracking-wide text-[color:var(--muted-foreground,#94a3b8)]";

export function IncidentCard({ incident, showRepairLink = true }: IncidentCardProps) {
  const evidenceLines =
    incident.evidence.length > 0
      ? incident.evidence
      : ["(no evidence recorded)"];

  return (
    <article
      className="rounded-lg border p-5"
      style={{
        backgroundColor: "var(--surface, rgba(255,255,255,0.02))",
        borderColor: "var(--border, rgba(255,255,255,0.08))",
      }}
    >
      <header className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={incident.severity} />
        <StatusBadge status={incident.status} />
        <h3 className="text-base font-semibold">{incident.system}</h3>
        {showRepairLink && (
          <Link
            href={`/hermes/repair?id=${encodeURIComponent(incident.alert_id)}`}
            className="ml-auto text-xs font-medium underline-offset-2 hover:underline"
            style={{ color: "var(--accent, #60a5fa)" }}
          >
            Open repair plan →
          </Link>
        )}
      </header>

      <p className="mt-3 text-sm leading-relaxed">{incident.exact_issue}</p>

      <dl className="mt-4 space-y-3 text-sm">
        <div>
          <dt className={SECTION_LABEL}>Evidence</dt>
          <dd>
            <ul className="mt-1 list-disc space-y-0.5 pl-5">
              {evidenceLines.map((line, idx) => (
                <li key={idx}>{line}</li>
              ))}
            </ul>
          </dd>
        </div>

        {incident.likely_cause && (
          <div>
            <dt className={SECTION_LABEL}>Likely cause</dt>
            <dd className="mt-1">{incident.likely_cause}</dd>
          </div>
        )}

        {incident.business_impact && (
          <div>
            <dt className={SECTION_LABEL}>Business impact</dt>
            <dd className="mt-1">{incident.business_impact}</dd>
          </div>
        )}

        {incident.recommended_fix && (
          <div>
            <dt className={SECTION_LABEL}>Recommended fix</dt>
            <dd className="mt-1">{incident.recommended_fix}</dd>
          </div>
        )}
      </dl>

      <footer className="mt-4 flex flex-wrap items-center gap-3 border-t pt-3 text-xs"
        style={{ borderColor: "var(--border, rgba(255,255,255,0.08))" }}>
        <span className="text-[color:var(--muted-foreground,#94a3b8)]">
          First seen: {formatTimestamp(incident.first_seen ?? incident.timestamp)}
        </span>
        <span className="text-[color:var(--muted-foreground,#94a3b8)]">
          Last seen: {formatTimestamp(incident.timestamp)}
        </span>
        {typeof incident.failure_count === "number" && (
          <span className="text-[color:var(--muted-foreground,#94a3b8)]">
            Repeats: {incident.failure_count}
          </span>
        )}
        <span className="ml-auto">
          {incident.claude_prompt && (
            <CopyButton
              text={incident.claude_prompt}
              label="Copy repair prompt"
              ariaLabel={`Copy Claude repair prompt for ${incident.system}`}
            />
          )}
        </span>
      </footer>
    </article>
  );
}

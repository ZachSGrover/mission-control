"use client";

import { formatRelative, formatTokens, formatUsd } from "../_lib/format";
import type { ProviderTotals } from "../_lib/types";
import { SourceBadge, StatusBadge } from "./StatusBadge";

const PROVIDER_LABELS: Record<string, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  gemini: "Gemini",
  internal: "Internal",
};

const PROVIDER_DESCRIPTIONS: Record<string, string> = {
  openai: "ChatGPT, GPT-4o and o-series spend.",
  anthropic: "Claude API and synthesizer spend.",
  gemini: "Google Gemini calls.",
  internal: "Aggregated internal AI calls logged by Mission Control agents.",
};

export function ProviderCard({ totals }: { totals: ProviderTotals }) {
  const label = PROVIDER_LABELS[totals.provider] ?? totals.provider;
  const description = PROVIDER_DESCRIPTIONS[totals.provider];
  const showError =
    totals.last_status === "error" && totals.last_error
      ? totals.last_error
      : null;
  const placeholderHint =
    totals.last_status === "not_configured" && totals.last_error
      ? totals.last_error
      : null;
  // For successful collections the backend joins any collector notes (e.g.
  // "Cost shown is estimated locally…") into the same field.  Surface them
  // as a quiet info note so the user can see when a number is approximate.
  const liveNote =
    totals.last_status === "ok" && totals.last_error ? totals.last_error : null;
  const costEstimated =
    !!liveNote && /estimated/i.test(liveNote);

  return (
    <div
      className="rounded-xl p-5 space-y-4"
      style={{
        background: "var(--surface-strong)",
        border: "1px solid var(--border)",
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3
            className="text-base font-semibold"
            style={{ color: "var(--text)" }}
          >
            {label}
          </h3>
          {description && (
            <p
              className="mt-0.5 text-xs"
              style={{ color: "var(--text-muted)" }}
            >
              {description}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <SourceBadge source={totals.last_source} />
          <StatusBadge status={totals.last_status} />
        </div>
      </div>

      <dl className="grid grid-cols-2 gap-3">
        <Stat
          label={costEstimated ? "Cost (estimated)" : "Cost"}
          value={formatUsd(totals.cost_usd)}
        />
        <Stat label="Requests" value={formatTokens(totals.requests)} />
        <Stat label="Input tokens" value={formatTokens(totals.input_tokens)} />
        <Stat label="Output tokens" value={formatTokens(totals.output_tokens)} />
        <Stat label="Total tokens" value={formatTokens(totals.total_tokens)} />
        <Stat
          label="Last check"
          value={formatRelative(totals.last_captured_at)}
        />
      </dl>

      {showError && (
        <div
          className="rounded-lg px-3 py-2 text-xs"
          style={{
            background: "rgba(239,68,68,0.08)",
            border: "1px solid rgba(239,68,68,0.2)",
            color: "#ef4444",
          }}
        >
          <span className="font-medium">Last error:</span> {showError}
        </div>
      )}

      {!showError && placeholderHint && (
        <p
          className="text-xs leading-relaxed"
          style={{ color: "var(--text-muted)" }}
        >
          {placeholderHint}
        </p>
      )}

      {!showError && !placeholderHint && liveNote && (
        <p
          className="text-xs leading-relaxed"
          style={{ color: "var(--text-muted)" }}
        >
          {liveNote}
        </p>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt
        className="text-[10px] font-semibold uppercase tracking-widest"
        style={{ color: "var(--text-quiet)" }}
      >
        {label}
      </dt>
      <dd
        className="mt-0.5 text-sm tabular-nums"
        style={{ color: "var(--text)" }}
      >
        {value}
      </dd>
    </div>
  );
}

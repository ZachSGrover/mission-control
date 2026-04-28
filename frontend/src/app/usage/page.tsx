"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useAuthFetch } from "@/hooks/use-auth-fetch";

import { EmptyState } from "./_components/EmptyState";
import { RangePicker } from "./_components/RangePicker";
import { RefreshButton } from "./_components/RefreshButton";
import { SetupCallout } from "./_components/SetupCallout";
import { StatCard } from "./_components/StatCard";
import { StatusBadge } from "./_components/StatusBadge";
import { UsagePageShell } from "./_components/UsagePageShell";
import { fetchOverview } from "./_lib/api";
import { formatRelative, formatTokens, formatUsd } from "./_lib/format";
import type { ProviderTotals, RangeKey, UsageOverview } from "./_lib/types";

const PROVIDER_LABELS: Record<string, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  gemini: "Gemini",
  internal: "Internal",
};

export default function UsageOverviewPage() {
  const { fetchWithAuth } = useAuthFetch();
  const [rangeKey, setRangeKey] = useState<RangeKey>("7d");
  const [data, setData] = useState<UsageOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (rk: RangeKey) => {
      setLoading(true);
      setError(null);
      try {
        const next = await fetchOverview(fetchWithAuth, rk);
        setData(next);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load usage");
      } finally {
        setLoading(false);
      }
    },
    [fetchWithAuth],
  );

  useEffect(() => {
    void load(rangeKey);
  }, [load, rangeKey]);

  const allNotConfigured = useMemo(() => {
    if (!data) return false;
    const providers = data.providers.filter((p) => p.provider !== "internal");
    return providers.length > 0 && providers.every((p) => !p.configured);
  }, [data]);

  const biggestSpender = useMemo<ProviderTotals | null>(() => {
    if (!data) return null;
    const ranked = [...data.providers]
      .filter((p) => p.cost_usd > 0)
      .sort((a, b) => b.cost_usd - a.cost_usd);
    return ranked[0] ?? null;
  }, [data]);

  return (
    <UsagePageShell
      title="Usage Overview"
      subtitle="AI spend, token volume, and provider health across Mission Control."
      actions={
        <>
          <RangePicker value={rangeKey} onChange={setRangeKey} />
          <RefreshButton onRefreshed={() => void load(rangeKey)} />
        </>
      }
    >
      {error && <ErrorBanner message={error} />}

      {allNotConfigured && <SetupCallout />}

      {loading && !data ? (
        <LoadingShell />
      ) : !data ? (
        <EmptyState
          title="No usage data yet"
          body="Press Refresh Usage to fetch the latest snapshot, or wait for the daily snapshot job."
        />
      ) : (
        <>
          {/* KPI grid */}
          <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatCard
              label="Total spend"
              value={formatUsd(data.total_cost_usd)}
              hint={
                rangeKey === "24h"
                  ? "Last 24 hours"
                  : rangeKey === "7d"
                  ? "Last 7 days"
                  : rangeKey === "30d"
                  ? "Last 30 days"
                  : "Month to date"
              }
            />
            <StatCard
              label="Total tokens"
              value={formatTokens(
                data.total_input_tokens + data.total_output_tokens,
              )}
              hint={`${formatTokens(data.total_input_tokens)} in · ${formatTokens(
                data.total_output_tokens,
              )} out`}
            />
            <StatCard
              label="Requests"
              value={formatTokens(data.total_requests)}
              hint="API calls in window"
            />
            <StatCard
              label="Active alerts"
              value={
                (data.daily_threshold_breached ? 1 : 0) +
                (data.monthly_threshold_breached ? 1 : 0)
              }
              tone={
                data.daily_threshold_breached || data.monthly_threshold_breached
                  ? "danger"
                  : "muted"
              }
              hint={
                data.daily_threshold_breached
                  ? "Daily threshold exceeded"
                  : data.monthly_threshold_breached
                  ? "Monthly threshold exceeded"
                  : "No thresholds breached"
              }
            />
          </section>

          {/* Threshold + freshness summary */}
          <section className="grid md:grid-cols-2 gap-3">
            <SummaryRow
              label="Daily threshold"
              value={
                data.daily_threshold_usd === null
                  ? "Not set"
                  : formatUsd(data.daily_threshold_usd)
              }
              hint={
                data.daily_threshold_usd === null
                  ? "Configure in Settings to enable runaway-usage alerts."
                  : data.daily_threshold_breached
                  ? "Currently exceeded"
                  : "Within budget"
              }
              tone={data.daily_threshold_breached ? "danger" : "muted"}
            />
            <SummaryRow
              label="Monthly threshold"
              value={
                data.monthly_threshold_usd === null
                  ? "Not set"
                  : formatUsd(data.monthly_threshold_usd)
              }
              hint={
                data.monthly_threshold_usd === null
                  ? "Configure in Settings."
                  : data.monthly_threshold_breached
                  ? "Currently exceeded"
                  : "Within budget"
              }
              tone={data.monthly_threshold_breached ? "danger" : "muted"}
            />
          </section>

          {/* Provider health */}
          <section className="space-y-3">
            <h2
              className="text-xs font-semibold uppercase tracking-widest"
              style={{ color: "var(--text-quiet)" }}
            >
              Provider health
            </h2>
            <div
              className="rounded-xl divide-y"
              style={{
                background: "var(--surface-strong)",
                border: "1px solid var(--border)",
                borderColor: "var(--border)",
              }}
            >
              {data.providers.map((p) => (
                <ProviderHealthRow key={p.provider} totals={p} />
              ))}
            </div>
          </section>

          {/* Footer summary */}
          <section
            className="rounded-xl px-4 py-3 text-xs flex flex-wrap gap-x-6 gap-y-2"
            style={{
              background: "var(--surface-strong)",
              border: "1px solid var(--border)",
              color: "var(--text-muted)",
            }}
          >
            <span>
              Last refresh:{" "}
              <span style={{ color: "var(--text)" }}>
                {formatRelative(data.last_refresh_at)}
              </span>
            </span>
            {biggestSpender && (
              <span>
                Biggest spender:{" "}
                <span style={{ color: "var(--text)" }}>
                  {PROVIDER_LABELS[biggestSpender.provider] ?? biggestSpender.provider}{" "}
                  ({formatUsd(biggestSpender.cost_usd)})
                </span>
              </span>
            )}
            {!biggestSpender && (
              <span>No spend recorded in this window.</span>
            )}
          </section>
        </>
      )}
    </UsagePageShell>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div
      className="rounded-xl px-4 py-3 text-sm"
      style={{
        background: "rgba(239,68,68,0.1)",
        color: "#ef4444",
        border: "1px solid rgba(239,68,68,0.2)",
      }}
    >
      {message}
    </div>
  );
}

function LoadingShell() {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {Array.from({ length: 4 }).map((_, i) => (
        <div
          key={i}
          className="rounded-xl px-4 py-4 h-[88px] animate-pulse"
          style={{
            background: "var(--surface-strong)",
            border: "1px solid var(--border)",
          }}
        />
      ))}
    </div>
  );
}

function SummaryRow({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint: string;
  tone: "default" | "warn" | "danger" | "muted";
}) {
  const toneColor =
    tone === "danger"
      ? "#ef4444"
      : tone === "warn"
      ? "#f59e0b"
      : "var(--text-muted)";
  return (
    <div
      className="rounded-xl px-4 py-3 flex items-center justify-between gap-4"
      style={{
        background: "var(--surface-strong)",
        border: "1px solid var(--border)",
      }}
    >
      <div>
        <p
          className="text-[11px] font-semibold uppercase tracking-widest"
          style={{ color: "var(--text-quiet)" }}
        >
          {label}
        </p>
        <p
          className="mt-0.5 text-base font-semibold tabular-nums"
          style={{ color: "var(--text)" }}
        >
          {value}
        </p>
      </div>
      <p className="text-xs text-right" style={{ color: toneColor }}>
        {hint}
      </p>
    </div>
  );
}

function ProviderHealthRow({ totals }: { totals: ProviderTotals }) {
  const label = PROVIDER_LABELS[totals.provider] ?? totals.provider;
  return (
    <div className="px-4 py-3 flex items-center justify-between gap-3">
      <div className="min-w-0">
        <p
          className="text-sm font-medium truncate"
          style={{ color: "var(--text)" }}
        >
          {label}
        </p>
        <p
          className="text-xs truncate"
          style={{ color: "var(--text-muted)" }}
        >
          {totals.last_status === "error" && totals.last_error
            ? totals.last_error
            : `Last check ${formatRelative(totals.last_captured_at)}`}
        </p>
      </div>
      <div className="flex items-center gap-3 shrink-0">
        <span
          className="text-sm tabular-nums"
          style={{ color: "var(--text)" }}
        >
          {formatUsd(totals.cost_usd)}
        </span>
        <StatusBadge status={totals.last_status} />
      </div>
    </div>
  );
}

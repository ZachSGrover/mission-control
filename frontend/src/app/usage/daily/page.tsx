"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useAuthFetch } from "@/hooks/use-auth-fetch";

import { EmptyState } from "../_components/EmptyState";
import { MiniSparkline } from "../_components/MiniSparkline";
import { RefreshButton } from "../_components/RefreshButton";
import { UsagePageShell } from "../_components/UsagePageShell";
import { fetchDaily } from "../_lib/api";
import {
  formatCompactNumber,
  formatTokens,
  formatUsd,
} from "../_lib/format";
import type { DailyUsageResponse } from "../_lib/types";

const DAYS_OPTIONS = [7, 14, 30] as const;
type Days = (typeof DAYS_OPTIONS)[number];

export default function UsageDailyPage() {
  const { fetchWithAuth } = useAuthFetch();
  const [days, setDays] = useState<Days>(14);
  const [data, setData] = useState<DailyUsageResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (n: Days) => {
      setLoading(true);
      setError(null);
      try {
        setData(await fetchDaily(fetchWithAuth, n));
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load daily usage");
      } finally {
        setLoading(false);
      }
    },
    [fetchWithAuth],
  );

  useEffect(() => {
    void load(days);
  }, [load, days]);

  const buckets = useMemo(() => data?.buckets ?? [], [data]);
  const hasAnyData = buckets.some(
    (b) => b.cost_usd > 0 || b.input_tokens > 0 || b.output_tokens > 0,
  );

  const totals = useMemo(() => {
    return buckets.reduce(
      (acc, b) => {
        acc.cost += b.cost_usd;
        acc.input += b.input_tokens;
        acc.output += b.output_tokens;
        acc.requests += b.requests;
        return acc;
      },
      { cost: 0, input: 0, output: 0, requests: 0 },
    );
  }, [buckets]);

  return (
    <UsagePageShell
      title="Daily spend"
      subtitle="Day-by-day cost and token volume across all providers."
      actions={
        <>
          <DaysPicker value={days} onChange={setDays} />
          <RefreshButton onRefreshed={() => void load(days)} />
        </>
      }
    >
      {error && (
        <div
          className="rounded-xl px-4 py-3 text-sm"
          style={{
            background: "rgba(239,68,68,0.1)",
            color: "#ef4444",
            border: "1px solid rgba(239,68,68,0.2)",
          }}
        >
          {error}
        </div>
      )}

      {loading && !data ? (
        <div
          className="rounded-xl h-[120px] animate-pulse"
          style={{
            background: "var(--surface-strong)",
            border: "1px solid var(--border)",
          }}
        />
      ) : (
        <>
          {/* Sparkline + totals */}
          <section
            className="rounded-xl p-4 space-y-3"
            style={{
              background: "var(--surface-strong)",
              border: "1px solid var(--border)",
            }}
          >
            <div className="flex items-center justify-between gap-4">
              <p
                className="text-xs font-semibold uppercase tracking-widest"
                style={{ color: "var(--text-quiet)" }}
              >
                Cost trend ({days}d)
              </p>
              <div
                className="flex items-center gap-4 text-xs"
                style={{ color: "var(--text-muted)" }}
              >
                <span>
                  Total{" "}
                  <span style={{ color: "var(--text)" }}>
                    {formatUsd(totals.cost)}
                  </span>
                </span>
                <span>
                  Tokens{" "}
                  <span style={{ color: "var(--text)" }}>
                    {formatCompactNumber(totals.input + totals.output)}
                  </span>
                </span>
                <span>
                  Requests{" "}
                  <span style={{ color: "var(--text)" }}>
                    {formatTokens(totals.requests)}
                  </span>
                </span>
              </div>
            </div>
            {hasAnyData ? (
              <MiniSparkline values={buckets.map((b) => b.cost_usd)} />
            ) : (
              <p
                className="text-xs text-center py-6"
                style={{ color: "var(--text-quiet)" }}
              >
                No spend recorded in this window yet.
              </p>
            )}
          </section>

          {/* Daily table */}
          <section
            className="rounded-xl overflow-hidden"
            style={{
              background: "var(--surface-strong)",
              border: "1px solid var(--border)",
            }}
          >
            <table className="w-full text-sm">
              <thead>
                <tr
                  className="text-left"
                  style={{ background: "var(--surface)" }}
                >
                  <Th>Date</Th>
                  <Th align="right">Requests</Th>
                  <Th align="right">Input tokens</Th>
                  <Th align="right">Output tokens</Th>
                  <Th align="right">Cost</Th>
                </tr>
              </thead>
              <tbody>
                {buckets.length === 0 ? (
                  <tr>
                    <td
                      colSpan={5}
                      className="py-10 text-center text-sm"
                      style={{ color: "var(--text-muted)" }}
                    >
                      No data in range.
                    </td>
                  </tr>
                ) : (
                  buckets.map((b) => (
                    <tr
                      key={b.day}
                      style={{ borderTop: "1px solid var(--border)" }}
                    >
                      <Td>{formatDayLabel(b.day)}</Td>
                      <Td align="right">{formatTokens(b.requests)}</Td>
                      <Td align="right">{formatTokens(b.input_tokens)}</Td>
                      <Td align="right">{formatTokens(b.output_tokens)}</Td>
                      <Td align="right">{formatUsd(b.cost_usd)}</Td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </section>

          <p className="text-xs" style={{ color: "var(--text-quiet)" }}>
            Errors per day surface on the{" "}
            <a
              href="/usage/alerts"
              className="underline"
              style={{ color: "var(--accent-strong)" }}
            >
              Alerts page
            </a>
            . Per-provider daily breakdown is on the Phase 3 roadmap.
          </p>

          {!hasAnyData && data && (
            <EmptyState
              title="No usage logged yet"
              body="Refresh usage or wait for the daily snapshot. Once provider admin keys are configured, snapshots will populate this view."
            />
          )}
        </>
      )}
    </UsagePageShell>
  );
}

function DaysPicker({
  value,
  onChange,
}: {
  value: Days;
  onChange: (v: Days) => void;
}) {
  return (
    <div
      className="inline-flex rounded-lg p-0.5"
      style={{
        background: "var(--surface-strong)",
        border: "1px solid var(--border)",
      }}
    >
      {DAYS_OPTIONS.map((d) => {
        const active = d === value;
        return (
          <button
            key={d}
            type="button"
            onClick={() => onChange(d)}
            className="px-3 py-1 text-xs rounded-md transition-colors"
            style={
              active
                ? {
                    background: "var(--accent-soft)",
                    color: "var(--accent-strong)",
                    fontWeight: 500,
                  }
                : { color: "var(--text-muted)" }
            }
          >
            {d}d
          </button>
        );
      })}
    </div>
  );
}

function Th({
  children,
  align,
}: {
  children: React.ReactNode;
  align?: "left" | "right";
}) {
  return (
    <th
      className="px-4 py-2 text-[11px] font-semibold uppercase tracking-widest"
      style={{
        color: "var(--text-quiet)",
        textAlign: align ?? "left",
      }}
    >
      {children}
    </th>
  );
}

function formatDayLabel(iso: string): string {
  // Naive-UTC ISO → render in local short form. Same parser as format.ts.
  const hasTz = /[zZ]|[+-]\d\d:\d\d$/.test(iso);
  const date = new Date(hasTz ? iso : `${iso}Z`);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

function Td({
  children,
  align,
}: {
  children: React.ReactNode;
  align?: "left" | "right";
}) {
  return (
    <td
      className="px-4 py-2 tabular-nums"
      style={{
        color: "var(--text)",
        textAlign: align ?? "left",
      }}
    >
      {children}
    </td>
  );
}

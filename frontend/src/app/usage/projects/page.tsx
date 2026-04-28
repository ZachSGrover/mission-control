"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";

import { useAuthFetch } from "@/hooks/use-auth-fetch";

import { EmptyState } from "../_components/EmptyState";
import { RangePicker } from "../_components/RangePicker";
import { RefreshButton } from "../_components/RefreshButton";
import { UsagePageShell } from "../_components/UsagePageShell";
import { fetchProjects } from "../_lib/api";
import { formatTokens, formatUsd } from "../_lib/format";
import type { ProjectListResponse, RangeKey } from "../_lib/types";

export default function UsageProjectsPage() {
  const { fetchWithAuth } = useAuthFetch();
  const [rangeKey, setRangeKey] = useState<RangeKey>("7d");
  const [data, setData] = useState<ProjectListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (rk: RangeKey) => {
      setLoading(true);
      setError(null);
      try {
        setData(await fetchProjects(fetchWithAuth, rk));
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load projects");
      } finally {
        setLoading(false);
      }
    },
    [fetchWithAuth],
  );

  useEffect(() => {
    void load(rangeKey);
  }, [load, rangeKey]);

  const rows = data?.rows ?? [];

  return (
    <UsagePageShell
      title="Project & feature spend"
      subtitle="Internal AI calls grouped by project and feature."
      actions={
        <>
          <RangePicker value={rangeKey} onChange={setRangeKey} />
          <RefreshButton onRefreshed={() => void load(rangeKey)} />
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

      <div
        className="rounded-xl px-4 py-3 text-xs"
        style={{
          background: "var(--surface-strong)",
          border: "1px solid var(--border)",
          color: "var(--text-muted)",
        }}
      >
        <span style={{ color: "var(--text)" }}>How this works:</span>{" "}
        rows appear here once Mission Control agents start logging each AI
        call via <code className="font-mono">record_usage_event</code>.
        Until then the table will stay empty — the foundation is in place
        but no agent is wired yet.
      </div>

      {loading && !data ? (
        <div
          className="rounded-xl h-[120px] animate-pulse"
          style={{
            background: "var(--surface-strong)",
            border: "1px solid var(--border)",
          }}
        />
      ) : rows.length === 0 ? (
        <EmptyState
          title="No internal usage logged yet"
          body="Project- and feature-level rollups will appear here once agents emit usage events."
        />
      ) : (
        <section
          className="rounded-xl overflow-hidden"
          style={{
            background: "var(--surface-strong)",
            border: "1px solid var(--border)",
          }}
        >
          <table className="w-full text-sm">
            <thead>
              <tr style={{ background: "var(--surface)" }}>
                <Th>Project</Th>
                <Th>Feature</Th>
                <Th align="right">Requests</Th>
                <Th align="right">Input tokens</Th>
                <Th align="right">Output tokens</Th>
                <Th align="right">Cost</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr
                  key={`${r.project ?? "_"}-${r.feature ?? "_"}-${i}`}
                  style={{ borderTop: "1px solid var(--border)" }}
                >
                  <Td>{r.project ?? <Muted>untagged</Muted>}</Td>
                  <Td>{r.feature ?? <Muted>untagged</Muted>}</Td>
                  <Td align="right">{formatTokens(r.requests)}</Td>
                  <Td align="right">{formatTokens(r.input_tokens)}</Td>
                  <Td align="right">{formatTokens(r.output_tokens)}</Td>
                  <Td align="right">{formatUsd(r.cost_usd)}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </UsagePageShell>
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

function Muted({ children }: { children: React.ReactNode }) {
  return (
    <span style={{ color: "var(--text-quiet)" }} className="italic">
      {children}
    </span>
  );
}

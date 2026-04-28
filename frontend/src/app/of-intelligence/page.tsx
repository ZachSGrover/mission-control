"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw, Zap } from "lucide-react";

import { SectionShell, StatPill, StatusBadge, EmptyState } from "@/components/of-intelligence/SectionShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import {
  ofiApi,
  type OverviewMetrics,
  type AlertRow,
  type QcReportRow,
  formatCents,
  formatRelative,
} from "@/lib/of-intelligence/api";

export default function OfIntelligenceOverviewPage() {
  const { fetchWithAuth } = useAuthFetch();
  const [overview, setOverview] = useState<OverviewMetrics | null>(null);
  const [alerts, setAlerts] = useState<AlertRow[]>([]);
  const [latestQc, setLatestQc] = useState<QcReportRow | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncBusy, setSyncBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const [ov, a, qcs] = await Promise.all([
        ofiApi.overview(fetchWithAuth),
        ofiApi.alerts(fetchWithAuth, { onlyOpen: true, limit: 10 }),
        ofiApi.qcReports(fetchWithAuth, 1),
      ]);
      setOverview(ov);
      setAlerts(a);
      setLatestQc(qcs[0] ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [fetchWithAuth]);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 30_000);
    return () => clearInterval(id);
  }, [refresh]);

  const onSync = useCallback(async () => {
    setSyncBusy(true);
    try {
      await ofiApi.triggerSync(fetchWithAuth);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSyncBusy(false);
    }
  }, [fetchWithAuth, refresh]);

  return (
    <SectionShell
      title="Overview"
      description="Connection status, sync state, and the highest-signal metrics across every connected creator account."
      actions={
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm"
            style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
          <button
            type="button"
            onClick={() => void onSync()}
            disabled={syncBusy || !overview?.api_connected}
            className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50"
            style={{ background: "var(--accent-strong)", color: "white" }}
          >
            {syncBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
            Sync now
          </button>
        </div>
      }
    >
      {error && (
        <div className="mb-4 rounded-md border p-3 text-sm" style={{ borderColor: "rgb(248,113,113)", color: "rgb(225,29,72)" }}>
          {error}
        </div>
      )}

      {loading && !overview ? (
        <EmptyState title="Loading overview…" />
      ) : !overview ? (
        <EmptyState title="No overview data yet." hint="Configure the OnlyMonster API key in Settings, then run a sync." />
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatPill
              label="API connection"
              value={overview.api_connected ? "Connected" : "Not connected"}
              hint={`source=${overview.api_key_source}`}
            />
            <StatPill
              label="Last sync"
              value={formatRelative(overview.last_sync_started_at)}
              hint={overview.last_sync_status ?? "—"}
            />
            <StatPill label="Accounts synced" value={String(overview.accounts_synced)} />
            <StatPill label="Fans synced" value={String(overview.fans_synced)} />
            <StatPill label="Messages synced" value={String(overview.messages_synced)} />
            <StatPill label="Revenue today" value={formatCents(overview.revenue_today_cents)} />
            <StatPill label="Revenue 7d" value={formatCents(overview.revenue_7d_cents)} />
            <StatPill label="Revenue 30d" value={formatCents(overview.revenue_30d_cents)} />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <StatPill label="Accounts needing attention" value={String(overview.accounts_needing_attention)} />
            <StatPill label="Chatters to review" value={String(overview.chatters_to_review)} />
            <StatPill
              label="Critical alerts"
              value={String(overview.critical_alerts)}
              hint={overview.critical_alerts > 0 ? "Open the Alerts tab" : "All clear"}
            />
          </div>

          <section
            className="rounded-xl border p-5"
            style={{ background: "var(--surface)", borderColor: "var(--border)" }}
          >
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold" style={{ color: "var(--text)" }}>Open critical alerts</h2>
              <span className="text-xs" style={{ color: "var(--text-quiet)" }}>top 10</span>
            </div>
            {alerts.length === 0 ? (
              <p className="text-sm" style={{ color: "var(--text-muted)" }}>No open alerts.</p>
            ) : (
              <ul className="space-y-2">
                {alerts.map((a) => (
                  <li key={a.id} className="flex items-start justify-between gap-2 text-sm">
                    <div>
                      <p style={{ color: "var(--text)" }}>{a.title}</p>
                      <p className="text-xs" style={{ color: "var(--text-quiet)" }}>{a.message ?? a.code}</p>
                    </div>
                    <StatusBadge status={a.severity} />
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section
            className="rounded-xl border p-5"
            style={{ background: "var(--surface)", borderColor: "var(--border)" }}
          >
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold" style={{ color: "var(--text)" }}>Latest QC report</h2>
              {latestQc && <span className="text-xs" style={{ color: "var(--text-quiet)" }}>{formatRelative(latestQc.generated_at)}</span>}
            </div>
            {!latestQc ? (
              <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                No QC reports yet. Generate one from the QC Reports tab.
              </p>
            ) : (
              <div className="text-sm" style={{ color: "var(--text-muted)" }}>
                <p style={{ color: "var(--text)" }}>{latestQc.summary || "—"}</p>
                <p className="mt-1 text-xs" style={{ color: "var(--text-quiet)" }}>
                  {latestQc.accounts_reviewed} accounts · {latestQc.chatters_reviewed} chatters · {latestQc.critical_alerts_count} critical
                </p>
              </div>
            )}
          </section>
        </div>
      )}
    </SectionShell>
  );
}

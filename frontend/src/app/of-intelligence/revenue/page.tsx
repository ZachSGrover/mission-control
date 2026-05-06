"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";

import { SectionShell, EmptyState } from "@/components/of-intelligence/SectionShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import { ofiApi, type RevenueRow, formatCents, formatDate } from "@/lib/of-intelligence/api";

export default function OfIntelligenceRevenuePage() {
  const { fetchWithAuth } = useAuthFetch();
  const [rows, setRows] = useState<RevenueRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setRows(await ofiApi.revenue(fetchWithAuth, 200));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [fetchWithAuth]);

  useEffect(() => { void refresh(); }, [refresh]);

  return (
    <SectionShell
      title="Revenue"
      description="Append-only revenue snapshots. Every sync writes new rows so historical totals are never overwritten."
    >
      {error && (
        <div className="mb-4 rounded-md border p-3 text-sm" style={{ borderColor: "rgb(248,113,113)", color: "rgb(225,29,72)" }}>
          {error}
        </div>
      )}
      {loading ? (
        <EmptyState title="Loading revenue…" />
      ) : rows.length === 0 ? (
        <EmptyState title="No revenue snapshots yet." hint="OnlyMonster's `/revenue` endpoint must be wired before this populates." />
      ) : (
        <div className="rounded-xl border overflow-hidden" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
          <table className="w-full text-sm">
            <thead style={{ background: "var(--bg)", color: "var(--text-quiet)" }}>
              <tr className="text-left">
                <th className="px-3 py-2 font-medium">Captured</th>
                <th className="px-3 py-2 font-medium">Account</th>
                <th className="px-3 py-2 font-medium">Period</th>
                <th className="px-3 py-2 font-medium">Revenue</th>
                <th className="px-3 py-2 font-medium">Transactions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t" style={{ borderColor: "var(--border)" }}>
                  <td className="px-3 py-2 whitespace-nowrap" style={{ color: "var(--text-muted)" }}>{formatDate(r.captured_at)}</td>
                  <td className="px-3 py-2" style={{ color: "var(--text)" }}>{r.account_source_id || "—"}</td>
                  <td className="px-3 py-2 whitespace-nowrap" style={{ color: "var(--text-muted)" }}>
                    {r.period_start ? formatDate(r.period_start).split(",")[0] : "—"} → {r.period_end ? formatDate(r.period_end).split(",")[0] : "—"}
                  </td>
                  <td className="px-3 py-2" style={{ color: "var(--text)" }}>{formatCents(r.revenue_cents)}</td>
                  <td className="px-3 py-2" style={{ color: "var(--text-muted)" }}>{r.transactions_count ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionShell>
  );
}

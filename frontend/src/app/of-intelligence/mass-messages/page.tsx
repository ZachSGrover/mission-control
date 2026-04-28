"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";

import { SectionShell, EmptyState } from "@/components/of-intelligence/SectionShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import { ofiApi, type MassMessageRow, formatCents, formatDate } from "@/lib/of-intelligence/api";

export default function OfIntelligenceMassMessagesPage() {
  const { fetchWithAuth } = useAuthFetch();
  const [rows, setRows] = useState<MassMessageRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setRows(await ofiApi.massMessages(fetchWithAuth, 100));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [fetchWithAuth]);

  useEffect(() => { void refresh(); }, [refresh]);

  return (
    <SectionShell
      title="Mass Messages"
      description="Mass DM blasts and their conversion stats. Best-vs-worst ranking lives in the QC report."
    >
      {error && (
        <div className="mb-4 rounded-md border p-3 text-sm" style={{ borderColor: "rgb(248,113,113)", color: "rgb(225,29,72)" }}>
          {error}
        </div>
      )}
      {loading ? (
        <EmptyState title="Loading mass messages…" />
      ) : rows.length === 0 ? (
        <EmptyState title="No mass messages synced yet." />
      ) : (
        <div className="rounded-xl border overflow-hidden" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
          <table className="w-full text-sm">
            <thead style={{ background: "var(--bg)", color: "var(--text-quiet)" }}>
              <tr className="text-left">
                <th className="px-3 py-2 font-medium">Sent</th>
                <th className="px-3 py-2 font-medium">Account</th>
                <th className="px-3 py-2 font-medium">Recipients</th>
                <th className="px-3 py-2 font-medium">Purchases</th>
                <th className="px-3 py-2 font-medium">Revenue</th>
                <th className="px-3 py-2 font-medium">Body</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t" style={{ borderColor: "var(--border)" }}>
                  <td className="px-3 py-2 whitespace-nowrap" style={{ color: "var(--text-muted)" }}>{formatDate(r.sent_at)}</td>
                  <td className="px-3 py-2" style={{ color: "var(--text)" }}>{r.account_source_id || "—"}</td>
                  <td className="px-3 py-2" style={{ color: "var(--text-muted)" }}>{r.recipients_count ?? "—"}</td>
                  <td className="px-3 py-2" style={{ color: "var(--text-muted)" }}>{r.purchases_count ?? "—"}</td>
                  <td className="px-3 py-2" style={{ color: "var(--text)" }}>{formatCents(r.revenue_cents)}</td>
                  <td className="px-3 py-2 max-w-xl truncate" style={{ color: "var(--text-muted)" }}>{r.body_preview || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionShell>
  );
}

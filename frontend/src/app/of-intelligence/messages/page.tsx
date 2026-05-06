"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";

import { SectionShell, EmptyState } from "@/components/of-intelligence/SectionShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import { ofiApi, type MessageRow, formatCents, formatRelative } from "@/lib/of-intelligence/api";

export default function OfIntelligenceMessagesPage() {
  const { fetchWithAuth } = useAuthFetch();
  const [rows, setRows] = useState<MessageRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setRows(await ofiApi.messages(fetchWithAuth, 200));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [fetchWithAuth]);

  useEffect(() => { void refresh(); }, [refresh]);

  return (
    <SectionShell
      title="Messages"
      description="Most recent DM messages. Stored permanently — historical traffic is preserved across syncs."
    >
      {error && (
        <div className="mb-4 rounded-md border p-3 text-sm" style={{ borderColor: "rgb(248,113,113)", color: "rgb(225,29,72)" }}>
          {error}
        </div>
      )}
      {loading ? (
        <EmptyState title="Loading messages…" />
      ) : rows.length === 0 ? (
        <EmptyState title="No messages synced yet." />
      ) : (
        <div className="rounded-xl border overflow-hidden" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
          <table className="w-full text-sm">
            <thead style={{ background: "var(--bg)", color: "var(--text-quiet)" }}>
              <tr className="text-left">
                <th className="px-3 py-2 font-medium">When</th>
                <th className="px-3 py-2 font-medium">Direction</th>
                <th className="px-3 py-2 font-medium">Account / Fan</th>
                <th className="px-3 py-2 font-medium">Body</th>
                <th className="px-3 py-2 font-medium">Revenue</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t" style={{ borderColor: "var(--border)" }}>
                  <td className="px-3 py-2 whitespace-nowrap" style={{ color: "var(--text-muted)" }}>{formatRelative(r.sent_at)}</td>
                  <td className="px-3 py-2" style={{ color: "var(--text-muted)" }}>{r.direction || "—"}</td>
                  <td className="px-3 py-2 whitespace-nowrap" style={{ color: "var(--text-muted)" }}>
                    {r.account_source_id || "—"} / {r.fan_source_id || "—"}
                  </td>
                  <td className="px-3 py-2 max-w-xl truncate" style={{ color: "var(--text)" }}>{r.body || ""}</td>
                  <td className="px-3 py-2" style={{ color: "var(--text)" }}>{formatCents(r.revenue_cents)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionShell>
  );
}

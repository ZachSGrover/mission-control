"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";

import { SectionShell, StatusBadge, EmptyState } from "@/components/of-intelligence/SectionShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import { ofiApi, type AccountRow, formatRelative } from "@/lib/of-intelligence/api";

export default function OfIntelligenceAccountsPage() {
  const { fetchWithAuth } = useAuthFetch();
  const [rows, setRows] = useState<AccountRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setRows(await ofiApi.accounts(fetchWithAuth));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [fetchWithAuth]);

  useEffect(() => { void refresh(); }, [refresh]);

  return (
    <SectionShell
      title="Accounts"
      description="Connected creator accounts. Watch the access status column for early warning signs that an account may have lost access."
    >
      {error && (
        <div className="mb-4 rounded-md border p-3 text-sm" style={{ borderColor: "rgb(248,113,113)", color: "rgb(225,29,72)" }}>
          {error}
        </div>
      )}

      {loading ? (
        <EmptyState title="Loading accounts…" />
      ) : rows.length === 0 ? (
        <EmptyState
          title="No accounts synced yet."
          hint="Configure the OnlyMonster API key in Settings, then run a manual sync from the Overview tab."
        />
      ) : (
        <div className="rounded-xl border overflow-hidden" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
          <table className="w-full text-sm">
            <thead style={{ background: "var(--bg)", color: "var(--text-quiet)" }}>
              <tr className="text-left">
                <th className="px-3 py-2 font-medium">Account</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Access</th>
                <th className="px-3 py-2 font-medium">Last synced</th>
                <th className="px-3 py-2 font-medium">Source</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t" style={{ borderColor: "var(--border)" }}>
                  <td className="px-3 py-2" style={{ color: "var(--text)" }}>
                    {r.username || r.display_name || r.source_id}
                  </td>
                  <td className="px-3 py-2"><StatusBadge status={r.status} /></td>
                  <td className="px-3 py-2"><StatusBadge status={r.access_status} /></td>
                  <td className="px-3 py-2" style={{ color: "var(--text-muted)" }}>{formatRelative(r.last_synced_at)}</td>
                  <td className="px-3 py-2" style={{ color: "var(--text-quiet)" }}>{r.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionShell>
  );
}

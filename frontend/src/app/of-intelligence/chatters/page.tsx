"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";

import { SectionShell, StatusBadge, EmptyState } from "@/components/of-intelligence/SectionShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import { ofiApi, type ChatterRow, formatRelative } from "@/lib/of-intelligence/api";

export default function OfIntelligenceChattersPage() {
  const { fetchWithAuth } = useAuthFetch();
  const [rows, setRows] = useState<ChatterRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setRows(await ofiApi.chatters(fetchWithAuth));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [fetchWithAuth]);

  useEffect(() => { void refresh(); }, [refresh]);

  return (
    <SectionShell
      title="Chatters"
      description="Team-member chatters synced from OnlyMonster. Quality scoring activates once response-time and conversion heuristics are wired."
    >
      {error && (
        <div className="mb-4 rounded-md border p-3 text-sm" style={{ borderColor: "rgb(248,113,113)", color: "rgb(225,29,72)" }}>
          {error}
        </div>
      )}
      {loading ? (
        <EmptyState title="Loading chatters…" />
      ) : rows.length === 0 ? (
        <EmptyState title="No chatters synced yet." hint="Sync once OnlyMonster's `/chatters` endpoint is wired." />
      ) : (
        <div className="rounded-xl border overflow-hidden" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
          <table className="w-full text-sm">
            <thead style={{ background: "var(--bg)", color: "var(--text-quiet)" }}>
              <tr className="text-left">
                <th className="px-3 py-2 font-medium">Name</th>
                <th className="px-3 py-2 font-medium">Email</th>
                <th className="px-3 py-2 font-medium">Role</th>
                <th className="px-3 py-2 font-medium">Active</th>
                <th className="px-3 py-2 font-medium">Last synced</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t" style={{ borderColor: "var(--border)" }}>
                  <td className="px-3 py-2" style={{ color: "var(--text)" }}>{r.name || r.source_id}</td>
                  <td className="px-3 py-2" style={{ color: "var(--text-muted)" }}>{r.email || "—"}</td>
                  <td className="px-3 py-2" style={{ color: "var(--text-muted)" }}>{r.role || "—"}</td>
                  <td className="px-3 py-2"><StatusBadge status={r.active === null ? "unknown" : r.active ? "active" : "inactive"} /></td>
                  <td className="px-3 py-2" style={{ color: "var(--text-muted)" }}>{formatRelative(r.last_synced_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionShell>
  );
}

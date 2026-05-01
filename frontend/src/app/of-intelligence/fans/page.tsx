"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";

import { SectionShell, EmptyState } from "@/components/of-intelligence/SectionShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import { ofiApi, type FanRow, formatCents, formatRelative } from "@/lib/of-intelligence/api";

export default function OfIntelligenceFansPage() {
  const { fetchWithAuth } = useAuthFetch();
  const [rows, setRows] = useState<FanRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setRows(await ofiApi.fans(fetchWithAuth, 200));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [fetchWithAuth]);

  useEffect(() => { void refresh(); }, [refresh]);

  return (
    <SectionShell
      title="Fans"
      description="Fan / subscriber records sorted by lifetime value. Use the filters below once segmentation lands."
    >
      {error && (
        <div className="mb-4 rounded-md border p-3 text-sm" style={{ borderColor: "rgb(248,113,113)", color: "rgb(225,29,72)" }}>
          {error}
        </div>
      )}
      {loading ? (
        <EmptyState title="Loading fans…" />
      ) : rows.length === 0 ? (
        <EmptyState title="No fans synced yet." hint="OnlyMonster's `/fans` endpoint must be wired before this populates." />
      ) : (
        <div className="rounded-xl border overflow-hidden" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
          <table className="w-full text-sm">
            <thead style={{ background: "var(--bg)", color: "var(--text-quiet)" }}>
              <tr className="text-left">
                <th className="px-3 py-2 font-medium">Fan</th>
                <th className="px-3 py-2 font-medium">Account</th>
                <th className="px-3 py-2 font-medium">LTV</th>
                <th className="px-3 py-2 font-medium">Subscribed</th>
                <th className="px-3 py-2 font-medium">Last message</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t" style={{ borderColor: "var(--border)" }}>
                  <td className="px-3 py-2" style={{ color: "var(--text)" }}>{r.username || r.source_id}</td>
                  <td className="px-3 py-2" style={{ color: "var(--text-muted)" }}>{r.account_source_id || "—"}</td>
                  <td className="px-3 py-2" style={{ color: "var(--text)" }}>{formatCents(r.lifetime_value_cents)}</td>
                  <td className="px-3 py-2" style={{ color: "var(--text-muted)" }}>{r.is_subscribed === null ? "—" : r.is_subscribed ? "yes" : "no"}</td>
                  <td className="px-3 py-2" style={{ color: "var(--text-muted)" }}>{formatRelative(r.last_message_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionShell>
  );
}

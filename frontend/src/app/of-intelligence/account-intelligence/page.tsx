"use client";

export const dynamic = "force-dynamic";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { EmptyState, SectionShell, StatusBadge } from "@/components/of-intelligence/SectionShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import {
  formatCents,
  formatRelative,
  ofiApi,
  type CreatorProfileRow,
} from "@/lib/of-intelligence/api";

/**
 * Account Intelligence — index of every connected creator with a permanent
 * profile.  Auto-fills identity from synced OnlyMonster accounts; the
 * operator clicks through to fill in brand / strategy / vault notes.
 */
export default function AccountIntelligenceIndexPage() {
  const { fetchWithAuth } = useAuthFetch();
  const [rows, setRows] = useState<CreatorProfileRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const refresh = useCallback(async () => {
    setError(null);
    try {
      setRows(await ofiApi.creatorProfiles(fetchWithAuth));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [fetchWithAuth]);

  useEffect(() => { void refresh(); }, [refresh]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) => {
      const haystack = [r.username, r.display_name, r.source_account_id]
        .filter((v): v is string => Boolean(v))
        .map((v) => v.toLowerCase())
        .join(" ");
      return haystack.includes(q);
    });
  }, [rows, query]);

  const filledFieldsCount = (r: CreatorProfileRow): number => {
    const fields = [
      r.brand_persona,
      r.content_pillars,
      r.voice_tone,
      r.audience_summary,
      r.monetization_focus,
      r.posting_cadence,
      r.strategy_summary,
      r.off_limits,
      r.vault_notes,
      r.agency_notes,
    ];
    return fields.filter((v) => v && v.trim().length > 0).length;
  };

  return (
    <SectionShell
      title="Account Intelligence"
      description="One creator brain per account. Identity, subscription, and access auto-fill from OnlyMonster. Persona, voice, vault, strategy, and game-plan notes are operator-managed and never overwritten by a sync. Click any creator to open the full profile and generate an audit."
      actions={
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by username…"
          className="rounded-md border px-3 py-1.5 text-sm"
          style={{
            background: "var(--surface)",
            borderColor: "var(--border)",
            color: "var(--text)",
          }}
        />
      }
    >
      {error && (
        <div
          className="mb-4 rounded-md border p-3 text-sm"
          style={{ borderColor: "rgb(248,113,113)", color: "rgb(225,29,72)" }}
        >
          {error}
        </div>
      )}

      {loading ? (
        <EmptyState title="Loading creator profiles…" />
      ) : filtered.length === 0 ? (
        <EmptyState
          title={query ? "No creators match that search." : "No creator profiles yet."}
          hint={
            query
              ? "Try clearing the filter."
              : "Profiles auto-create from synced OnlyMonster accounts.  Run a manual sync from the Overview tab if no accounts have synced yet."
          }
        />
      ) : (
        <div
          className="rounded-xl border overflow-hidden"
          style={{ borderColor: "var(--border)", background: "var(--surface)" }}
        >
          <table className="w-full text-sm">
            <thead style={{ background: "var(--bg)", color: "var(--text-quiet)" }}>
              <tr className="text-left">
                <th className="px-3 py-2 font-medium">Creator</th>
                <th className="px-3 py-2 font-medium">Access</th>
                <th className="px-3 py-2 font-medium">Sub price</th>
                <th className="px-3 py-2 font-medium">Fans</th>
                <th className="px-3 py-2 font-medium">Messages</th>
                <th className="px-3 py-2 font-medium">Revenue 30d</th>
                <th className="px-3 py-2 font-medium">Open alerts</th>
                <th className="px-3 py-2 font-medium">Notes filled</th>
                <th className="px-3 py-2 font-medium">Last sync</th>
                <th className="px-3 py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => {
                const filled = filledFieldsCount(r);
                const label = r.display_name || r.username || r.source_account_id;
                return (
                  <tr key={r.id} className="border-t" style={{ borderColor: "var(--border)" }}>
                    <td className="px-3 py-2" style={{ color: "var(--text)" }}>
                      <Link
                        href={`/of-intelligence/account-intelligence/${r.id}`}
                        className="font-medium hover:underline"
                        style={{ color: "var(--accent-strong)" }}
                      >
                        {label}
                      </Link>
                      {r.username && r.display_name && r.username !== r.display_name && (
                        <span className="ml-2 text-xs" style={{ color: "var(--text-quiet)" }}>
                          @{r.username}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <StatusBadge status={r.access_status} />
                    </td>
                    <td className="px-3 py-2" style={{ color: "var(--text-muted)" }}>
                      {formatCents(r.subscribe_price_cents)}
                    </td>
                    <td className="px-3 py-2" style={{ color: "var(--text-muted)" }}>
                      {r.stats.fans_count.toLocaleString()}
                    </td>
                    <td className="px-3 py-2" style={{ color: "var(--text-muted)" }}>
                      {r.stats.messages_count.toLocaleString()}
                    </td>
                    <td className="px-3 py-2" style={{ color: "var(--text-muted)" }}>
                      {formatCents(r.stats.revenue_30d_cents)}
                    </td>
                    <td className="px-3 py-2" style={{ color: "var(--text-muted)" }}>
                      {r.stats.open_alert_count > 0 ? (
                        <span style={{ color: "rgb(225,29,72)", fontWeight: 500 }}>
                          {r.stats.open_alert_count}
                        </span>
                      ) : (
                        "0"
                      )}
                    </td>
                    <td className="px-3 py-2" style={{ color: "var(--text-muted)" }}>
                      {filled}/10
                    </td>
                    <td className="px-3 py-2" style={{ color: "var(--text-quiet)" }}>
                      {formatRelative(r.last_account_sync_at)}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Link
                        href={`/of-intelligence/account-intelligence/${r.id}`}
                        className="text-xs hover:underline"
                        style={{ color: "var(--accent-strong)" }}
                      >
                        Open →
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </SectionShell>
  );
}

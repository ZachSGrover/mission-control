"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import { getApiBaseUrl } from "@/lib/api-base";

import { SandboxBanner } from "../_lib/SandboxBanner";
import { formatRelative, type AuditEntry, RT_BOT_SLUG } from "../_lib/rt-bot";

function AuditContent() {
  const params = useParams();
  const slug = (Array.isArray(params?.slug) ? params.slug[0] : params?.slug) ?? "";
  const { fetchWithAuth } = useAuthFetch();

  const [rows, setRows] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchWithAuth(`${getApiBaseUrl()}/api/v1/audit-log/${slug}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setRows((await res.json()) as AuditEntry[]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load audit log.");
    } finally {
      setLoading(false);
    }
  }, [fetchWithAuth, slug]);

  useEffect(() => {
    if (slug) void refresh();
  }, [slug, refresh]);

  const filtered = useMemo(() => {
    if (!filter) return rows;
    const needle = filter.toLowerCase();
    return rows.filter(
      (r) =>
        r.action.toLowerCase().includes(needle) ||
        (r.target_id ?? "").toLowerCase().includes(needle) ||
        (r.actor_email ?? "").toLowerCase().includes(needle),
    );
  }, [rows, filter]);

  return (
    <main className="flex-1 overflow-y-auto" style={{ background: "var(--bg)" }}>
      <div className="max-w-4xl mx-auto px-6 py-8 space-y-5">
        <Link
          href={`/bots/${slug}`}
          className="text-xs underline decoration-dotted"
          style={{ color: "var(--text-quiet)" }}
        >
          ← Bot detail
        </Link>
        <h1 className="text-xl font-semibold" style={{ color: "var(--text)" }}>
          Audit log
        </h1>
        {slug === RT_BOT_SLUG && <SandboxBanner />}

        <input
          type="text"
          placeholder="Filter by action / target / actor"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="w-full rounded-lg px-3 py-1.5 text-xs"
          style={{
            background: "var(--surface-strong)",
            border: "1px solid var(--border)",
            color: "var(--text)",
          }}
        />

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

        {loading ? (
          <p className="text-xs" style={{ color: "var(--text-quiet)" }}>
            Loading…
          </p>
        ) : filtered.length === 0 ? (
          <p className="text-xs" style={{ color: "var(--text-quiet)" }}>
            No audit events.
          </p>
        ) : (
          <div
            className="rounded-xl overflow-hidden"
            style={{
              background: "var(--surface-strong)",
              border: "1px solid var(--border)",
            }}
          >
            <table className="w-full text-xs">
              <thead style={{ color: "var(--text-quiet)" }}>
                <tr>
                  <th className="text-left px-3 py-2">When</th>
                  <th className="text-left px-3 py-2">Actor</th>
                  <th className="text-left px-3 py-2">Action</th>
                  <th className="text-left px-3 py-2">Target</th>
                  <th className="text-left px-3 py-2">Outcome</th>
                  <th className="text-left px-3 py-2">Summary</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => (
                  <tr
                    key={r.id}
                    className="border-t"
                    style={{ borderColor: "var(--border)" }}
                  >
                    <td className="px-3 py-2" style={{ color: "var(--text-quiet)" }}>
                      {formatRelative(r.created_at)}
                    </td>
                    <td className="px-3 py-2" style={{ color: "var(--text)" }}>
                      {r.actor_email ?? r.actor_clerk_user_id}
                    </td>
                    <td className="px-3 py-2 font-mono" style={{ color: "var(--text)" }}>
                      {r.action}
                    </td>
                    <td className="px-3 py-2 font-mono" style={{ color: "var(--text-muted)" }}>
                      {r.target_type}/{(r.target_id ?? "").slice(0, 8)}…
                    </td>
                    <td className="px-3 py-2">{r.outcome}</td>
                    <td className="px-3 py-2" style={{ color: "var(--text-muted)" }}>
                      {r.safe_summary}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </main>
  );
}

export default function AuditPage() {
  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel message="Sign in to view the audit log" forceRedirectUrl="/bots" />
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <RoleGuard
          require="operator"
          denied={
            <main
              className="flex-1 flex items-center justify-center"
              style={{ background: "var(--bg)" }}
            >
              <p className="text-sm" style={{ color: "var(--text-quiet)" }}>
                Operator access required.
              </p>
            </main>
          }
        >
          <AuditContent />
        </RoleGuard>
      </SignedIn>
    </DashboardShell>
  );
}

"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  AlertTriangle,
  Loader2,
  Lock,
  RefreshCw,
  ShieldOff,
} from "lucide-react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import { useRole } from "@/hooks/use-role";
import { getApiBaseUrl } from "@/lib/api-base";

import { SandboxBanner } from "./_lib/SandboxBanner";
import {
  formatRelative,
  type BotEntryDetail,
  type BotRun,
  RT_BOT_SLUG,
} from "./_lib/rt-bot";

function StatusPill({ status }: { status: string }) {
  const palette: Record<string, { bg: string; fg: string }> = {
    completed: { bg: "rgba(34,197,94,0.15)", fg: "#22c55e" },
    running_scan: { bg: "rgba(59,130,246,0.15)", fg: "#60a5fa" },
    queued: { bg: "rgba(234,179,8,0.15)", fg: "#eab308" },
    paused: { bg: "rgba(234,179,8,0.15)", fg: "#eab308" },
    rejected: { bg: "rgba(239,68,68,0.15)", fg: "#ef4444" },
    failed: { bg: "rgba(239,68,68,0.15)", fg: "#ef4444" },
    draft: { bg: "rgba(107,114,128,0.15)", fg: "#9ca3af" },
  };
  const colors = palette[status] ?? { bg: "rgba(107,114,128,0.15)", fg: "#9ca3af" };
  return (
    <span
      className="rounded-full px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide"
      style={{ background: colors.bg, color: colors.fg }}
    >
      {status}
    </span>
  );
}

function BotDetailContent() {
  const params = useParams();
  const slugParam = params?.slug;
  const slug = Array.isArray(slugParam) ? slugParam[0] : slugParam ?? "";

  const { fetchWithAuth } = useAuthFetch();
  const { role } = useRole();
  const isOwner = role === "owner";

  const [bot, setBot] = useState<BotEntryDetail | null>(null);
  const [runs, setRuns] = useState<BotRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [killing, setKilling] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [botRes, runsRes] = await Promise.all([
        fetchWithAuth(`${getApiBaseUrl()}/api/v1/bots/${slug}`),
        fetchWithAuth(`${getApiBaseUrl()}/api/v1/bots/${slug}/runs`),
      ]);
      if (!botRes.ok) throw new Error(`HTTP ${botRes.status}`);
      setBot((await botRes.json()) as BotEntryDetail);
      if (runsRes.ok) {
        setRuns((await runsRes.json()) as BotRun[]);
      } else if (runsRes.status === 404) {
        // bots without RT BOT run lifecycle simply don't expose this list.
        setRuns([]);
      } else {
        // Soft-fail on the runs list; the bot detail still renders.
        setRuns([]);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load bot.");
    } finally {
      setLoading(false);
    }
  }, [fetchWithAuth, slug]);

  useEffect(() => {
    if (slug) void refresh();
  }, [slug, refresh]);

  const onKill = useCallback(async () => {
    if (!isOwner) return;
    if (!confirm("Activate kill switch? This cancels queued runs and pauses running scans.")) {
      return;
    }
    setKilling(true);
    try {
      const res = await fetchWithAuth(`${getApiBaseUrl()}/api/v1/bots/${slug}/kill`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Kill switch failed.");
    } finally {
      setKilling(false);
    }
  }, [fetchWithAuth, isOwner, refresh, slug]);

  const isRtBot = slug === RT_BOT_SLUG;

  return (
    <main className="flex-1 overflow-y-auto" style={{ background: "var(--bg)" }}>
      <div className="max-w-4xl mx-auto px-6 py-8 space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <Link
              href="/bots"
              className="text-xs underline decoration-dotted"
              style={{ color: "var(--text-quiet)" }}
            >
              ← All bots
            </Link>
            <h1 className="text-xl font-semibold mt-2" style={{ color: "var(--text)" }}>
              {bot?.name ?? slug}
            </h1>
            <p className="mt-1 text-sm" style={{ color: "var(--text-muted)" }}>
              {bot?.description ?? ""}
            </p>
            <p className="mt-1 font-mono text-[11px]" style={{ color: "var(--text-quiet)" }}>
              slug: {slug}
            </p>
          </div>
          <button
            type="button"
            onClick={() => void refresh()}
            className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs"
            style={{
              background: "var(--surface-strong)",
              border: "1px solid var(--border)",
              color: "var(--text-muted)",
            }}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
        </div>

        {isRtBot && <SandboxBanner />}

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
          <p className="text-sm" style={{ color: "var(--text-quiet)" }}>
            Loading…
          </p>
        ) : bot ? (
          <>
            <section
              className="rounded-xl p-4"
              style={{
                background: "var(--surface-strong)",
                border: "1px solid var(--border)",
              }}
            >
              <div className="grid grid-cols-2 gap-4 text-xs">
                <div>
                  <p style={{ color: "var(--text-quiet)" }}>Status</p>
                  <p className="mt-1" style={{ color: "var(--text)" }}>
                    {bot.status}
                  </p>
                </div>
                <div>
                  <p style={{ color: "var(--text-quiet)" }}>Last run</p>
                  <p className="mt-1" style={{ color: "var(--text)" }}>
                    {formatRelative(bot.last_run_at)}
                  </p>
                </div>
                <div>
                  <p style={{ color: "var(--text-quiet)" }}>Sandbox</p>
                  <p className="mt-1" style={{ color: "var(--text)" }}>
                    {bot.safe_mode ? "On" : "Off"}
                  </p>
                </div>
                <div>
                  <p style={{ color: "var(--text-quiet)" }}>Live writes</p>
                  <p className="mt-1" style={{ color: "var(--text)" }}>
                    Disabled
                  </p>
                </div>
              </div>
              {bot.last_error_summary && (
                <p
                  className="mt-3 text-xs flex items-center gap-1"
                  style={{ color: "var(--danger, #ef4444)" }}
                >
                  <AlertTriangle className="h-3 w-3" />
                  {bot.last_error_summary}
                </p>
              )}
            </section>

            {isRtBot && (
              <section className="flex flex-wrap gap-2">
                {isOwner && (
                  <Link
                    href={`/bots/${slug}/runs/new`}
                    className="rounded-lg px-3 py-1.5 text-xs font-medium"
                    style={{ background: "rgba(34,197,94,0.15)", color: "#22c55e" }}
                  >
                    + New Sandbox Run
                  </Link>
                )}
                <Link
                  href={`/bots/${slug}/audit`}
                  className="rounded-lg px-3 py-1.5 text-xs"
                  style={{
                    background: "var(--surface-strong)",
                    border: "1px solid var(--border)",
                    color: "var(--text-muted)",
                  }}
                >
                  Audit log
                </Link>
                {isOwner && (
                  <Link
                    href={`/bots/${slug}/settings`}
                    className="rounded-lg px-3 py-1.5 text-xs"
                    style={{
                      background: "var(--surface-strong)",
                      border: "1px solid var(--border)",
                      color: "var(--text-muted)",
                    }}
                  >
                    Settings
                  </Link>
                )}
                {isOwner && (
                  <button
                    type="button"
                    onClick={() => void onKill()}
                    disabled={killing}
                    className="rounded-lg px-3 py-1.5 text-xs font-medium flex items-center gap-1 disabled:opacity-50"
                    style={{ background: "rgba(239,68,68,0.15)", color: "#ef4444" }}
                  >
                    {killing ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <ShieldOff className="h-3 w-3" />
                    )}
                    Kill switch
                  </button>
                )}
                {!isOwner && (
                  <span
                    className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs"
                    style={{ background: "var(--surface-muted)", color: "var(--text-quiet)" }}
                    title="Owner only"
                  >
                    <Lock className="h-3 w-3" /> Owner-only actions hidden
                  </span>
                )}
              </section>
            )}

            {isRtBot && (
              <section>
                <h2 className="text-sm font-semibold mb-2" style={{ color: "var(--text)" }}>
                  Run history
                </h2>
                {runs.length === 0 ? (
                  <p className="text-xs" style={{ color: "var(--text-quiet)" }}>
                    No runs yet.
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
                          <th className="text-left px-3 py-2">Status</th>
                          <th className="text-left px-3 py-2">Profile</th>
                          <th className="text-left px-3 py-2">Mode</th>
                          <th className="text-left px-3 py-2">Targets</th>
                          <th className="text-left px-3 py-2">Scan</th>
                          <th className="text-left px-3 py-2">Sent</th>
                          <th className="text-left px-3 py-2">Created</th>
                        </tr>
                      </thead>
                      <tbody>
                        {runs.map((r) => (
                          <tr
                            key={r.id}
                            className="border-t"
                            style={{ borderColor: "var(--border)" }}
                          >
                            <td className="px-3 py-2">
                              <Link
                                href={`/bots/${slug}/runs/${r.id}`}
                                className="underline decoration-dotted"
                              >
                                <StatusPill status={r.status} />
                              </Link>
                            </td>
                            <td className="px-3 py-2" style={{ color: "var(--text)" }}>
                              {r.profile_name}
                            </td>
                            <td className="px-3 py-2">{r.mode}</td>
                            <td className="px-3 py-2">{r.target_count}</td>
                            <td className="px-3 py-2">{r.scan_count}</td>
                            <td className="px-3 py-2">{r.sent_count}</td>
                            <td
                              className="px-3 py-2"
                              style={{ color: "var(--text-quiet)" }}
                            >
                              {formatRelative(r.created_at)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            )}
          </>
        ) : (
          <p className="text-sm" style={{ color: "var(--text-quiet)" }}>
            Bot not found.
          </p>
        )}
      </div>
    </main>
  );
}

export default function BotDetailPage() {
  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel message="Sign in to view bot details" forceRedirectUrl="/bots" />
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
          <BotDetailContent />
        </RoleGuard>
      </SignedIn>
    </DashboardShell>
  );
}

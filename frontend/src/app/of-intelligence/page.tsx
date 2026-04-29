"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw, Zap } from "lucide-react";
import Link from "next/link";

import {
  EmptyState,
  SectionShell,
  StatPill,
  StatusBadge,
} from "@/components/of-intelligence/SectionShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import {
  formatRelative,
  ofiApi,
  type AlertRow,
  type ChatImportRow,
  type CreatorProfileRow,
  type OverviewMetrics,
  type QcReportRow,
  type SyncLogRow,
} from "@/lib/of-intelligence/api";

/**
 * Overview = the agency-data-brain home screen.
 *
 * Reading order:
 *   1. What's broken right now → Critical alerts
 *   2. What's slipping         → Accounts / chatters needing attention
 *   3. What we know            → Latest QC report + creator profile + chat-lab activity
 *   4. What's connected        → Data Brain Status panel
 *   5. What's next             → Next Unlocks panel (roadmap shadow)
 *   6. What's flowing          → Last sync (per-entity) — kept for diagnostics
 *
 * No charts, no glossy KPIs.  This screen is for deciding what to do.
 */
export default function OfIntelligenceOverviewPage() {
  const { fetchWithAuth } = useAuthFetch();
  const [overview, setOverview] = useState<OverviewMetrics | null>(null);
  const [alerts, setAlerts] = useState<AlertRow[]>([]);
  const [latestQc, setLatestQc] = useState<QcReportRow | null>(null);
  const [syncLogs, setSyncLogs] = useState<SyncLogRow[]>([]);
  const [profiles, setProfiles] = useState<CreatorProfileRow[]>([]);
  const [chatImports, setChatImports] = useState<ChatImportRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncBusy, setSyncBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const [ov, a, qcs, logs, profs, imports] = await Promise.all([
        ofiApi.overview(fetchWithAuth),
        ofiApi.alerts(fetchWithAuth, { onlyOpen: true, limit: 10 }),
        ofiApi.qcReports(fetchWithAuth, 1),
        ofiApi.syncLogs(fetchWithAuth, 200),
        ofiApi.creatorProfiles(fetchWithAuth).catch(() => []),
        ofiApi.chatLabImports(fetchWithAuth, 5).catch(() => []),
      ]);
      setOverview(ov);
      setAlerts(a);
      setLatestQc(qcs[0] ?? null);
      setSyncLogs(logs);
      setProfiles(profs);
      setChatImports(imports);
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

  // Derived stats for the status / unlocks panels.
  const profilesWithNotes = profiles.filter((p) => {
    const fields = [
      p.brand_persona, p.content_pillars, p.voice_tone, p.audience_summary,
      p.monetization_focus, p.posting_cadence, p.strategy_summary,
      p.off_limits, p.vault_notes, p.agency_notes,
    ];
    return fields.some((v) => v && v.trim().length > 0);
  }).length;
  const totalChatImportMessages = chatImports.reduce(
    (sum, imp) => sum + imp.messages_inserted,
    0,
  );
  const totalChatImportFindings = chatImports.reduce(
    (sum, imp) => sum + imp.findings_count,
    0,
  );

  return (
    <SectionShell
      title="OnlyFans Intelligence"
      description="The agency data brain. Collects data, builds creator memory, runs QC, surfaces alerts, and powers strategy. This screen is about deciding what to do — raw rows live under Data sources."
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
        <div
          className="mb-4 rounded-md border p-3 text-sm"
          style={{ borderColor: "rgb(248,113,113)", color: "rgb(225,29,72)" }}
        >
          {error}
        </div>
      )}

      {loading && !overview ? (
        <EmptyState title="Loading overview…" />
      ) : !overview ? (
        <EmptyState
          title="No overview data yet."
          hint="Configure the OnlyMonster API key in Settings, then run a sync."
        />
      ) : (
        <div className="space-y-6">
          {/* ── Today's signals ──────────────────────────────────────── */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatPill
              label="Critical alerts"
              value={String(overview.critical_alerts)}
              hint={overview.critical_alerts > 0 ? "Open Critical Alerts" : "All clear"}
            />
            <StatPill
              label="Accounts needing attention"
              value={String(overview.accounts_needing_attention)}
              hint={
                overview.accounts_needing_attention > 0
                  ? "Lost / blocked / stale sync"
                  : "All current"
              }
            />
            <StatPill
              label="Chatters to review"
              value={String(overview.chatters_to_review)}
              hint="From Chat QC v1 (user_metrics)"
            />
            <StatPill
              label="Latest QC report"
              value={latestQc ? formatRelative(latestQc.generated_at) : "—"}
              hint={
                latestQc
                  ? `${latestQc.critical_alerts_count} critical · ${latestQc.chatters_reviewed} chatters`
                  : "Generate one from QC Reports"
              }
            />
          </div>

          {/* ── Open critical alerts ─────────────────────────────────── */}
          <Section title="Open critical alerts" subtitle="Top 10 by recency" link={{ href: "/of-intelligence/alerts", label: "All alerts →" }}>
            {alerts.length === 0 ? (
              <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                No open alerts.  When the alert engine fires (sync failure,
                lost account access, critical chatter QC), it lands here.
              </p>
            ) : (
              <ul className="space-y-2">
                {alerts.map((a) => (
                  <li
                    key={a.id}
                    className="flex items-start justify-between gap-2 text-sm"
                  >
                    <div>
                      <p style={{ color: "var(--text)" }}>{a.title}</p>
                      <p className="text-xs" style={{ color: "var(--text-quiet)" }}>
                        {a.message ?? a.code}
                      </p>
                    </div>
                    <StatusBadge status={a.severity} />
                  </li>
                ))}
              </ul>
            )}
          </Section>

          {/* ── Latest QC report ─────────────────────────────────────── */}
          <Section
            title="Latest QC report"
            subtitle={latestQc ? formatRelative(latestQc.generated_at) : undefined}
            link={{ href: "/of-intelligence/qc-reports", label: "All reports →" }}
          >
            {!latestQc ? (
              <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                No QC reports yet.  Generate one from QC Reports.
              </p>
            ) : (
              <div className="text-sm" style={{ color: "var(--text-muted)" }}>
                <p style={{ color: "var(--text)" }}>{latestQc.summary || "—"}</p>
                <p className="mt-1 text-xs" style={{ color: "var(--text-quiet)" }}>
                  {latestQc.accounts_reviewed} accounts · {latestQc.chatters_reviewed} chatters · {latestQc.critical_alerts_count} critical findings
                </p>
              </div>
            )}
          </Section>

          {/* ── Creator Intelligence + Chat QC Lab snapshot ──────────── */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Section
              title="Creator Intelligence"
              subtitle={`${profiles.length} profile${profiles.length === 1 ? "" : "s"}`}
              link={{
                href: "/of-intelligence/account-intelligence",
                label: "Open Account Intelligence →",
              }}
            >
              <p className="text-sm" style={{ color: "var(--text)" }}>
                {profiles.length === 0
                  ? "No profiles synced yet — run a sync from above."
                  : profilesWithNotes === 0
                    ? `${profiles.length} profile${profiles.length === 1 ? "" : "s"} auto-created.  None have brand / strategy / vault notes filled in yet.`
                    : `${profilesWithNotes} of ${profiles.length} profile${profiles.length === 1 ? "" : "s"} have operator notes.  ${profiles.length - profilesWithNotes} still empty.`}
              </p>
              <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                Identity, subscription, and access auto-fill from OnlyMonster.
                Brand persona, voice, vault, and strategy are operator-managed.
              </p>
            </Section>

            <Section
              title="Chat QC Lab"
              subtitle={
                chatImports.length === 0
                  ? "No imports yet"
                  : `${chatImports.length} recent import${chatImports.length === 1 ? "" : "s"}`
              }
              link={{
                href: "/of-intelligence/chat-qc-lab",
                label: "Open Chat QC Lab →",
              }}
            >
              {chatImports.length === 0 ? (
                <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                  Manual chat-data import bridge.  Upload sample JSON or CSV
                  to test the chat QC engine before live capture is ready.
                </p>
              ) : (
                <p className="text-sm" style={{ color: "var(--text)" }}>
                  {totalChatImportMessages} message{totalChatImportMessages === 1 ? "" : "s"} imported · {totalChatImportFindings} finding{totalChatImportFindings === 1 ? "" : "s"} surfaced.
                </p>
              )}
              <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                Live chat scraping is not connected yet.  Treat any uploaded
                message text as sensitive.
              </p>
            </Section>
          </div>

          {/* ── Data Brain Status ─────────────────────────────────────── */}
          <DataBrainStatusPanel
            apiConnected={overview.api_connected}
            apiKeySource={overview.api_key_source}
            accountsSynced={overview.accounts_synced}
            messagesSynced={overview.messages_synced}
            profilesCount={profiles.length}
            chatImportsCount={chatImports.length}
            latestQc={latestQc}
            criticalAlerts={overview.critical_alerts}
          />

          {/* ── Next Unlocks ──────────────────────────────────────────── */}
          <NextUnlocksPanel />

          {/* ── Last sync per-entity (kept for diagnostics) ─────────── */}
          <Section
            title="Last sync — per entity"
            subtitle="Source-side flow.  This panel is diagnostic; if numbers look wrong, start here."
          >
            <PerEntitySyncTable syncLogs={syncLogs} />
          </Section>
        </div>
      )}
    </SectionShell>
  );
}

// ── Reusable section shell (kept local so we don't churn SectionShell.tsx) ───

function Section({
  title,
  subtitle,
  link,
  children,
}: {
  title: string;
  subtitle?: string;
  link?: { href: string; label: string };
  children: React.ReactNode;
}) {
  return (
    <section
      className="rounded-xl border p-5"
      style={{ background: "var(--surface)", borderColor: "var(--border)" }}
    >
      <div className="flex items-baseline justify-between gap-3 mb-3">
        <div>
          <h2 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
            {title}
          </h2>
          {subtitle && (
            <p className="text-xs mt-0.5" style={{ color: "var(--text-quiet)" }}>
              {subtitle}
            </p>
          )}
        </div>
        {link && (
          <Link
            href={link.href}
            className="text-xs hover:underline whitespace-nowrap"
            style={{ color: "var(--accent-strong)" }}
          >
            {link.label}
          </Link>
        )}
      </div>
      {children}
    </section>
  );
}

// ── Data Brain Status panel ──────────────────────────────────────────────────

function DataBrainStatusPanel({
  apiConnected,
  apiKeySource,
  accountsSynced,
  messagesSynced,
  profilesCount,
  chatImportsCount,
  latestQc,
  criticalAlerts,
}: {
  apiConnected: boolean;
  apiKeySource: string;
  accountsSynced: number;
  messagesSynced: number;
  profilesCount: number;
  chatImportsCount: number;
  latestQc: QcReportRow | null;
  criticalAlerts: number;
}) {
  const connected: Array<{ label: string; detail: string; ok: boolean }> = [
    {
      label: "OnlyMonster API",
      detail: apiConnected
        ? `Connected (${apiKeySource})`
        : "Not configured — set the API key in Settings",
      ok: apiConnected,
    },
    {
      label: "Account sync",
      detail:
        accountsSynced > 0
          ? `${accountsSynced} account${accountsSynced === 1 ? "" : "s"} synced`
          : "No accounts synced yet",
      ok: accountsSynced > 0,
    },
    {
      label: "User metrics → Chat QC v1",
      detail: "Per-chatter aggregates power the daily QC report",
      ok: true,
    },
    {
      label: "Creator profiles",
      detail:
        profilesCount > 0
          ? `${profilesCount} profile${profilesCount === 1 ? "" : "s"} auto-created`
          : "Profiles auto-create on first sync",
      ok: profilesCount > 0,
    },
    {
      label: "Chat QC Lab (manual import)",
      detail:
        chatImportsCount > 0
          ? `${chatImportsCount} recent import${chatImportsCount === 1 ? "" : "s"}`
          : "Bridge ready — no imports yet",
      ok: true,
    },
    {
      label: "Daily QC reports",
      detail: latestQc
        ? `Last generated ${formatRelative(latestQc.generated_at)}`
        : "Not yet generated",
      ok: !!latestQc,
    },
    {
      label: "Internal alerts",
      detail:
        criticalAlerts > 0
          ? `${criticalAlerts} open critical`
          : "Engine running, all clear",
      ok: true,
    },
    {
      label: "Messages synced (live)",
      detail:
        messagesSynced > 0
          ? `${messagesSynced} message${messagesSynced === 1 ? "" : "s"} from OnlyMonster`
          : "0 — OnlyMonster does not expose chat content",
      ok: messagesSynced > 0,
    },
  ];
  const notConnected: Array<{ label: string; detail: string }> = [
    {
      label: "Live chat scraping",
      detail: "Requires direct OnlyFans connector",
    },
    {
      label: "Direct OnlyFans connector",
      detail: "Read-only prototype planned (see Next Unlocks)",
    },
    {
      label: "Message history automation",
      detail: "Depends on direct connector",
    },
    {
      label: "Social audits (IG / X / TikTok / Reddit)",
      detail: "Funnel-alive signals not collected yet",
    },
    {
      label: "Discord critical-alert delivery",
      detail: "Engine writes to DB; delivery deferred",
    },
    {
      label: "AI agent actions",
      detail: "QC / posting / mass-DM agents — not built",
    },
  ];

  return (
    <Section
      title="Data Brain Status"
      subtitle="What the brain currently knows about, and what it is still blind to."
    >
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        <div>
          <p
            className="text-[11px] font-semibold uppercase tracking-widest mb-2"
            style={{ color: "var(--text-quiet)" }}
          >
            Connected
          </p>
          <ul className="space-y-1.5 text-sm">
            {connected.map((row) => (
              <li
                key={row.label}
                className="flex items-start gap-2"
                style={{ color: "var(--text)" }}
              >
                <span
                  className="mt-1 h-2 w-2 rounded-full shrink-0"
                  style={{
                    background: row.ok ? "rgb(16,185,129)" : "rgb(217,119,6)",
                  }}
                />
                <span>
                  <span className="font-medium">{row.label}</span>{" "}
                  <span style={{ color: "var(--text-muted)" }}>
                    — {row.detail}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <p
            className="text-[11px] font-semibold uppercase tracking-widest mb-2"
            style={{ color: "var(--text-quiet)" }}
          >
            Not connected yet
          </p>
          <ul className="space-y-1.5 text-sm">
            {notConnected.map((row) => (
              <li
                key={row.label}
                className="flex items-start gap-2"
                style={{ color: "var(--text-muted)" }}
              >
                <span
                  className="mt-1 h-2 w-2 rounded-full shrink-0"
                  style={{ background: "rgba(100,116,139,0.5)" }}
                />
                <span>
                  <span style={{ color: "var(--text)" }}>{row.label}</span> —{" "}
                  <span>{row.detail}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Section>
  );
}

// ── Next Unlocks panel ───────────────────────────────────────────────────────

function NextUnlocksPanel() {
  const unlocks: Array<{ title: string; detail: string }> = [
    {
      title: "Direct OnlyFans read-only connector",
      detail:
        "Single-account prototype.  Captures chat, vault, mass-DM bodies, subs.  No write actions, no sends.",
    },
    {
      title: "Live chat / message capture",
      detail:
        "Real DM history into of_intelligence_messages — fuel for chat QC v2 and per-fan memory.",
    },
    {
      title: "Creator memory system",
      detail:
        "L4 memory writers: rolling brand / voice / strategy summaries persisted to business_memory_entries.",
    },
    {
      title: "Fan memory system",
      detail:
        "Per-fan briefs: spend pattern, kinks, do/don't, last-touch.  Powers smarter outbound suggestions.",
    },
    {
      title: "Discord critical-alert delivery",
      detail: "Existing alert engine pushes criticals to Discord with anti-spam guards.",
    },
    {
      title: "Social persona audits",
      detail:
        "Read-only IG / X / TikTok / Reddit signals — follower delta, posting cadence, funnel-alive checks.",
    },
    {
      title: "Per-creator agent teams",
      detail:
        "QC, chatter manager, posting, mass-message, vault, strategy, fan-memory.  Operator-approval gated.",
    },
  ];
  return (
    <Section
      title="Next Unlocks"
      subtitle="Roadmap shadow — what comes next, in priority order.  Detailed plan in docs/onlyfans-intelligence/data-brain-roadmap.md."
    >
      <ol className="space-y-2 text-sm">
        {unlocks.map((u, i) => (
          <li
            key={u.title}
            className="flex items-start gap-3"
            style={{ color: "var(--text)" }}
          >
            <span
              className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold"
              style={{
                background: "var(--bg)",
                color: "var(--text-quiet)",
                border: "1px solid var(--border)",
              }}
            >
              {i + 1}
            </span>
            <span>
              <span className="font-medium">{u.title}</span>
              <span style={{ color: "var(--text-muted)" }}> — {u.detail}</span>
            </span>
          </li>
        ))}
      </ol>
    </Section>
  );
}

// ── Per-entity sync table (kept from original Overview, lightly cleaned) ─────

function PerEntitySyncTable({ syncLogs }: { syncLogs: SyncLogRow[] }) {
  const latestRunId = syncLogs[0]?.run_id;
  if (!latestRunId) {
    return (
      <p className="text-sm" style={{ color: "var(--text-muted)" }}>
        No sync runs yet.
      </p>
    );
  }
  const byEntity = new Map<
    string,
    {
      rows: number;
      got: number;
      created: number;
      updated: number;
      skipped: number;
      errors: number;
      statuses: Set<string>;
      endpoint: string | null;
    }
  >();
  for (const log of syncLogs) {
    if (log.run_id !== latestRunId) continue;
    const cur = byEntity.get(log.entity) ?? {
      rows: 0,
      got: 0,
      created: 0,
      updated: 0,
      skipped: 0,
      errors: 0,
      statuses: new Set<string>(),
      endpoint: log.source_endpoint,
    };
    cur.rows += 1;
    cur.got += log.items_synced;
    cur.created += log.created_count;
    cur.updated += log.updated_count;
    cur.skipped += log.skipped_duplicate_count;
    cur.errors += log.error_count;
    cur.statuses.add(log.status);
    cur.endpoint = log.source_endpoint || cur.endpoint;
    byEntity.set(log.entity, cur);
  }
  const entries = Array.from(byEntity.entries()).sort(([a], [b]) =>
    a.localeCompare(b),
  );
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead style={{ color: "var(--text-quiet)" }}>
          <tr className="text-left">
            <th className="px-2 py-1 font-medium">Entity</th>
            <th className="px-2 py-1 font-medium">Status</th>
            <th className="px-2 py-1 font-medium text-right">Got</th>
            <th className="px-2 py-1 font-medium text-right">+New</th>
            <th className="px-2 py-1 font-medium text-right">~Upd</th>
            <th className="px-2 py-1 font-medium text-right">=Dup</th>
            <th className="px-2 py-1 font-medium text-right">!Err</th>
            <th className="px-2 py-1 font-medium">Endpoint</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([entity, c]) => {
            const status = c.statuses.has("error")
              ? "error"
              : c.statuses.has("write_disabled")
                ? "write_disabled"
                : c.statuses.has("dynamic_discovery_required")
                  ? "discovery_pending"
                  : c.statuses.has("not_configured")
                    ? "not_configured"
                    : c.statuses.has("not_available_from_api")
                      ? "not_available"
                      : c.statuses.has("partial")
                        ? "partial"
                        : "success";
            return (
              <tr
                key={entity}
                className="border-t"
                style={{ borderColor: "var(--border)" }}
              >
                <td className="px-2 py-1" style={{ color: "var(--text)" }}>
                  {entity}
                </td>
                <td className="px-2 py-1" style={{ color: "var(--text-muted)" }}>
                  {status}
                </td>
                <td
                  className="px-2 py-1 text-right"
                  style={{ color: "var(--text-muted)" }}
                >
                  {c.got}
                </td>
                <td
                  className="px-2 py-1 text-right"
                  style={{
                    color:
                      c.created > 0 ? "var(--accent-strong)" : "var(--text-quiet)",
                  }}
                >
                  {c.created}
                </td>
                <td
                  className="px-2 py-1 text-right"
                  style={{ color: "var(--text-muted)" }}
                >
                  {c.updated}
                </td>
                <td
                  className="px-2 py-1 text-right"
                  style={{ color: "var(--text-quiet)" }}
                >
                  {c.skipped}
                </td>
                <td
                  className="px-2 py-1 text-right"
                  style={{
                    color: c.errors > 0 ? "rgb(225,29,72)" : "var(--text-quiet)",
                  }}
                >
                  {c.errors}
                </td>
                <td
                  className="px-2 py-1 font-mono text-[10px]"
                  style={{ color: "var(--text-quiet)" }}
                >
                  {c.endpoint || "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}


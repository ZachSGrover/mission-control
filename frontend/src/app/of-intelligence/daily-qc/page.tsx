"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Beaker, CheckCircle2, Clock, Loader2, Send, RefreshCw, ShieldAlert, XCircle } from "lucide-react";

import { SectionShell, EmptyState } from "@/components/of-intelligence/SectionShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import {
  ofiApi,
  type DailySummaryShipResult,
  type QcDashboardPayload,
  type QcSchedulerSandboxRun,
  type QcSchedulerStatus,
} from "@/lib/of-intelligence/api";

type ShipState = {
  channel: "discord" | "telegram";
  ok: boolean;
  reason: string;
  status: number | null;
  ts: number;
};

type SandboxState = {
  ok: boolean;
  message: string;
  result: QcSchedulerSandboxRun | null;
  ts: number;
};

export default function OfIntelligenceDailyQcPage() {
  const { fetchWithAuth } = useAuthFetch();
  const [payload, setPayload] = useState<QcDashboardPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<null | "discord" | "telegram">(null);
  const [shipState, setShipState] = useState<ShipState | null>(null);
  const [scheduler, setScheduler] = useState<QcSchedulerStatus | null>(null);
  const [sandboxBusy, setSandboxBusy] = useState(false);
  const [sandboxState, setSandboxState] = useState<SandboxState | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const p = await ofiApi.qcDashboard(fetchWithAuth);
      setPayload(p);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
    try {
      const s = await ofiApi.qcSchedulerStatus(fetchWithAuth);
      setScheduler(s);
    } catch {
      setScheduler(null);
    }
  }, [fetchWithAuth]);

  useEffect(() => { void refresh(); }, [refresh]);

  const handleSandbox = useCallback(async () => {
    setSandboxBusy(true);
    setSandboxState(null);
    try {
      const result = await ofiApi.qcSchedulerRunSandbox(fetchWithAuth);
      setSandboxState({
        ok: true,
        message: `Sandbox tick recorded — ${result.findings_simulated} synthetic findings (NO live sends).`,
        result,
        ts: Date.now(),
      });
      const s = await ofiApi.qcSchedulerStatus(fetchWithAuth);
      setScheduler(s);
    } catch (err) {
      setSandboxState({
        ok: false,
        message: err instanceof Error ? err.message : "Sandbox run failed",
        result: null,
        ts: Date.now(),
      });
    } finally {
      setSandboxBusy(false);
    }
  }, [fetchWithAuth]);

  const handleShip = useCallback(async (channel: "discord" | "telegram") => {
    setBusy(channel);
    setShipState(null);
    try {
      const result: DailySummaryShipResult = await ofiApi.shipDailySummary(fetchWithAuth, channel);
      setShipState({
        channel,
        ok: result.publish_ok,
        reason: result.publish_reason,
        status: result.publish_status,
        ts: Date.now(),
      });
    } catch (err) {
      setShipState({
        channel,
        ok: false,
        reason: err instanceof Error ? err.message : "error",
        status: null,
        ts: Date.now(),
      });
    } finally {
      setBusy(null);
    }
  }, [fetchWithAuth]);

  return (
    <SectionShell
      title="Daily QC Dashboard"
      description="Operator-facing view: per-account health, revenue warnings, chatter mistakes, fan opportunities, sync health, and the action list. Read-only — buttons re-derive privacy-safe summaries server-side."
      actions={
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      }
    >
      {error && (
        <p className="text-sm text-red-500 mb-4">{error}</p>
      )}
      {loading && !payload && (
        <p className="inline-flex items-center gap-1 text-sm text-slate-400"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…</p>
      )}
      {!loading && payload && (
        <div className="space-y-8">
          {/* 0. Scheduler status */}
          {scheduler && (
            <Section title="Scheduler">
              <SchedulerCard
                state={scheduler}
                sandboxBusy={sandboxBusy}
                sandboxState={sandboxState}
                onRunSandbox={() => void handleSandbox()}
              />
            </Section>
          )}

          {/* 1. Per-account status */}
          <Section title="Per-Account Status">
            {payload.account_status.length === 0 ? (
              <EmptyState title="No accounts synced yet." />
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {payload.account_status.map((a) => (
                  <AccountCard key={a.account_id} a={a} />
                ))}
              </div>
            )}
          </Section>

          {/* 2. Revenue warnings */}
          <Section title="Revenue Warnings">
            {payload.revenue_warnings.length === 0 ? (
              <EmptyState title="No revenue drops detected." />
            ) : (
              <ul className="space-y-2">
                {payload.revenue_warnings.map((w) => (
                  <li key={w.account_id} className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5">
                    <AlertTriangle className="h-4 w-4 text-red-500 mt-0.5 shrink-0" />
                    <div className="flex-1 text-sm">
                      <div className="font-medium text-slate-900">{w.username ?? w.account_id}</div>
                      <div className="text-slate-600">{w.reason}</div>
                      <div className="text-xs text-slate-500 mt-1">
                        24h: ${(w.revenue_24h_cents / 100).toFixed(2)} · 7d daily avg: ${(w.revenue_7d_avg_cents / 100).toFixed(2)} · severity: {w.severity}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          {/* 3. Chatting quality */}
          <Section title="Chatting Quality (last 24h)">
            {payload.chatting_quality.length === 0 ? (
              <EmptyState title="No findings in the last 24h." />
            ) : (
              <Table
                headers={["Account", "Total", "Critical", "High", "Top codes", "Worst chatter"]}
                rows={payload.chatting_quality.map((q) => [
                  q.username ?? q.account_id,
                  q.total_findings,
                  q.critical_count,
                  q.high_count,
                  q.top_codes.map(([c, n]) => `${n}× ${c}`).join(", ") || "—",
                  q.worst_chatter ?? "—",
                ])}
              />
            )}
          </Section>

          {/* 4. Chatter mistakes */}
          <Section title="Chatter Mistakes">
            {payload.chatter_mistakes.length === 0 ? (
              <EmptyState title="No repeat mistakes." />
            ) : (
              <Table
                headers={["Chatter", "Code", "Count", "Accounts affected", "Ref"]}
                rows={payload.chatter_mistakes.map((m) => [
                  m.chatter_name,
                  m.code,
                  m.count,
                  m.accounts_affected,
                  m.dashboard_ref,
                ])}
              />
            )}
          </Section>

          {/* 5. Fan opportunities */}
          <Section title="Fan Opportunities (open)">
            {payload.fan_opportunities.length === 0 ? (
              <EmptyState title="No open opportunities." />
            ) : (
              <Table
                headers={["Code", "Severity", "Account", "Chatter", "Fan", "Age (min)", "Ref"]}
                rows={payload.fan_opportunities.map((o) => [
                  o.code,
                  o.severity,
                  o.account_username ?? "—",
                  o.chatter_name ?? "—",
                  o.fan_handle ?? "—",
                  o.age_minutes,
                  o.dashboard_ref,
                ])}
              />
            )}
          </Section>

          {/* 6. Sync health */}
          <Section title="Sync Health">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <Stat label="Errors (24h)" value={String(payload.sync_health.error_count_24h)} bad={payload.sync_health.error_count_24h > 0} />
              <Stat label="Stale accounts" value={String(payload.sync_health.stale_account_count)} bad={payload.sync_health.stale_account_count > 0} />
              <Stat label="API disconnected" value={payload.sync_health.api_disconnected ? "yes" : "no"} bad={payload.sync_health.api_disconnected} />
            </div>
            {Object.keys(payload.sync_health.last_success_per_entity).length > 0 && (
              <div className="mt-3 text-xs text-slate-500">
                Last success per entity:{" "}
                {Object.entries(payload.sync_health.last_success_per_entity)
                  .map(([k, v]) => `${k}: ${v ? new Date(v).toLocaleString() : "—"}`)
                  .join(" · ")}
              </div>
            )}
          </Section>

          {/* 7. Action list */}
          <Section title="Action List">
            {payload.action_list.length === 0 ? (
              <EmptyState title="No actions queued." />
            ) : (
              <ul className="space-y-1.5">
                {payload.action_list.map((a, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-slate-700">
                    <CheckCircle2 className="h-4 w-4 text-emerald-500 mt-0.5 shrink-0" />
                    <span>{a}</span>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          {/* 8 + 9. Send buttons */}
          <Section title="Send Daily Summary">
            <p className="text-xs text-slate-500 mb-3">
              Buttons trigger the existing server-side publishers. The Discord and Telegram payloads are
              re-derived server-side from the safe-summary renderer — fan handles, message bodies, and
              raw API content are never included regardless of what this dashboard shows above.
            </p>
            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => void handleShip("discord")}
                disabled={busy !== null}
                className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:opacity-80 disabled:opacity-50"
              >
                {busy === "discord" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
                Send Discord summary now
              </button>
              <button
                type="button"
                onClick={() => void handleShip("telegram")}
                disabled={busy !== null}
                className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                {busy === "telegram" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
                Send Telegram summary now
              </button>
            </div>
            {shipState && <ShipResultBanner state={shipState} />}
          </Section>

          <div className="text-xs text-slate-400">
            Generated {new Date(payload.generated_at).toLocaleString()}
            {payload.mock && <span className="ml-2 px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200">mock fixture</span>}
          </div>
        </div>
      )}
    </SectionShell>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function SchedulerCard({
  state,
  sandboxBusy,
  sandboxState,
  onRunSandbox,
}: {
  state: QcSchedulerStatus;
  sandboxBusy: boolean;
  sandboxState: SandboxState | null;
  onRunSandbox: () => void;
}) {
  const enabledPill = (label: string, on: boolean) => (
    <span className={`text-xs px-2 py-0.5 rounded-full border ${on ? "bg-emerald-50 text-emerald-700 border-emerald-200" : "bg-slate-100 text-slate-500 border-slate-200"}`}>
      {label}: {on ? "on" : "off"}
    </span>
  );
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <Clock className="h-4 w-4 text-slate-500" />
            <h3 className="font-semibold text-slate-900">OF Daily QC scheduler</h3>
          </div>
          <p className="text-xs text-slate-500">
            All toggles default OFF. The supervisor records skipped ticks while disabled
            so you can see the loop is healthy. Sandbox tick uses synthetic data only —
            no DB rows are read and no Discord or Telegram messages are sent.
          </p>
          <div className="flex flex-wrap gap-2 pt-1">
            {enabledPill("Daily QC", state.daily_qc_enabled)}
            {enabledPill("Live send", state.live_send_enabled)}
            {enabledPill("Discord", state.discord_enabled)}
            {enabledPill("Telegram", state.telegram_enabled)}
            <span className="text-xs px-2 py-0.5 rounded-full border bg-slate-50 text-slate-600 border-slate-200">
              source: {state.daily_qc_source_mode}
            </span>
            {state.safe_mode && (
              <span className="text-xs px-2 py-0.5 rounded-full border bg-emerald-50 text-emerald-700 border-emerald-200">
                safe mode
              </span>
            )}
          </div>
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 mt-2 text-[11px] text-amber-800">
            <strong>Real platform access is OFF.</strong> OnlyMonster read-only:{" "}
            <code>{state.onlymonster_readonly_enabled ? "enabled" : "disabled"}</code>{" "}
            · OnlyFans read-only:{" "}
            <code>{state.onlyfans_readonly_enabled ? "enabled" : "disabled"}</code>{" "}
            · Platform write:{" "}
            <code>{state.platform_write_enabled ? "enabled" : "disabled"}</code>
            {!state.onlymonster_readonly_enabled &&
              !state.onlyfans_readonly_enabled &&
              !state.platform_write_enabled && (
                <span className="block mt-1 text-amber-700">
                  Daily QC is reading{" "}
                  {state.daily_qc_source_mode === "synthetic"
                    ? "synthetic fixture data"
                    : state.daily_qc_source_mode === "local_ofi"
                      ? "local OFI database rows"
                      : "no data (selected source is disconnected)"}
                  . No live OnlyFans / OnlyMonster calls will happen.
                </span>
              )}
          </div>
        </div>
        <button
          type="button"
          onClick={onRunSandbox}
          disabled={sandboxBusy}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          title="Runs against synthetic data; never sends live"
        >
          {sandboxBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Beaker className="h-3.5 w-3.5" />}
          Run sandbox now (no live sends)
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs text-slate-600">
        <div>
          <div className="text-[10px] uppercase tracking-wide text-slate-400">Last run</div>
          <div className="text-slate-700 mt-0.5">
            {state.last_run_at ? new Date(state.last_run_at).toLocaleString() : "—"}
          </div>
          {state.last_status && (
            <div className="text-[11px] mt-0.5">
              status: <span className="font-medium">{state.last_status}</span>
              {state.last_skipped_reason && <span className="text-slate-500"> · {state.last_skipped_reason}</span>}
              {state.last_error_summary && <span className="text-red-500"> · {state.last_error_summary}</span>}
            </div>
          )}
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wide text-slate-400">Next run</div>
          <div className="text-slate-700 mt-0.5">
            {state.next_run_at ? new Date(state.next_run_at).toLocaleString() : "—"}
          </div>
          <div className="text-[11px] text-slate-500 mt-0.5">
            tick interval: {Math.round(state.tick_interval_seconds / 60)} min
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wide text-slate-400">Last counts</div>
          <div className="text-slate-700 mt-0.5">
            accounts: {state.last_accounts_checked ?? "—"} · findings: {state.last_findings_count ?? "—"}
          </div>
          <div className="text-[11px] text-slate-500 mt-0.5">
            last source: {state.last_source_mode ?? "—"}
            {state.last_source_confidence && ` · confidence: ${state.last_source_confidence}`}
          </div>
        </div>
      </div>

      {sandboxState && (
        <div
          className={`text-xs px-3 py-2 rounded-lg border ${
            sandboxState.ok
              ? "bg-amber-50 text-amber-700 border-amber-200"
              : "bg-red-50 text-red-700 border-red-200"
          }`}
        >
          {sandboxState.ok ? "🧪 " : "⚠ "}
          {sandboxState.message}
          {sandboxState.result && (
            <span className="text-slate-600">
              {" "}— sandbox accounts: {sandboxState.result.accounts_checked}, synthetic findings: {sandboxState.result.findings_simulated}
            </span>
          )}
        </div>
      )}

      {state.recent_jobs && state.recent_jobs.length > 0 && (
        <div className="pt-2 border-t border-slate-100">
          <div className="text-[10px] uppercase tracking-wide text-slate-400 mb-1.5">
            Recent ticks
          </div>
          <ul className="space-y-1">
            {state.recent_jobs.slice(0, 5).map((job) => (
              <li
                key={job.id}
                className="flex flex-wrap items-center gap-2 text-[11px] text-slate-600"
              >
                <span className="font-mono text-slate-500">
                  {new Date(job.started_at).toLocaleString()}
                </span>
                <span className="text-slate-700">{job.job_kind}</span>
                <span className="text-slate-500">via {job.triggered_by}</span>
                <span
                  className={`px-1.5 py-0.5 rounded border text-[10px] ${
                    job.status === "completed"
                      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                      : job.status === "skipped"
                        ? "bg-slate-100 text-slate-600 border-slate-200"
                        : job.status === "failed"
                          ? "bg-red-50 text-red-700 border-red-200"
                          : "bg-blue-50 text-blue-700 border-blue-200"
                  }`}
                >
                  {job.status}
                </span>
                {job.skipped_reason && (
                  <span className="text-slate-500">· {job.skipped_reason}</span>
                )}
                {job.error_summary && (
                  <span className="text-red-500">· {job.error_summary}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wide">{title}</h2>
      {children}
    </section>
  );
}

function AccountCard({ a }: { a: QcDashboardPayload["account_status"][number] }) {
  const healthColor: Record<string, string> = {
    ok:       "bg-emerald-50 text-emerald-700 border-emerald-200",
    stale:    "bg-amber-50 text-amber-700 border-amber-200",
    blocked:  "bg-red-50 text-red-700 border-red-200",
    expired:  "bg-red-50 text-red-700 border-red-200",
    lost:     "bg-red-50 text-red-700 border-red-200",
  };
  const badge = healthColor[a.health_status] ?? "bg-slate-50 text-slate-600 border-slate-200";
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold text-slate-900 truncate">{a.username ?? a.account_id}</span>
        <span className={`text-xs px-2 py-0.5 rounded-full border ${badge}`}>{a.health_status}</span>
      </div>
      <div className="text-xs text-slate-500">
        Last sync: {a.hours_since_sync !== null ? `${a.hours_since_sync}h ago` : "—"}
      </div>
      <div className="text-xs text-slate-700">
        24h ${(a.revenue_24h_cents / 100).toFixed(2)} · 7d avg ${(a.revenue_7d_avg_cents / 100).toFixed(2)}
      </div>
      {a.open_layer1_codes.length > 0 && (
        <div className="text-[11px] text-red-600 inline-flex items-center gap-1">
          <XCircle className="h-3 w-3" /> {a.open_layer1_codes.join(", ")}
        </div>
      )}
      {a.open_layer2_codes.length > 0 && (
        <div className="text-[11px] text-amber-600 inline-flex items-center gap-1">
          <ShieldAlert className="h-3 w-3" /> {a.open_layer2_codes.join(", ")}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, bad }: { label: string; value: string; bad: boolean }) {
  return (
    <div className={`rounded-lg border px-4 py-3 ${bad ? "bg-red-50 border-red-200" : "bg-slate-50 border-slate-200"}`}>
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`text-lg font-semibold mt-0.5 ${bad ? "text-red-700" : "text-slate-900"}`}>{value}</div>
    </div>
  );
}

function Table({ headers, rows }: { headers: string[]; rows: (string | number)[][] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-slate-600">
          <tr>
            {headers.map((h, i) => (
              <th key={i} className="px-3 py-2 text-left text-xs uppercase tracking-wide">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t border-slate-100">
              {row.map((cell, j) => (
                <td key={j} className="px-3 py-2 text-slate-700 align-top">{String(cell)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ShipResultBanner({ state }: { state: ShipState }) {
  const cls = state.ok
    ? "bg-emerald-50 text-emerald-700 border-emerald-200"
    : state.reason === "no_telegram" || state.reason === "no_telegram_chat" || state.reason === "telegram_disabled" || state.reason === "disabled" || state.reason === "no_webhook"
      ? "bg-amber-50 text-amber-700 border-amber-200"
      : "bg-red-50 text-red-700 border-red-200";
  return (
    <div className={`mt-3 text-sm px-3 py-2 rounded-lg border ${cls}`}>
      {state.channel}: {state.ok ? `✅ sent` : `⚠ ${state.reason}`}
      {state.status !== null && ` (HTTP ${state.status})`}
    </div>
  );
}

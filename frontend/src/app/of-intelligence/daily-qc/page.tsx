"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, Send, RefreshCw, ShieldAlert, XCircle } from "lucide-react";

import { SectionShell, EmptyState } from "@/components/of-intelligence/SectionShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import {
  ofiApi,
  type DailySummaryShipResult,
  type QcDashboardPayload,
} from "@/lib/of-intelligence/api";

type ShipState = {
  channel: "discord" | "telegram";
  ok: boolean;
  reason: string;
  status: number | null;
  ts: number;
};

export default function OfIntelligenceDailyQcPage() {
  const { fetchWithAuth } = useAuthFetch();
  const [payload, setPayload] = useState<QcDashboardPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<null | "discord" | "telegram">(null);
  const [shipState, setShipState] = useState<ShipState | null>(null);

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
  }, [fetchWithAuth]);

  useEffect(() => { void refresh(); }, [refresh]);

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

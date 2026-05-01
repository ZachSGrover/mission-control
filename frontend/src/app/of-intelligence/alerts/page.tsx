"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Loader2, Play } from "lucide-react";

import { SectionShell, StatusBadge, EmptyState } from "@/components/of-intelligence/SectionShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import { ofiApi, type AlertRow, formatRelative } from "@/lib/of-intelligence/api";

export default function OfIntelligenceAlertsPage() {
  const { fetchWithAuth } = useAuthFetch();
  const [rows, setRows] = useState<AlertRow[]>([]);
  const [onlyOpen, setOnlyOpen] = useState(true);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await ofiApi.alerts(fetchWithAuth, { onlyOpen, limit: 200 }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [fetchWithAuth, onlyOpen]);

  useEffect(() => { void refresh(); }, [refresh]);

  const onEvaluate = useCallback(async () => {
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const summary = await ofiApi.evaluateAlerts(fetchWithAuth);
      setInfo(`Evaluated ${summary.rules_run} rules — created ${summary.alerts_created}, skipped ${summary.alerts_skipped_existing} existing.`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [fetchWithAuth, refresh]);

  const onAction = useCallback(async (id: string, action: "ack" | "resolve") => {
    try {
      if (action === "ack") await ofiApi.ackAlert(fetchWithAuth, id);
      else await ofiApi.resolveAlert(fetchWithAuth, id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [fetchWithAuth, refresh]);

  return (
    <SectionShell
      title="Alerts"
      description="Operational alerts from the rule engine. Acknowledge to silence; resolve once the underlying issue is fixed."
      actions={
        <div className="flex items-center gap-2">
          <label className="text-xs flex items-center gap-1" style={{ color: "var(--text-muted)" }}>
            <input
              type="checkbox"
              checked={onlyOpen}
              onChange={(e) => setOnlyOpen(e.target.checked)}
            />
            Only open
          </label>
          <button
            type="button"
            onClick={() => void onEvaluate()}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50"
            style={{ background: "var(--accent-strong)", color: "white" }}
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
            Evaluate now
          </button>
        </div>
      }
    >
      {(error || info) && (
        <div
          className="mb-4 rounded-md border p-3 text-sm"
          style={{
            borderColor: error ? "rgb(248,113,113)" : "var(--border)",
            color: error ? "rgb(225,29,72)" : "var(--text-muted)",
          }}
        >
          {error || info}
        </div>
      )}

      {loading ? (
        <EmptyState title="Loading alerts…" />
      ) : rows.length === 0 ? (
        <EmptyState
          title={onlyOpen ? "No open alerts." : "No alerts on record."}
          hint="Click ‘Evaluate now’ to run the rule engine against the latest synced data."
        />
      ) : (
        <ul className="space-y-2">
          {rows.map((a) => (
            <li
              key={a.id}
              className="rounded-xl border p-4"
              style={{ background: "var(--surface)", borderColor: "var(--border)" }}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <StatusBadge status={a.severity} />
                    <StatusBadge status={a.status} />
                    <span className="text-xs" style={{ color: "var(--text-quiet)" }}>{formatRelative(a.created_at)}</span>
                  </div>
                  <p className="mt-1 text-sm font-medium" style={{ color: "var(--text)" }}>{a.title}</p>
                  {a.message && (
                    <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>{a.message}</p>
                  )}
                  <p className="text-[11px] mt-1 font-mono" style={{ color: "var(--text-quiet)" }}>{a.code}</p>
                </div>
                {a.status === "open" && (
                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      type="button"
                      onClick={() => void onAction(a.id, "ack")}
                      className="rounded-md border px-2 py-1 text-xs"
                      style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
                    >
                      Acknowledge
                    </button>
                    <button
                      type="button"
                      onClick={() => void onAction(a.id, "resolve")}
                      className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium"
                      style={{ background: "var(--accent-strong)", color: "white" }}
                    >
                      <CheckCircle2 className="h-3 w-3" />
                      Resolve
                    </button>
                  </div>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </SectionShell>
  );
}

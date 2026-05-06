"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";

import { SectionShell, EmptyState } from "@/components/of-intelligence/SectionShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import { ofiApi, type QcReportRow, type QcReportDetail, formatRelative } from "@/lib/of-intelligence/api";

export default function OfIntelligenceQcReportsPage() {
  const { fetchWithAuth } = useAuthFetch();
  const [rows, setRows] = useState<QcReportRow[]>([]);
  const [selected, setSelected] = useState<QcReportDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const reports = await ofiApi.qcReports(fetchWithAuth);
      setRows(reports);
      if (reports.length && !selected) {
        const first = await ofiApi.qcReport(fetchWithAuth, reports[0].id);
        setSelected(first);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [fetchWithAuth, selected]);

  useEffect(() => { void refresh(); }, [refresh]);

  const onGenerate = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const report = await ofiApi.generateQcReport(fetchWithAuth);
      setSelected(report);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [fetchWithAuth, refresh]);

  const onSelect = useCallback(async (id: string) => {
    setError(null);
    try {
      setSelected(await ofiApi.qcReport(fetchWithAuth, id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [fetchWithAuth]);

  return (
    <SectionShell
      title="QC Reports"
      description="Daily QC bot output. Direct, operational, action-oriented. Generate a fresh report to evaluate today's data."
      actions={
        <button
          type="button"
          onClick={() => void onGenerate()}
          disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50"
          style={{ background: "var(--accent-strong)", color: "white" }}
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
          Generate report
        </button>
      }
    >
      {error && (
        <div className="mb-4 rounded-md border p-3 text-sm" style={{ borderColor: "rgb(248,113,113)", color: "rgb(225,29,72)" }}>
          {error}
        </div>
      )}

      {loading ? (
        <EmptyState title="Loading reports…" />
      ) : rows.length === 0 ? (
        <EmptyState title="No QC reports yet." hint="Click ‘Generate report’ to produce the first one." />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <aside className="lg:col-span-1 space-y-2">
            {rows.map((r) => {
              const isActive = selected?.id === r.id;
              return (
                <button
                  key={r.id}
                  type="button"
                  onClick={() => void onSelect(r.id)}
                  className="w-full text-left rounded-md border p-3 text-sm transition-colors"
                  style={{
                    background: isActive ? "var(--accent-soft)" : "var(--surface)",
                    borderColor: "var(--border)",
                    color: isActive ? "var(--accent-strong)" : "var(--text)",
                  }}
                >
                  <p className="font-medium">{new Date(r.report_date).toLocaleDateString()}</p>
                  <p className="text-xs mt-0.5" style={{ color: "var(--text-quiet)" }}>
                    {r.critical_alerts_count} critical · {r.accounts_reviewed} accts · {formatRelative(r.generated_at)}
                  </p>
                </button>
              );
            })}
          </aside>

          <article
            className="lg:col-span-2 rounded-xl border p-5"
            style={{ background: "var(--surface)", borderColor: "var(--border)" }}
          >
            {!selected ? (
              <p className="text-sm" style={{ color: "var(--text-muted)" }}>Select a report on the left.</p>
            ) : (
              <pre
                className="whitespace-pre-wrap text-sm leading-relaxed font-sans"
                style={{ color: "var(--text)" }}
              >
{selected.markdown ?? selected.summary ?? "(empty report)"}
              </pre>
            )}
          </article>
        </div>
      )}
    </SectionShell>
  );
}

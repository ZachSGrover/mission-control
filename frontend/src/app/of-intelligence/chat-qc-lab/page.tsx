"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useMemo, useState } from "react";

import { EmptyState, SectionShell, StatPill, StatusBadge } from "@/components/of-intelligence/SectionShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import {
  formatRelative,
  ofiApi,
  type ChatImportRow,
  type ChatQcFindingRow,
  type ChatQcRunResponse,
} from "@/lib/of-intelligence/api";

/**
 * Chat QC Lab — operator-facing workspace for the manual chat-data
 * import bridge.  This is NOT a live scraper.  Every row this page
 * displays came from a JSON / CSV upload that an operator initiated.
 *
 * Page flow:
 *   1. Operator uploads or pastes sample chat data.
 *   2. Backend parses, dedups, persists into `of_intelligence_messages`
 *      and creates an `of_intelligence_chat_imports` row.
 *   3. Operator clicks "Run QC" — backend evaluates the 13 text rules
 *      and writes findings into `of_intelligence_chat_qc_findings`.
 *   4. Findings render below with severity, why-it-matters, suggested
 *      better response, and recommended action.
 */
export default function ChatQcLabPage() {
  const { fetchWithAuth } = useAuthFetch();
  const [imports, setImports] = useState<ChatImportRow[]>([]);
  const [findings, setFindings] = useState<ChatQcFindingRow[]>([]);
  const [selectedImportId, setSelectedImportId] = useState<string | null>(null);
  const [paste, setPaste] = useState("");
  const [label, setLabel] = useState("");
  const [sourceKind, setSourceKind] = useState<"manual_json" | "manual_csv" | "paste">("manual_json");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [limitationsNote, setLimitationsNote] = useState<string | null>(null);
  const [lastRun, setLastRun] = useState<ChatQcRunResponse | null>(null);
  const [severityFilter, setSeverityFilter] = useState<"all" | "info" | "warn" | "critical">("all");

  const loadImports = useCallback(async () => {
    try {
      setImports(await ofiApi.chatLabImports(fetchWithAuth));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [fetchWithAuth]);

  const loadFindings = useCallback(
    async (importId: string | null) => {
      try {
        const rows = await ofiApi.chatLabFindings(fetchWithAuth, {
          importId: importId ?? undefined,
          limit: 500,
        });
        setFindings(rows);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [fetchWithAuth],
  );

  useEffect(() => {
    void loadImports();
    void loadFindings(null);
    void ofiApi.chatLabLimitations(fetchWithAuth)
      .then((r) => setLimitationsNote(r.note))
      .catch(() => { /* limitations is informational only */ });
  }, [loadImports, loadFindings, fetchWithAuth]);

  const handleUpload = useCallback(async () => {
    setBusy(true);
    setError(null);
    setInfo(null);
    setLastRun(null);
    try {
      const res = await ofiApi.uploadChatImport(fetchWithAuth, {
        payload: paste,
        source_kind: sourceKind,
        label: label.trim() || null,
      });
      setInfo(
        `Imported ${res.messages_inserted} new messages across ${res.total_chats_seen} chats `
        + `(${res.messages_skipped_dup} duplicates skipped). Status: ${res.status}.`,
      );
      setSelectedImportId(res.import_id);
      await loadImports();
      await loadFindings(res.import_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [paste, sourceKind, label, fetchWithAuth, loadImports, loadFindings]);

  const handleRunQc = useCallback(async (importId: string) => {
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const summary = await ofiApi.runChatQc(fetchWithAuth, importId);
      setLastRun(summary);
      setSelectedImportId(importId);
      await loadImports();
      await loadFindings(importId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [fetchWithAuth, loadImports, loadFindings]);

  const filteredFindings = useMemo(() => {
    if (severityFilter === "all") return findings;
    return findings.filter((f) => f.severity === severityFilter);
  }, [findings, severityFilter]);

  const sevCounts = useMemo(() => {
    const c = { info: 0, warn: 0, critical: 0 };
    for (const f of findings) {
      if (f.severity === "info") c.info += 1;
      else if (f.severity === "warn") c.warn += 1;
      else if (f.severity === "critical") c.critical += 1;
    }
    return c;
  }, [findings]);

  return (
    <SectionShell
      title="Chat QC Lab"
      description="The first manual bridge for real chat QC. Live scraping is not connected yet. Use sample / imported chat data to validate the QC engine. Message text is sensitive — do not paste real client data unless explicitly approved."
    >
      {limitationsNote && (
        <div
          className="mb-4 rounded-md border p-3 text-xs"
          style={{
            background: "rgba(245,158,11,0.08)",
            borderColor: "rgba(245,158,11,0.4)",
            color: "rgb(180,83,9)",
          }}
        >
          <strong>Limitations.</strong> {limitationsNote}
        </div>
      )}

      {/* Sensitivity banner — separate from Limitations so it is impossible
          to miss before pasting real data. */}
      <div
        className="mb-4 rounded-md border p-3 text-xs"
        style={{
          background: "rgba(244,63,94,0.06)",
          borderColor: "rgba(244,63,94,0.4)",
          color: "rgb(159,18,57)",
        }}
      >
        <strong>Sensitive data.</strong> Treat every message body as
        confidential. The lab does not call OnlyFans or OnlyMonster, does not
        post anywhere, and does not log message text — but uploaded content is
        persisted to the local database for QC evaluation. Do not paste real
        client conversations unless Zach has explicitly approved that import.
        Use the sample fixture (<code>backend/fixtures/chat_qc_lab/sample_chats.json</code>)
        to test the engine.
      </div>

      {error && (
        <div className="mb-4 rounded-md border p-3 text-sm" style={{ borderColor: "rgb(248,113,113)", color: "rgb(225,29,72)" }}>
          {error}
        </div>
      )}
      {info && (
        <div className="mb-4 rounded-md border p-3 text-sm" style={{ borderColor: "rgba(16,185,129,0.5)", color: "rgb(5,150,105)" }}>
          {info}
        </div>
      )}

      {/* ── Upload ──────────────────────────────────────────────────────── */}
      <div
        className="rounded-xl border p-5 mb-6"
        style={{ background: "var(--surface)", borderColor: "var(--border)" }}
      >
        <h2
          className="text-sm font-semibold uppercase tracking-widest mb-3"
          style={{ color: "var(--text-quiet)" }}
        >
          Upload sample chat data
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
          <div>
            <label className="text-[11px] font-semibold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>
              Format
            </label>
            <select
              value={sourceKind}
              onChange={(e) => setSourceKind(e.target.value as typeof sourceKind)}
              className="mt-1 w-full rounded-md border px-2 py-2 text-sm"
              style={{ background: "var(--bg)", borderColor: "var(--border)", color: "var(--text)" }}
            >
              <option value="manual_json">JSON</option>
              <option value="manual_csv">CSV</option>
              <option value="paste">Paste (JSON-shaped)</option>
            </select>
          </div>
          <div className="md:col-span-2">
            <label className="text-[11px] font-semibold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>
              Label (optional)
            </label>
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="e.g. AdamJaxon — week of 2026-04-21 sample"
              className="mt-1 w-full rounded-md border px-3 py-2 text-sm"
              style={{ background: "var(--bg)", borderColor: "var(--border)", color: "var(--text)" }}
            />
          </div>
        </div>
        <textarea
          value={paste}
          onChange={(e) => setPaste(e.target.value)}
          rows={8}
          placeholder={
            sourceKind === "manual_csv"
              ? "chat_id,message_id,sender_type,timestamp,message_text,price,purchased\nchat_1,msg_1,fan,2026-04-21T10:00:00Z,hey what do you have today,,\n…"
              : '[\n  {"chat_id":"chat_1","message_id":"m1","sender_type":"fan","timestamp":"2026-04-21T10:00:00Z","message_text":"hey what do you have today"},\n  …\n]'
          }
          className="w-full rounded-md border px-3 py-2 text-xs font-mono"
          style={{ background: "var(--bg)", borderColor: "var(--border)", color: "var(--text)" }}
        />
        <div className="mt-3 flex items-center gap-3">
          <button
            onClick={() => void handleUpload()}
            disabled={busy || !paste.trim()}
            className="rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
            style={{
              background: "var(--accent-strong)",
              borderColor: "var(--accent-strong)",
              color: "white",
            }}
          >
            {busy ? "Working…" : "Upload"}
          </button>
          {selectedImportId && (
            <button
              onClick={() => void handleRunQc(selectedImportId)}
              disabled={busy}
              className="rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
              style={{
                background: "var(--surface)",
                borderColor: "var(--border)",
                color: "var(--text)",
              }}
            >
              Run QC on latest import
            </button>
          )}
        </div>
        <p className="text-xs mt-3" style={{ color: "var(--text-muted)" }}>
          Operator-only. No external calls. Message bodies are not logged.
          Re-uploading the same content de-duplicates by message_id (or by
          deterministic hash if no id is provided).
        </p>
      </div>

      {/* ── Import history ─────────────────────────────────────────────── */}
      <div
        className="rounded-xl border overflow-hidden mb-6"
        style={{ borderColor: "var(--border)", background: "var(--surface)" }}
      >
        <div className="px-4 py-2 border-b" style={{ borderColor: "var(--border)" }}>
          <p
            className="text-[11px] font-semibold uppercase tracking-widest"
            style={{ color: "var(--text-quiet)" }}
          >
            Recent imports
          </p>
        </div>
        {imports.length === 0 ? (
          <div className="p-6 text-center text-sm" style={{ color: "var(--text-muted)" }}>
            No imports yet.  Upload a sample above to begin.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead style={{ background: "var(--bg)", color: "var(--text-quiet)" }}>
              <tr className="text-left">
                <th className="px-3 py-2 font-medium">Started</th>
                <th className="px-3 py-2 font-medium">Label</th>
                <th className="px-3 py-2 font-medium">Format</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Chats</th>
                <th className="px-3 py-2 font-medium">Messages</th>
                <th className="px-3 py-2 font-medium">Findings</th>
                <th className="px-3 py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {imports.map((imp) => (
                <tr
                  key={imp.id}
                  className="border-t cursor-pointer"
                  style={{
                    borderColor: "var(--border)",
                    background: imp.id === selectedImportId ? "rgba(99,102,241,0.06)" : undefined,
                  }}
                  onClick={() => {
                    setSelectedImportId(imp.id);
                    void loadFindings(imp.id);
                  }}
                >
                  <td className="px-3 py-2" style={{ color: "var(--text-muted)" }}>
                    {formatRelative(imp.started_at)}
                  </td>
                  <td className="px-3 py-2" style={{ color: "var(--text)" }}>
                    {imp.label || <span style={{ color: "var(--text-quiet)" }}>(no label)</span>}
                  </td>
                  <td className="px-3 py-2" style={{ color: "var(--text-muted)" }}>
                    {imp.source_kind}
                  </td>
                  <td className="px-3 py-2"><StatusBadge status={imp.status} /></td>
                  <td className="px-3 py-2" style={{ color: "var(--text-muted)" }}>
                    {imp.total_chats}
                  </td>
                  <td className="px-3 py-2" style={{ color: "var(--text-muted)" }}>
                    {imp.messages_inserted}
                    {imp.messages_skipped_dup > 0 && (
                      <span className="ml-1 text-xs" style={{ color: "var(--text-quiet)" }}>
                        (+{imp.messages_skipped_dup} dup)
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2" style={{ color: "var(--text-muted)" }}>
                    {imp.findings_count}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        void handleRunQc(imp.id);
                      }}
                      disabled={busy}
                      className="text-xs hover:underline disabled:opacity-50"
                      style={{ color: "var(--accent-strong)" }}
                    >
                      Run QC →
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ── QC run summary + severity filter ──────────────────────────── */}
      {(lastRun || findings.length > 0) && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
          <StatPill
            label="Findings (filtered scope)"
            value={findings.length.toString()}
            hint={selectedImportId ? "Scoped to selected import" : "All imports"}
          />
          <StatPill label="Critical" value={sevCounts.critical.toString()} />
          <StatPill label="Warn" value={sevCounts.warn.toString()} />
          <StatPill label="Info" value={sevCounts.info.toString()} />
        </div>
      )}

      {findings.length > 0 && (
        <div className="mb-3 flex items-center gap-2">
          <span className="text-[11px] font-semibold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>
            Filter:
          </span>
          {(["all", "critical", "warn", "info"] as const).map((s) => (
            <button
              key={s}
              onClick={() => setSeverityFilter(s)}
              className="rounded-md border px-2 py-1 text-xs"
              style={{
                background: severityFilter === s ? "var(--accent-strong)" : "var(--surface)",
                borderColor: "var(--border)",
                color: severityFilter === s ? "white" : "var(--text-muted)",
              }}
            >
              {s}
            </button>
          ))}
          {selectedImportId && (
            <button
              onClick={() => {
                setSelectedImportId(null);
                void loadFindings(null);
              }}
              className="ml-2 text-xs hover:underline"
              style={{ color: "var(--text-muted)" }}
            >
              clear import filter
            </button>
          )}
        </div>
      )}

      {/* ── Findings list ─────────────────────────────────────────────── */}
      {findings.length === 0 ? (
        <EmptyState
          title="No findings yet."
          hint="Upload a chat sample and click Run QC to evaluate."
        />
      ) : (
        <div className="space-y-3">
          {filteredFindings.map((f) => (
            <FindingCard key={f.id} finding={f} />
          ))}
          {filteredFindings.length === 0 && (
            <EmptyState title={`No ${severityFilter} findings.`} />
          )}
        </div>
      )}
    </SectionShell>
  );
}

function FindingCard({ finding }: { finding: ChatQcFindingRow }) {
  const palette = severityPalette(finding.severity);
  return (
    <div
      className="rounded-xl border p-4"
      style={{
        background: "var(--surface)",
        borderColor: "var(--border)",
        borderLeft: `4px solid ${palette.accent}`,
      }}
    >
      <div className="flex items-start gap-3">
        <span
          className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider shrink-0"
          style={{ background: palette.bg, color: palette.fg }}
        >
          {finding.severity}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <h3 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
              {finding.title}
            </h3>
            <span className="text-xs shrink-0" style={{ color: "var(--text-quiet)" }}>
              {finding.rule_id}
            </span>
          </div>
          <p className="text-sm mt-1" style={{ color: "var(--text)" }}>
            {finding.issue}
          </p>
          {finding.message_excerpt && (
            <pre
              className="mt-2 rounded-md p-2 text-xs whitespace-pre-wrap"
              style={{
                background: "var(--bg)",
                color: "var(--text-muted)",
                fontFamily: "ui-monospace,monospace",
                margin: 0,
              }}
            >
              {finding.message_excerpt}
            </pre>
          )}
          <div className="mt-2 grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
            <div>
              <p className="font-semibold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>
                Why it matters
              </p>
              <p className="mt-0.5" style={{ color: "var(--text-muted)" }}>
                {finding.why_it_matters}
              </p>
            </div>
            {finding.suggested_better && (
              <div>
                <p className="font-semibold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>
                  Suggested better
                </p>
                <p className="mt-0.5" style={{ color: "var(--text-muted)" }}>
                  {finding.suggested_better}
                </p>
              </div>
            )}
            {finding.recommended_action && (
              <div>
                <p className="font-semibold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>
                  Action for Zach
                </p>
                <p className="mt-0.5" style={{ color: "var(--text-muted)" }}>
                  {finding.recommended_action}
                </p>
              </div>
            )}
          </div>
          <div className="mt-2 text-[11px]" style={{ color: "var(--text-quiet)" }}>
            chat <code>{finding.chat_source_id ?? "?"}</code>
            {finding.chatter_source_id && (
              <> · chatter <code>{finding.chatter_source_id}</code></>
            )}
            {finding.account_source_id && (
              <> · account <code>{finding.account_source_id}</code></>
            )}
            <> · {formatRelative(finding.created_at)}</>
          </div>
        </div>
      </div>
    </div>
  );
}

function severityPalette(severity: string) {
  switch (severity) {
    case "critical":
      return {
        accent: "rgb(225,29,72)",
        bg: "rgba(244,63,94,0.12)",
        fg: "rgb(225,29,72)",
      };
    case "warn":
      return {
        accent: "rgb(217,119,6)",
        bg: "rgba(245,158,11,0.12)",
        fg: "rgb(217,119,6)",
      };
    case "info":
    default:
      return {
        accent: "rgb(71,85,105)",
        bg: "rgba(100,116,139,0.12)",
        fg: "rgb(71,85,105)",
      };
  }
}

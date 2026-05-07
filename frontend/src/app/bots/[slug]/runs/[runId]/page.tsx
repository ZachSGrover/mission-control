"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Download } from "lucide-react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import { getApiBaseUrl } from "@/lib/api-base";

import { SandboxBanner } from "../../_lib/SandboxBanner";
import { formatRelative, type RunDetail, RT_BOT_SLUG } from "../../_lib/rt-bot";

function RunDetailContent() {
  const params = useParams();
  const slug = (Array.isArray(params?.slug) ? params.slug[0] : params?.slug) ?? "";
  const runId = (Array.isArray(params?.runId) ? params.runId[0] : params?.runId) ?? "";
  const { fetchWithAuth } = useAuthFetch();
  const [run, setRun] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"pause" | "reject" | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchWithAuth(
        `${getApiBaseUrl()}/api/v1/bots/${slug}/runs/${runId}`,
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setRun((await res.json()) as RunDetail);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load run.");
    } finally {
      setLoading(false);
    }
  }, [fetchWithAuth, runId, slug]);

  useEffect(() => {
    if (slug && runId) void refresh();
  }, [slug, runId, refresh]);

  const onAction = useCallback(
    async (action: "pause" | "reject") => {
      setBusy(action);
      try {
        const res = await fetchWithAuth(
          `${getApiBaseUrl()}/api/v1/bots/${slug}/runs/${runId}/${action}`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
          },
        );
        if (!res.ok) {
          const body = (await res.json().catch(() => null)) as
            | { detail?: { error?: string } | string }
            | null;
          throw new Error(
            (typeof body?.detail === "object" ? body.detail?.error : body?.detail) ??
              `HTTP ${res.status}`,
          );
        }
        await refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Action failed");
      } finally {
        setBusy(null);
      }
    },
    [fetchWithAuth, refresh, runId, slug],
  );

  const downloadCsv = useCallback(() => {
    window.open(
      `${getApiBaseUrl()}/api/v1/bots/${slug}/runs/${runId}/export`,
      "_blank",
    );
  }, [runId, slug]);

  if (slug !== RT_BOT_SLUG) {
    return (
      <main
        className="flex-1 flex items-center justify-center"
        style={{ background: "var(--bg)" }}
      >
        <p className="text-sm" style={{ color: "var(--text-quiet)" }}>
          This run lifecycle is only available for the X DM Bot RTxRT.
        </p>
      </main>
    );
  }

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
          Run {runId.slice(0, 8)}…
        </h1>
        <SandboxBanner />

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

        {loading || !run ? (
          <p className="text-sm" style={{ color: "var(--text-quiet)" }}>
            Loading…
          </p>
        ) : (
          <>
            <section
              className="rounded-xl p-4 grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs"
              style={{
                background: "var(--surface-strong)",
                border: "1px solid var(--border)",
              }}
            >
              <Field label="Status" value={run.status} />
              <Field label="Mode" value={run.mode} />
              <Field label="Profile" value={run.profile_name} />
              <Field label="Target count" value={String(run.target_count)} />
              <Field label="Scan count" value={String(run.scan_count)} />
              <Field label="Sent count" value={String(run.sent_count)} />
              <Field label="Read-only" value={String(run.readonly_count)} />
              <Field
                label="Started"
                value={run.started_at ? formatRelative(run.started_at) : "—"}
              />
              <Field
                label="Completed"
                value={run.completed_at ? formatRelative(run.completed_at) : "—"}
              />
              <Field
                label="Message preview (≤80)"
                value={run.message_preview ?? "—"}
                full
              />
            </section>

            <section className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => void onAction("pause")}
                disabled={busy !== null || !["queued", "running_scan"].includes(run.status)}
                className="rounded-lg px-3 py-1.5 text-xs disabled:opacity-50"
                style={{ background: "rgba(234,179,8,0.15)", color: "#eab308" }}
              >
                {busy === "pause" ? "Pausing…" : "Pause"}
              </button>
              <button
                type="button"
                onClick={() => void onAction("reject")}
                disabled={
                  busy !== null ||
                  !["draft", "queued", "paused"].includes(run.status)
                }
                className="rounded-lg px-3 py-1.5 text-xs disabled:opacity-50"
                style={{ background: "rgba(239,68,68,0.15)", color: "#ef4444" }}
              >
                {busy === "reject" ? "Rejecting…" : "Reject"}
              </button>
              <button
                type="button"
                onClick={downloadCsv}
                className="rounded-lg px-3 py-1.5 text-xs flex items-center gap-1"
                style={{
                  background: "var(--surface-strong)",
                  border: "1px solid var(--border)",
                  color: "var(--text-muted)",
                }}
              >
                <Download className="h-3 w-3" /> Export CSV
              </button>
            </section>

            <section>
              <h2 className="text-sm font-semibold mb-2" style={{ color: "var(--text)" }}>
                Outputs
              </h2>
              <div className="space-y-2">
                {run.outputs.map((o) => (
                  <details
                    key={o.id}
                    className="rounded-xl px-3 py-2"
                    style={{
                      background: "var(--surface-strong)",
                      border: "1px solid var(--border)",
                    }}
                  >
                    <summary className="text-xs cursor-pointer" style={{ color: "var(--text)" }}>
                      <span className="font-mono">{o.output_type}</span>{" "}
                      <span style={{ color: "var(--text-quiet)" }}>
                        {formatRelative(o.created_at)}
                      </span>
                    </summary>
                    <pre
                      className="mt-2 text-[11px] overflow-auto"
                      style={{ color: "var(--text-muted)" }}
                    >
                      {JSON.stringify(o.content, null, 2)}
                    </pre>
                  </details>
                ))}
                {run.outputs.length === 0 && (
                  <p className="text-xs" style={{ color: "var(--text-quiet)" }}>
                    No outputs yet.
                  </p>
                )}
              </div>
            </section>
          </>
        )}
      </div>
    </main>
  );
}

function Field({ label, value, full }: { label: string; value: string; full?: boolean }) {
  return (
    <div className={full ? "col-span-2 sm:col-span-3" : undefined}>
      <p style={{ color: "var(--text-quiet)" }}>{label}</p>
      <p className="mt-0.5 break-words" style={{ color: "var(--text)" }}>
        {value}
      </p>
    </div>
  );
}

export default function RunDetailPage() {
  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel message="Sign in to view run details" forceRedirectUrl="/bots" />
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
          <RunDetailContent />
        </RoleGuard>
      </SignedIn>
    </DashboardShell>
  );
}

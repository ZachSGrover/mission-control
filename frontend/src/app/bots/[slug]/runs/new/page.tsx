"use client";

export const dynamic = "force-dynamic";

import { useCallback, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import { getApiBaseUrl } from "@/lib/api-base";

import { SandboxBanner } from "../../_lib/SandboxBanner";
import {
  MAX_PREVIEW_CHARS,
  MOCK_PROFILES,
  previewOfMessage,
  RT_BOT_SLUG,
} from "../../_lib/rt-bot";

function NewRunContent() {
  const params = useParams();
  const slugParam = params?.slug;
  const slug = (Array.isArray(slugParam) ? slugParam[0] : slugParam) ?? "";
  const router = useRouter();
  const { fetchWithAuth } = useAuthFetch();

  const [profileId, setProfileId] = useState<string>(MOCK_PROFILES[0].id);
  const [message, setMessage] = useState("");
  const [targetCount, setTargetCount] = useState(10);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const profileName = useMemo(
    () => MOCK_PROFILES.find((p) => p.id === profileId)?.name ?? profileId,
    [profileId],
  );

  const preview = previewOfMessage(message);

  const submit = useCallback(async () => {
    setError(null);
    setSubmitting(true);
    try {
      const res = await fetchWithAuth(`${getApiBaseUrl()}/api/v1/bots/${slug}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          profile_id: profileId,
          profile_name: profileName,
          message,
          target_count: targetCount,
        }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as
          | { detail?: { error?: string; detail?: string } | string }
          | null;
        const detail = body?.detail;
        const code =
          typeof detail === "object" && detail
            ? detail.error ?? detail.detail ?? `HTTP ${res.status}`
            : detail ?? `HTTP ${res.status}`;
        throw new Error(String(code));
      }
      const created = (await res.json()) as { id: string };
      // Owner immediately starts the run after the draft is accepted.
      const start = await fetchWithAuth(
        `${getApiBaseUrl()}/api/v1/bots/${slug}/runs/${created.id}/start`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
        },
      );
      if (!start.ok) {
        const body = (await start.json().catch(() => null)) as
          | { detail?: { error?: string } | string }
          | null;
        const detail = body?.detail;
        const code =
          typeof detail === "object" && detail
            ? detail.error ?? `HTTP ${start.status}`
            : detail ?? `HTTP ${start.status}`;
        throw new Error(String(code));
      }
      router.push(`/bots/${slug}/runs/${created.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create run");
    } finally {
      setSubmitting(false);
      setConfirmOpen(false);
    }
  }, [fetchWithAuth, message, profileId, profileName, router, slug, targetCount]);

  return (
    <main className="flex-1 overflow-y-auto" style={{ background: "var(--bg)" }}>
      <div className="max-w-2xl mx-auto px-6 py-8 space-y-5">
        <Link
          href={`/bots/${slug}`}
          className="text-xs underline decoration-dotted"
          style={{ color: "var(--text-quiet)" }}
        >
          ← Bot detail
        </Link>
        <h1 className="text-xl font-semibold" style={{ color: "var(--text)" }}>
          New Sandbox Run
        </h1>
        <SandboxBanner />

        <div
          className="rounded-xl p-4 space-y-3"
          style={{
            background: "var(--surface-strong)",
            border: "1px solid var(--border)",
          }}
        >
          <label className="block text-xs">
            <span style={{ color: "var(--text-muted)" }}>Profile</span>
            <select
              value={profileId}
              onChange={(e) => setProfileId(e.target.value)}
              className="mt-1 w-full rounded-lg px-2 py-1.5 text-xs"
              style={{
                background: "var(--bg)",
                border: "1px solid var(--border)",
                color: "var(--text)",
              }}
            >
              {MOCK_PROFILES.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <span
              className="mt-1 block text-[11px]"
              style={{ color: "var(--text-quiet)" }}
            >
              MVP profile picker. AdsPower is not contacted.
            </span>
          </label>

          <label className="block text-xs">
            <span style={{ color: "var(--text-muted)" }}>Target count</span>
            <input
              type="number"
              min={1}
              max={10000}
              value={targetCount}
              onChange={(e) => setTargetCount(Math.max(1, Number(e.target.value) || 1))}
              className="mt-1 w-full rounded-lg px-2 py-1.5 text-xs"
              style={{
                background: "var(--bg)",
                border: "1px solid var(--border)",
                color: "var(--text)",
              }}
            />
          </label>

          <label className="block text-xs">
            <span style={{ color: "var(--text-muted)" }}>Message</span>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              rows={4}
              className="mt-1 w-full rounded-lg px-2 py-1.5 text-xs font-mono"
              style={{
                background: "var(--bg)",
                border: "1px solid var(--border)",
                color: "var(--text)",
              }}
              placeholder="Outreach message body. Only the first 80 chars are stored as a preview; the full body is discarded after submit."
            />
          </label>

          <div
            className="rounded-lg px-3 py-2 text-[11px] font-mono"
            style={{
              background: "rgba(168,85,247,0.06)",
              border: "1px dashed rgba(168,85,247,0.2)",
              color: "var(--text-muted)",
            }}
          >
            <p style={{ color: "#c084fc" }}>Preview ({preview.length} / {MAX_PREVIEW_CHARS})</p>
            <p className="mt-1" style={{ color: "var(--text)" }}>
              {preview || "(empty)"}
            </p>
          </div>

          {error && (
            <p className="text-xs" style={{ color: "#ef4444" }}>
              {error === "live_writes_disabled_in_MVP"
                ? "Blocked: live writes are disabled in MVP."
                : error}
            </p>
          )}
        </div>

        <div className="flex justify-end gap-2">
          <Link
            href={`/bots/${slug}`}
            className="rounded-lg px-3 py-1.5 text-xs"
            style={{
              background: "var(--surface-strong)",
              border: "1px solid var(--border)",
              color: "var(--text-muted)",
            }}
          >
            Cancel
          </Link>
          <button
            type="button"
            disabled={submitting || !message.trim()}
            onClick={() => setConfirmOpen(true)}
            className="rounded-lg px-3 py-1.5 text-xs font-medium disabled:opacity-50 flex items-center gap-1"
            style={{ background: "rgba(34,197,94,0.15)", color: "#22c55e" }}
          >
            {submitting ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
            Start Sandbox Run
          </button>
        </div>

        {confirmOpen && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center"
            style={{ background: "rgba(0,0,0,0.55)" }}
          >
            <div
              className="rounded-xl p-5 max-w-sm w-full mx-4 space-y-4"
              style={{
                background: "var(--surface-strong)",
                border: "1px solid var(--border)",
              }}
            >
              <h2 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
                Start sandbox run?
              </h2>
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                A sandbox dry-run will execute against {targetCount} mock contacts
                on profile {profileName}. <strong>No live DMs are sent.</strong>{" "}
                Only the 80-char message preview is stored.
              </p>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  className="rounded-lg px-3 py-1.5 text-xs"
                  onClick={() => setConfirmOpen(false)}
                  style={{
                    background: "var(--bg)",
                    border: "1px solid var(--border)",
                    color: "var(--text-muted)",
                  }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="rounded-lg px-3 py-1.5 text-xs font-medium"
                  onClick={() => void submit()}
                  style={{ background: "rgba(34,197,94,0.15)", color: "#22c55e" }}
                  disabled={submitting}
                >
                  {submitting ? "Running…" : "Confirm sandbox start"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}

export default function NewRunPage() {
  const params = useParams();
  const slug = Array.isArray(params?.slug) ? params.slug[0] : params?.slug;
  if (slug !== RT_BOT_SLUG) {
    // Future-proof: only the RT BOT exposes the run-creation surface
    // in this MVP.  Any other slug routes through to a denied state.
    return (
      <DashboardShell>
        <SignedIn>
          <DashboardSidebar />
          <main
            className="flex-1 flex items-center justify-center"
            style={{ background: "var(--bg)" }}
          >
            <p className="text-sm" style={{ color: "var(--text-quiet)" }}>
              Run creation is only available for the X DM Bot RTxRT in this MVP.
            </p>
          </main>
        </SignedIn>
      </DashboardShell>
    );
  }
  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel message="Sign in to create a run" forceRedirectUrl="/bots" />
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <RoleGuard
          require="owner"
          denied={
            <main
              className="flex-1 flex items-center justify-center"
              style={{ background: "var(--bg)" }}
            >
              <p className="text-sm" style={{ color: "var(--text-quiet)" }}>
                Owner access required.
              </p>
            </main>
          }
        >
          <NewRunContent />
        </RoleGuard>
      </SignedIn>
    </DashboardShell>
  );
}

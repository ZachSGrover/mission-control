"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Loader2, Lock, ShieldOff } from "lucide-react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import { getApiBaseUrl } from "@/lib/api-base";

import { SandboxBanner } from "../_lib/SandboxBanner";
import { type BotSettings, RT_BOT_SLUG } from "../_lib/rt-bot";

function SettingsContent() {
  const params = useParams();
  const slug = (Array.isArray(params?.slug) ? params.slug[0] : params?.slug) ?? "";
  const { fetchWithAuth } = useAuthFetch();
  const [settings, setSettings] = useState<BotSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [killing, setKilling] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchWithAuth(`${getApiBaseUrl()}/api/v1/bots/${slug}/settings`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setSettings((await res.json()) as BotSettings);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load settings.");
    } finally {
      setLoading(false);
    }
  }, [fetchWithAuth, slug]);

  useEffect(() => {
    if (slug) void refresh();
  }, [slug, refresh]);

  const onKill = useCallback(async () => {
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
  }, [fetchWithAuth, refresh, slug]);

  if (slug !== RT_BOT_SLUG) {
    return (
      <main
        className="flex-1 flex items-center justify-center"
        style={{ background: "var(--bg)" }}
      >
        <p className="text-sm" style={{ color: "var(--text-quiet)" }}>
          Settings are only available for the X DM Bot RTxRT in this MVP.
        </p>
      </main>
    );
  }

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
          Settings
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

        {loading || !settings ? (
          <p className="text-xs" style={{ color: "var(--text-quiet)" }}>
            Loading…
          </p>
        ) : (
          <>
            <section
              className="rounded-xl p-4 space-y-3 text-xs"
              style={{
                background: "var(--surface-strong)",
                border: "1px solid var(--border)",
              }}
            >
              <Row label="Name" value={settings.name} />
              <Row label="Slug" value={settings.slug} />
              <Row label="Version" value={settings.version ?? "—"} />
              <Row
                label="Sandbox mode"
                value={
                  <span className="flex items-center gap-1">
                    <Lock className="h-3 w-3" /> Locked ON
                  </span>
                }
              />
              <Row
                label="Live writes"
                value={
                  <span className="flex items-center gap-1" style={{ color: "#22c55e" }}>
                    <Lock className="h-3 w-3" /> Locked OFF in MVP
                  </span>
                }
              />
              <Row
                label="Kill switch"
                value={settings.kill_switch_active ? "ACTIVE" : "Inactive"}
              />
              <Row
                label="API key"
                value={settings.api_key_present ? "Present" : "Not configured"}
              />
              <p className="mt-3 text-[11px]" style={{ color: "var(--text-quiet)" }}>
                Sensitive values (API keys, cookies, passwords, tokens) are
                never returned by this endpoint — only presence flags.
              </p>
            </section>

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
              Activate kill switch
            </button>
          </>
        )}
      </div>
    </main>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <span style={{ color: "var(--text-quiet)" }}>{label}</span>
      <span style={{ color: "var(--text)" }}>{value}</span>
    </div>
  );
}

export default function SettingsPage() {
  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel message="Sign in to view settings" forceRedirectUrl="/bots" />
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
          <SettingsContent />
        </RoleGuard>
      </SignedIn>
    </DashboardShell>
  );
}

"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Bot as BotIcon,
  CheckCircle2,
  Loader2,
  Lock,
  Pause,
  Play,
  RefreshCw,
} from "lucide-react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { BotPermissionsEditor } from "@/components/bots/BotPermissionsEditor";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import { useRole } from "@/hooks/use-role";
import { getApiBaseUrl } from "@/lib/api-base";
import type { MCRole } from "@/lib/roles";

// ── Types ─────────────────────────────────────────────────────────────────────

interface BotEntry {
  slug: string;
  name: string;
  kind: string;
  description: string | null;
  enabled: boolean;
  safe_mode: boolean;
  status: string;
  last_status_detail: string | null;
  last_run_at: string | null;
  last_error_summary: string | null;
  permitted_roles: MCRole[];
  can_operate: boolean;
  read_only_external: boolean;
}

type FetchFn = (url: string, init?: RequestInit) => Promise<Response>;

// ── API helpers ───────────────────────────────────────────────────────────────

async function fetchBots(fetchFn: FetchFn): Promise<BotEntry[]> {
  const res = await fetchFn(`${getApiBaseUrl()}/api/v1/bots`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as BotEntry[];
}

async function startBot(slug: string, fetchFn: FetchFn): Promise<BotEntry> {
  const res = await fetchFn(`${getApiBaseUrl()}/api/v1/bots/${slug}/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  // Re-fetch detail so the row reflects post-start state.
  const detailRes = await fetchFn(`${getApiBaseUrl()}/api/v1/bots/${slug}`);
  if (!detailRes.ok) throw new Error(`HTTP ${detailRes.status}`);
  return (await detailRes.json()) as BotEntry;
}

async function stopBot(slug: string, fetchFn: FetchFn): Promise<BotEntry> {
  const res = await fetchFn(`${getApiBaseUrl()}/api/v1/bots/${slug}/stop`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  const detailRes = await fetchFn(`${getApiBaseUrl()}/api/v1/bots/${slug}`);
  if (!detailRes.ok) throw new Error(`HTTP ${detailRes.status}`);
  return (await detailRes.json()) as BotEntry;
}

async function setBotPermissions(
  slug: string,
  permittedRoles: MCRole[],
  fetchFn: FetchFn,
): Promise<BotEntry> {
  const res = await fetchFn(`${getApiBaseUrl()}/api/v1/bots/${slug}/permissions`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ permitted_roles: permittedRoles }),
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  return (await res.json()) as BotEntry;
}

// ── Visual helpers ────────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, { bg: string; fg: string }> = {
  idle: { bg: "rgba(107,114,128,0.15)", fg: "#9ca3af" },
  running: { bg: "rgba(34,197,94,0.15)", fg: "#22c55e" },
  disabled: { bg: "rgba(107,114,128,0.15)", fg: "#9ca3af" },
  error: { bg: "rgba(239,68,68,0.15)", fg: "#ef4444" },
  unknown: { bg: "rgba(107,114,128,0.15)", fg: "#9ca3af" },
};

function StatusPill({ status }: { status: string }) {
  const colors = STATUS_COLORS[status] ?? STATUS_COLORS.unknown;
  return (
    <span
      className="rounded-full px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide"
      style={{ background: colors.bg, color: colors.fg }}
    >
      {status}
    </span>
  );
}

function formatRelative(iso: string | null): string {
  if (!iso) return "never";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const now = Date.now();
  const seconds = Math.max(0, Math.floor((now - date.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86_400)}d ago`;
}

// ── Bot row ───────────────────────────────────────────────────────────────────

function BotRow({
  entry,
  fetchFn,
  onUpdate,
  viewerRole,
}: {
  entry: BotEntry;
  fetchFn: FetchFn;
  onUpdate: (next: BotEntry) => void;
  viewerRole: MCRole | null;
}) {
  const [busy, setBusy] = useState<"start" | "stop" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onSavePermissions = useCallback(
    async (slug: string, roles: MCRole[]): Promise<MCRole[]> => {
      const next = await setBotPermissions(slug, roles, fetchFn);
      onUpdate(next);
      return next.permitted_roles;
    },
    [fetchFn, onUpdate],
  );

  const blockedReason = useMemo(() => {
    if (entry.read_only_external) return "Managed externally (launchd / cloudflared)";
    if (!entry.can_operate) return "Your role is not permitted to operate this bot";
    return null;
  }, [entry.read_only_external, entry.can_operate]);

  const onStart = useCallback(async () => {
    setBusy("start");
    setError(null);
    try {
      const next = await startBot(entry.slug, fetchFn);
      onUpdate(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(null);
    }
  }, [entry.slug, fetchFn, onUpdate]);

  const onStop = useCallback(async () => {
    setBusy("stop");
    setError(null);
    try {
      const next = await stopBot(entry.slug, fetchFn);
      onUpdate(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(null);
    }
  }, [entry.slug, fetchFn, onUpdate]);

  return (
    <div
      className="rounded-xl px-4 py-3"
      style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}
    >
      <div className="flex items-center gap-3">
        <BotIcon className="h-5 w-5 shrink-0" style={{ color: "var(--text-muted)" }} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate text-sm font-medium" style={{ color: "var(--text)" }}>
              {entry.name}
            </p>
            <span className="text-[10px] font-mono uppercase" style={{ color: "var(--text-quiet)" }}>
              {entry.kind}
            </span>
            <StatusPill status={entry.status} />
            {entry.safe_mode && (
              <span
                className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
                style={{ background: "rgba(168,85,247,0.10)", color: "#c084fc" }}
                title="Safe-mode operation only"
              >
                safe-mode
              </span>
            )}
          </div>
          {entry.description && (
            <p className="mt-1 text-xs" style={{ color: "var(--text-muted)" }}>
              {entry.description}
            </p>
          )}
          <div className="mt-1 flex flex-wrap gap-3 text-[11px]" style={{ color: "var(--text-quiet)" }}>
            <span>last run: {formatRelative(entry.last_run_at)}</span>
            <span>permitted: {entry.permitted_roles.join(", ") || "owner"}</span>
            {entry.last_status_detail && <span>detail: {entry.last_status_detail}</span>}
          </div>
          {entry.last_error_summary && (
            <p className="mt-1 text-xs" style={{ color: "var(--danger, #ef4444)" }}>
              <AlertTriangle className="inline h-3 w-3 mr-1" />
              {entry.last_error_summary}
            </p>
          )}
          {error && (
            <p className="mt-1 text-xs" style={{ color: "var(--danger, #ef4444)" }}>
              {error}
            </p>
          )}
        </div>

        <div className="flex shrink-0 flex-col items-end gap-1">
          {blockedReason ? (
            <span
              className="flex items-center gap-1 rounded-lg px-2 py-1 text-[11px]"
              style={{ background: "var(--surface-muted)", color: "var(--text-quiet)" }}
              title={blockedReason}
            >
              <Lock className="h-3 w-3" />
              blocked
            </span>
          ) : (
            <div className="flex gap-1">
              <button
                type="button"
                disabled={busy !== null || entry.enabled}
                onClick={() => void onStart()}
                className="flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium transition-opacity disabled:opacity-40"
                style={{ background: "rgba(34,197,94,0.15)", color: "#22c55e" }}
                title="Start (mark enabled)"
              >
                {busy === "start" ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
                Start
              </button>
              <button
                type="button"
                disabled={busy !== null || !entry.enabled}
                onClick={() => void onStop()}
                className="flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium transition-opacity disabled:opacity-40"
                style={{ background: "rgba(239,68,68,0.15)", color: "#ef4444" }}
                title="Stop (mark disabled)"
              >
                {busy === "stop" ? <Loader2 className="h-3 w-3 animate-spin" /> : <Pause className="h-3 w-3" />}
                Stop
              </button>
            </div>
          )}
          {entry.enabled && (
            <span className="flex items-center gap-1 text-[10px]" style={{ color: "#22c55e" }}>
              <CheckCircle2 className="h-3 w-3" />
              enabled
            </span>
          )}
        </div>
      </div>
      <BotPermissionsEditor
        slug={entry.slug}
        permittedRoles={entry.permitted_roles}
        readOnlyExternal={entry.read_only_external}
        viewerRole={viewerRole}
        onSave={onSavePermissions}
      />
    </div>
  );
}

// ── Page content ──────────────────────────────────────────────────────────────

function BotsPageContent() {
  const [bots, setBots] = useState<BotEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const { fetchWithAuth } = useAuthFetch();
  const { role: viewerRole } = useRole();

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchBots(fetchWithAuth);
      setBots(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load bots.");
    } finally {
      setLoading(false);
    }
  }, [fetchWithAuth]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleUpdate = useCallback((next: BotEntry) => {
    setBots((prev) => prev.map((b) => (b.slug === next.slug ? next : b)));
  }, []);

  return (
    <main className="flex-1 overflow-y-auto" style={{ background: "var(--bg)" }}>
      <div className="max-w-3xl mx-auto px-6 py-8 space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold" style={{ color: "var(--text)" }}>
              Bots
            </h1>
            <p className="mt-1 text-sm" style={{ color: "var(--text-muted)" }}>
              Operator dashboard for Mission Control bots. Start/stop affects
              the bot&apos;s intent flag — actual orchestration runs in
              its existing safe-mode loop.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void refresh()}
            className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs"
            style={{ background: "var(--surface-strong)", border: "1px solid var(--border)", color: "var(--text-muted)" }}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
        </div>

        <div
          className="rounded-xl px-4 py-3 text-xs"
          style={{
            background: "rgba(168,85,247,0.08)",
            border: "1px solid rgba(168,85,247,0.2)",
            color: "var(--text-muted)",
          }}
        >
          External-managed bots (Hermes, Radar, etc.) appear here for
          visibility but cannot be started or stopped from this page —
          their lifecycle is owned by launchd.
        </div>

        {error && (
          <div
            className="rounded-xl px-4 py-3 text-sm"
            style={{ background: "rgba(239,68,68,0.1)", color: "#ef4444", border: "1px solid rgba(239,68,68,0.2)" }}
          >
            {error}
          </div>
        )}

        {loading ? (
          <p className="text-sm" style={{ color: "var(--text-quiet)" }}>
            Loading bots…
          </p>
        ) : bots.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--text-quiet)" }}>
            No bots registered yet.
          </p>
        ) : (
          <div className="space-y-3">
            {bots.map((b) => (
              <BotRow
                key={b.slug}
                entry={b}
                fetchFn={fetchWithAuth}
                onUpdate={handleUpdate}
                viewerRole={viewerRole}
              />
            ))}
          </div>
        )}
      </div>
    </main>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function BotsPage() {
  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel message="Sign in to access Mission Control bots" forceRedirectUrl="/bots" />
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <RoleGuard
          require="operator"
          denied={
            <main className="flex-1 flex items-center justify-center" style={{ background: "var(--bg)" }}>
              <p className="text-sm" style={{ color: "var(--text-quiet)" }}>
                Operator access required.
              </p>
            </main>
          }
        >
          <BotsPageContent />
        </RoleGuard>
      </SignedIn>
    </DashboardShell>
  );
}

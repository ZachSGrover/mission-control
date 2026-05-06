"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Eye, EyeOff, ExternalLink, Loader2, RefreshCw, Send, Shield, X, XCircle } from "lucide-react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { getApiBaseUrl } from "@/lib/api-base";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";

// ── Types ─────────────────────────────────────────────────────────────────────

type BotStatus = {
  connected: boolean;
  bot_username: string | null;
  detail: string;
};

type Integration = {
  name:        string;
  label:       string;
  description: string;
  placeholder: string;
  docs_url:    string;
  configured:  boolean;
  preview:     string | null;
  source:      string;
};

type FetchFn = typeof fetch;

// ── API helpers ───────────────────────────────────────────────────────────────

async function fetchIntegrations(fetchFn: FetchFn): Promise<Integration[]> {
  const res = await fetchFn(`${getApiBaseUrl()}/api/v1/integrations`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<Integration[]>;
}

async function saveCredential(name: string, key: string, fetchFn: FetchFn): Promise<Integration> {
  const res = await fetchFn(`${getApiBaseUrl()}/api/v1/integrations/${name}`, {
    method:  "PUT",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ key }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<Integration>;
}

async function clearCredential(name: string, fetchFn: FetchFn): Promise<void> {
  await fetchFn(`${getApiBaseUrl()}/api/v1/integrations/${name}`, { method: "DELETE" });
}

async function fetchTelegramStatus(fetchFn: FetchFn): Promise<{ has_token: boolean; bot_username: string | null; source: string }> {
  const res = await fetchFn(`${getApiBaseUrl()}/api/v1/telegram/config`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<{ has_token: boolean; bot_username: string | null; source: string }>;
}

async function fetchDiscordStatus(fetchFn: FetchFn): Promise<BotStatus> {
  const res = await fetchFn(`${getApiBaseUrl()}/api/v1/discord/status`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<BotStatus>;
}

// ── OF Intelligence QC Discord ────────────────────────────────────────────────

type OfQcCardState = "not_configured" | "configured" | "last_test_failed" | "connected";

type OfQcStatus = {
  configured:           boolean;
  preview:              string | null;
  source:               string;
  enabled:              boolean;
  last_success_at:      string | null;
  last_failure_at:      string | null;
  last_failure_reason:  string | null;
  last_failure_status:  number | null;
  card_state:           OfQcCardState;
};

type OfQcTestResult = {
  ok:         boolean;
  status:     number | null;
  attempts:   number;
  reason:     string;
  elapsed_ms: number;
  card_state: OfQcCardState;
};

const OF_QC_BASE = "/api/v1/of-qc-discord";

type AuthFetchFn = (url: string, options?: RequestInit) => Promise<Response>;

async function fetchOfQcStatus(fetchFn: AuthFetchFn): Promise<OfQcStatus> {
  const res = await fetchFn(`${getApiBaseUrl()}${OF_QC_BASE}/status`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<OfQcStatus>;
}

async function saveOfQcWebhook(key: string, fetchFn: AuthFetchFn): Promise<OfQcStatus> {
  const res = await fetchFn(`${getApiBaseUrl()}${OF_QC_BASE}/webhook`, {
    method:  "PUT",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ key }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<OfQcStatus>;
}

async function clearOfQcWebhook(fetchFn: AuthFetchFn): Promise<OfQcStatus> {
  const res = await fetchFn(`${getApiBaseUrl()}${OF_QC_BASE}/webhook`, { method: "DELETE" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<OfQcStatus>;
}

async function setOfQcEnabled(enabled: boolean, fetchFn: AuthFetchFn): Promise<OfQcStatus> {
  const res = await fetchFn(`${getApiBaseUrl()}${OF_QC_BASE}/enabled`, {
    method:  "PUT",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ enabled }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<OfQcStatus>;
}

async function sendOfQcTestAlert(fetchFn: AuthFetchFn): Promise<OfQcTestResult> {
  const res = await fetchFn(`${getApiBaseUrl()}${OF_QC_BASE}/test`, { method: "POST" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<OfQcTestResult>;
}

function formatTimestamp(value: string | null): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

// ── Bot status card (read-only — Telegram / Discord) ─────────────────────────

function BotStatusCard({
  label,
  icon,
  connected,
  username,
  detail,
  loading,
  onRefresh,
}: {
  label: string;
  icon: React.ReactNode;
  connected: boolean | null;
  username: string | null;
  detail: string;
  loading: boolean;
  onRefresh: () => void;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-slate-100 text-slate-600">
            {icon}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-semibold text-slate-900">{label}</h3>
              {connected === null || loading ? (
                <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-slate-100 text-slate-400">
                  Checking…
                </span>
              ) : connected ? (
                <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
                  Connected
                </span>
              ) : (
                <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-red-50 text-red-600 border border-red-200">
                  Disconnected
                </span>
              )}
            </div>
            {username && (
              <p className="text-sm text-slate-500 mt-0.5">@{username}</p>
            )}
            {!username && detail && (
              <p className="text-xs text-slate-400 mt-0.5">{detail}</p>
            )}
          </div>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={loading}
          className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600 transition-colors disabled:opacity-40"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>
      <p className="mt-3 text-xs text-slate-400">
        Managed via OpenClaw. Configure tokens in{" "}
        <code className="text-slate-500">~/.openclaw/openclaw.json</code>.
      </p>
    </div>
  );
}

// ── Integration card ──────────────────────────────────────────────────────────

function IntegrationCard({
  integration,
  fetchFn,
  onUpdate,
}: {
  integration: Integration;
  fetchFn: FetchFn;
  onUpdate: (updated: Integration) => void;
}) {
  const [inputValue, setInputValue]   = useState("");
  const [showValue, setShowValue]     = useState(false);
  const [saving, setSaving]           = useState(false);
  const [clearing, setClearing]       = useState(false);
  const [error, setError]             = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  const handleSave = useCallback(async () => {
    if (!inputValue.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await saveCredential(integration.name, inputValue.trim(), fetchFn);
      onUpdate(updated);
      setInputValue("");
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }, [inputValue, integration.name, fetchFn, onUpdate]);

  const handleClear = useCallback(async () => {
    setClearing(true);
    setError(null);
    try {
      await clearCredential(integration.name, fetchFn);
      onUpdate({ ...integration, configured: false, preview: null, source: "none" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove");
    } finally {
      setClearing(false);
    }
  }, [integration, fetchFn, onUpdate]);

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-slate-900">{integration.label}</h3>
            <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
              integration.configured
                ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                : "bg-slate-100 text-slate-500"
            }`}>
              {integration.configured ? "Connected" : "Not configured"}
            </span>
          </div>
          <p className="text-sm text-slate-500">{integration.description}</p>
        </div>
        <a
          href={integration.docs_url}
          target="_blank"
          rel="noreferrer"
          className="shrink-0 flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600 transition-colors"
        >
          Docs <ExternalLink className="h-3 w-3" />
        </a>
      </div>

      {integration.configured && integration.preview && (
        <div className="flex items-center justify-between gap-3 rounded-lg bg-slate-50 px-4 py-2.5 border border-slate-200">
          <span className="font-mono text-sm text-slate-600">{integration.preview}</span>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400">{integration.source}</span>
            <button
              type="button"
              onClick={() => void handleClear()}
              disabled={clearing}
              className="flex items-center gap-1 text-xs text-red-500 hover:text-red-700 transition-colors disabled:opacity-50"
            >
              <X className="h-3.5 w-3.5" />
              {clearing ? "Removing…" : "Remove"}
            </button>
          </div>
        </div>
      )}

      <div className="flex gap-2">
        <div className="relative flex-1">
          <input
            type={showValue ? "text" : "password"}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void handleSave(); }}
            placeholder={integration.configured ? "Enter new key to rotate…" : integration.placeholder}
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 pr-9 text-sm font-mono placeholder:font-sans placeholder:text-slate-400 focus:border-slate-400 focus:outline-none"
          />
          <button
            type="button"
            onClick={() => setShowValue((v) => !v)}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
            tabIndex={-1}
          >
            {showValue ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
          </button>
        </div>
        <button
          type="button"
          onClick={() => void handleSave()}
          disabled={saving || !inputValue.trim()}
          className="shrink-0 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-80 disabled:opacity-40"
        >
          {saving ? "Saving…" : saveSuccess ? "Saved!" : "Save"}
        </button>
      </div>

      {error && <p className="text-sm text-red-500">{error}</p>}
    </div>
  );
}

// ── OF Intelligence QC Discord card ──────────────────────────────────────────

function OfQcStatePill({ state }: { state: OfQcCardState }) {
  const map: Record<OfQcCardState, { label: string; cls: string; icon: React.ReactNode }> = {
    not_configured:   { label: "Not configured",  cls: "bg-slate-100 text-slate-500",                                    icon: null },
    configured:       { label: "Configured",      cls: "bg-amber-50 text-amber-700 border border-amber-200",             icon: null },
    last_test_failed: { label: "Last test failed",cls: "bg-red-50 text-red-700 border border-red-200",                   icon: <XCircle className="h-3 w-3" /> },
    connected:        { label: "Connected",       cls: "bg-emerald-50 text-emerald-700 border border-emerald-200",       icon: <CheckCircle2 className="h-3 w-3" /> },
  };
  const item = map[state];
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${item.cls}`}>
      {item.icon}
      {item.label}
    </span>
  );
}

function OfQcDiscordCard({ fetchFn }: { fetchFn: AuthFetchFn }) {
  const [status, setStatus]           = useState<OfQcStatus | null>(null);
  const [loading, setLoading]         = useState(true);
  const [inputValue, setInputValue]   = useState("");
  const [showValue, setShowValue]     = useState(false);
  const [saving, setSaving]           = useState(false);
  const [testing, setTesting]         = useState(false);
  const [removing, setRemoving]       = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [error, setError]             = useState<string | null>(null);
  const [testToast, setTestToast]     = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    fetchOfQcStatus(fetchFn)
      .then(setStatus)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, [fetchFn]);

  useEffect(() => { load(); }, [load]);

  const handleSave = useCallback(async () => {
    if (!inputValue.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await saveOfQcWebhook(inputValue.trim(), fetchFn);
      setStatus(updated);
      setInputValue("");
      setShowValue(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }, [inputValue, fetchFn]);

  const handleToggle = useCallback(async (next: boolean) => {
    if (!status?.configured) return;
    try {
      const updated = await setOfQcEnabled(next, fetchFn);
      setStatus(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update toggle");
    }
  }, [status, fetchFn]);

  const handleTest = useCallback(async () => {
    if (!status?.configured) return;
    setTesting(true);
    setError(null);
    setTestToast(null);
    try {
      const result = await sendOfQcTestAlert(fetchFn);
      setTestToast({
        ok:   result.ok,
        text: result.ok
          ? `✅ Sent (HTTP ${result.status ?? "?"}) in ${result.elapsed_ms} ms`
          : `❌ ${result.reason}${result.status ? ` (HTTP ${result.status})` : ""}`,
      });
      // Refresh status to pick up the new last_success_at / last_failure_at.
      const refreshed = await fetchOfQcStatus(fetchFn);
      setStatus(refreshed);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send test");
    } finally {
      setTesting(false);
    }
  }, [status, fetchFn]);

  const handleRemove = useCallback(async () => {
    setRemoving(true);
    setError(null);
    try {
      const updated = await clearOfQcWebhook(fetchFn);
      setStatus(updated);
      setConfirmRemove(false);
      setTestToast(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove");
    } finally {
      setRemoving(false);
    }
  }, [fetchFn]);

  const cardState: OfQcCardState = status?.card_state ?? "not_configured";
  const configured  = !!status?.configured;
  const enabled     = !!status?.enabled;
  const enableLocked = !configured;

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <Shield className="h-4 w-4 text-slate-500 shrink-0" />
            <h3 className="font-semibold text-slate-900">OnlyFans Intelligence QC Discord</h3>
            <OfQcStatePill state={cardState} />
          </div>
          <p className="text-sm text-slate-500">
            Send QC alerts (account access, sync health, refund risk, chatter quality) to a private Discord channel.
            Webhook stored encrypted; never displayed after saving.
          </p>
        </div>
      </div>

      {/* Configured state — show masked preview + remove */}
      {configured && status?.preview && (
        <div className="flex items-center justify-between gap-3 rounded-lg bg-slate-50 px-4 py-2.5 border border-slate-200">
          <span className="font-mono text-sm text-slate-600 truncate">{status.preview}</span>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400">{status.source}</span>
            {!confirmRemove ? (
              <button
                type="button"
                onClick={() => setConfirmRemove(true)}
                className="flex items-center gap-1 text-xs text-red-500 hover:text-red-700 transition-colors"
              >
                <X className="h-3.5 w-3.5" />
                Remove
              </button>
            ) : (
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-500">Confirm remove?</span>
                <button
                  type="button"
                  onClick={() => void handleRemove()}
                  disabled={removing}
                  className="text-xs text-red-600 font-medium hover:text-red-800 transition-colors disabled:opacity-50"
                >
                  {removing ? "Removing…" : "Yes, remove"}
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmRemove(false)}
                  disabled={removing}
                  className="text-xs text-slate-500 hover:text-slate-700 transition-colors"
                >
                  Cancel
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Webhook URL input */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <input
            type={showValue ? "text" : "password"}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void handleSave(); }}
            placeholder={configured ? "Paste new webhook to rotate…" : "https://discord.com/api/webhooks/…/…"}
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 pr-9 text-sm font-mono placeholder:font-sans placeholder:text-slate-400 focus:border-slate-400 focus:outline-none"
            autoComplete="off"
            spellCheck={false}
          />
          <button
            type="button"
            onClick={() => setShowValue((v) => !v)}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
            tabIndex={-1}
            aria-label={showValue ? "Hide" : "Show"}
          >
            {showValue ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
          </button>
        </div>
        <button
          type="button"
          onClick={() => void handleSave()}
          disabled={saving || !inputValue.trim()}
          className="shrink-0 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-80 disabled:opacity-40"
        >
          {saving ? "Saving…" : "Save"}
        </button>
      </div>

      {/* Toggle + Test */}
      <div className="flex items-center justify-between gap-3 pt-2">
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => void handleToggle(e.target.checked)}
            disabled={enableLocked}
            className="h-4 w-4 rounded border-slate-300 disabled:opacity-50"
          />
          <span className={`text-sm ${enableLocked ? "text-slate-400" : "text-slate-700"}`}>
            Send real QC alerts to Discord
          </span>
          {enableLocked && <span className="text-xs text-slate-400">(save a webhook first)</span>}
        </label>
        <button
          type="button"
          onClick={() => void handleTest()}
          disabled={testing || !configured}
          className="shrink-0 inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
          {testing ? "Sending…" : "Send test alert"}
        </button>
      </div>

      {/* Test toast — clears on next test or remove */}
      {testToast && (
        <div className={`text-xs px-3 py-2 rounded-lg border ${
          testToast.ok ? "bg-emerald-50 text-emerald-700 border-emerald-200" : "bg-red-50 text-red-700 border-red-200"
        }`}>
          {testToast.text}
        </div>
      )}

      {/* History block */}
      {configured && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs text-slate-500 pt-2 border-t border-slate-100">
          <div>
            <span className="text-slate-400 uppercase tracking-wide text-[10px]">Last successful test</span>
            <div className="text-slate-700 mt-0.5">{formatTimestamp(status?.last_success_at ?? null)}</div>
          </div>
          <div>
            <span className="text-slate-400 uppercase tracking-wide text-[10px]">Last failure</span>
            <div className="text-slate-700 mt-0.5">
              {status?.last_failure_at
                ? `${status.last_failure_reason ?? "—"}${status.last_failure_status ? ` (HTTP ${status.last_failure_status})` : ""} · ${formatTimestamp(status.last_failure_at)}`
                : "—"}
            </div>
          </div>
        </div>
      )}

      {error   && <p className="text-sm text-red-500">{error}</p>}
      {loading && <p className="text-xs text-slate-400 inline-flex items-center gap-1"><Loader2 className="h-3 w-3 animate-spin" /> Loading…</p>}
    </div>
  );
}

// ── Page body ─────────────────────────────────────────────────────────────────

function IntegrationsBody() {
  const { fetchWithAuth } = useAuthFetch();
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [loading, setLoading]           = useState(true);
  const [error, setError]               = useState<string | null>(null);

  const [tgStatus, setTgStatus]       = useState<{ connected: boolean; username: string | null } | null>(null);
  const [tgLoading, setTgLoading]     = useState(true);
  const [discordStatus, setDiscordStatus] = useState<BotStatus | null>(null);
  const [discordLoading, setDiscordLoading] = useState(true);

  const loadBotStatuses = useCallback(() => {
    setTgLoading(true);
    fetchTelegramStatus(fetchWithAuth)
      .then((s) => setTgStatus({ connected: s.has_token, username: s.bot_username }))
      .catch(() => setTgStatus({ connected: false, username: null }))
      .finally(() => setTgLoading(false));

    setDiscordLoading(true);
    fetchDiscordStatus(fetchWithAuth)
      .then(setDiscordStatus)
      .catch(() => setDiscordStatus({ connected: false, bot_username: null, detail: "error" }))
      .finally(() => setDiscordLoading(false));
  }, [fetchWithAuth]);

  useEffect(() => {
    // Initial fetch — flips loading state then resolves into setIntegrations.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    fetchIntegrations(fetchWithAuth)
      .then(setIntegrations)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"))
      .finally(() => setLoading(false));

    loadBotStatuses();
  }, [fetchWithAuth, loadBotStatuses]);

  const handleUpdate = useCallback((updated: Integration) => {
    setIntegrations((prev) => prev.map((i) => (i.name === updated.name ? updated : i)));
  }, []);

  return (
    <div className="max-w-2xl mx-auto px-6 py-8 space-y-8">
      <div className="space-y-1">
        <h1 className="text-xl font-semibold text-slate-900">Integrations</h1>
        <p className="text-sm text-slate-500">
          Connect external automation tools. Credentials are encrypted at rest.
        </p>
      </div>

      {/* ── Messaging bots (read-only status) ── */}
      <div className="space-y-3">
        <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wide">Messaging</h2>
        <BotStatusCard
          label="Telegram"
          icon={<span className="text-base leading-none">✈️</span>}
          connected={tgStatus?.connected ?? null}
          username={tgStatus?.username ?? null}
          detail=""
          loading={tgLoading}
          onRefresh={loadBotStatuses}
        />
        <BotStatusCard
          label="Discord"
          icon={<span className="text-base leading-none">🎮</span>}
          connected={discordStatus?.connected ?? null}
          username={discordStatus?.bot_username ?? null}
          detail={discordStatus?.detail ?? ""}
          loading={discordLoading}
          onRefresh={loadBotStatuses}
        />
      </div>

      {/* ── OnlyFans Intelligence ── */}
      <div className="space-y-3">
        <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wide">OnlyFans Intelligence</h2>
        <OfQcDiscordCard fetchFn={fetchWithAuth} />
      </div>

      {/* ── API credential integrations ── */}
      <div className="space-y-3">
        <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wide">Automation Tools</h2>
        {loading && <p className="text-sm text-slate-400">Loading…</p>}
        {error && <p className="text-sm text-red-500">{error}</p>}
        {!loading && !error && integrations.map((integration) => (
          <IntegrationCard
            key={integration.name}
            integration={integration}
            fetchFn={fetchWithAuth}
            onUpdate={handleUpdate}
          />
        ))}
      </div>

      <div className="rounded-xl border border-slate-200 bg-slate-50 p-5 space-y-3">
        <h2 className="text-sm font-semibold text-slate-700">How These Work</h2>
        <div className="space-y-2 text-xs text-slate-500">
          <p>
            <strong className="text-slate-600">AdsPower</strong> — Local API at{" "}
            <code className="text-slate-700">http://local.adspower.net:50325</code> (requires local install).
            Use from Agents to request browser profile CDP endpoints for Playwright/Puppeteer automation.
          </p>
          <p>
            <strong className="text-slate-600">PhantomBuster</strong> — Cloud API at{" "}
            <code className="text-slate-700">https://api.phantombuster.com/api/v2</code> (no local install needed).
            Trigger phantoms from Workflow nodes for LinkedIn scraping, lead gen, and social automation.
          </p>
        </div>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function IntegrationsPage() {
  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel message="Sign in to manage integrations" forceRedirectUrl="/settings/integrations" />
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <main className="flex-1 overflow-y-auto bg-slate-50">
          <RoleGuard
            require="owner"
            denied={
              <div className="flex items-center justify-center h-full">
                <p className="text-sm text-slate-500">Only organization owners can manage integrations.</p>
              </div>
            }
          >
            <IntegrationsBody />
          </RoleGuard>
        </main>
      </SignedIn>
    </DashboardShell>
  );
}

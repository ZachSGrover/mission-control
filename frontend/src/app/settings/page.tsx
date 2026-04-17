"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";
import { Eye, EyeOff, X } from "lucide-react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { getApiBaseUrl } from "@/lib/api-base";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import { logRemoteCommand, logSystemAction, writeAutoJournal } from "@/lib/action-logger";

// ── Types ─────────────────────────────────────────────────────────────────────

type Provider = "openai" | "gemini" | "anthropic";
type GitHubField = "github_username" | "github_pat" | "github_repo";
type FieldStatus = { configured: boolean; preview: string | null; source?: string };
type AllKeyStatuses = Record<Provider, FieldStatus>;
type GitHubStatuses = Record<GitHubField, FieldStatus>;
type FetchFn = (url: string, init?: RequestInit) => Promise<Response>;

const PROVIDERS: { id: Provider; label: string; hint: string; placeholder: string }[] = [
  { id: "openai",    label: "OpenAI",         hint: "Used by ChatGPT tab",                          placeholder: "sk-proj-..." },
  { id: "gemini",    label: "Gemini",          hint: "Used by Gemini tab",                           placeholder: "AIza..." },
  { id: "anthropic", label: "Claude (direct)", hint: "Anthropic API key — for direct Claude access", placeholder: "sk-ant-..." },
];

const GITHUB_FIELDS: { id: GitHubField; label: string; hint: string; placeholder: string; secret: boolean }[] = [
  { id: "github_username", label: "GitHub Username",       hint: "Your GitHub username",        placeholder: "ZachSGrover",                    secret: false },
  { id: "github_pat",      label: "Personal Access Token", hint: "repo scope required",         placeholder: "ghp_...",                        secret: true  },
  { id: "github_repo",     label: "Repository",            hint: "owner/repo format",           placeholder: "ZachSGrover/mission-control",    secret: false },
];

// ── API helpers (accept fetchFn so auth mode is transparent) ──────────────────

async function fetchKeyStatuses(fetchFn: FetchFn): Promise<AllKeyStatuses> {
  const res = await fetchFn(`${getApiBaseUrl()}/api/v1/settings/api-keys`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<AllKeyStatuses>;
}

async function saveKey(provider: Provider, key: string, fetchFn: FetchFn): Promise<FieldStatus> {
  const res = await fetchFn(`${getApiBaseUrl()}/api/v1/settings/api-keys/${provider}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<FieldStatus>;
}

async function clearKey(provider: Provider, fetchFn: FetchFn): Promise<void> {
  await fetchFn(`${getApiBaseUrl()}/api/v1/settings/api-keys/${provider}`, { method: "DELETE" });
}

async function fetchGitHubStatuses(fetchFn: FetchFn): Promise<GitHubStatuses> {
  const res = await fetchFn(`${getApiBaseUrl()}/api/v1/settings/github`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<GitHubStatuses>;
}

async function saveGitHubField(field: GitHubField, value: string, fetchFn: FetchFn): Promise<FieldStatus> {
  const res = await fetchFn(`${getApiBaseUrl()}/api/v1/settings/github/${field}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<FieldStatus>;
}

async function clearGitHubField(field: GitHubField, fetchFn: FetchFn): Promise<void> {
  await fetchFn(`${getApiBaseUrl()}/api/v1/settings/github/${field}`, { method: "DELETE" });
}

// ── Telegram types and API helpers ────────────────────────────────────────────

type TelegramConfig = {
  has_token: boolean;
  bot_username: string | null;
  source: string;
};

async function fetchTelegramConfig(fetchFn: FetchFn): Promise<TelegramConfig> {
  const res = await fetchFn(`${getApiBaseUrl()}/api/v1/telegram/config`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<TelegramConfig>;
}

async function saveTelegramToken(token: string, fetchFn: FetchFn): Promise<TelegramConfig> {
  const res = await fetchFn(`${getApiBaseUrl()}/api/v1/telegram/config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<TelegramConfig>;
}

async function deleteTelegramToken(fetchFn: FetchFn): Promise<void> {
  const res = await fetchFn(`${getApiBaseUrl()}/api/v1/telegram/config`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) throw new Error(`HTTP ${res.status}`);
}

async function sendTelegramTest(chatId: string, fetchFn: FetchFn): Promise<void> {
  const res = await fetchFn(`${getApiBaseUrl()}/api/v1/telegram/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chatId }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
}

// ── Shared field row ──────────────────────────────────────────────────────────

function FieldRow({
  label,
  hint,
  placeholder,
  secret,
  status,
  onSave,
  onClear,
}: {
  label: string;
  hint: string;
  placeholder: string;
  secret: boolean;
  status: FieldStatus | undefined;
  onSave: (value: string) => Promise<FieldStatus>;
  onClear: () => Promise<void>;
}) {
  const [value, setValue] = useState("");
  const [shown, setShown] = useState(false);
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState<{ ok: boolean; msg: string } | null>(null);

  const fb = useCallback((ok: boolean, msg: string) => {
    setFeedback({ ok, msg });
    setTimeout(() => setFeedback(null), 3000);
  }, []);

  const handleSave = async () => {
    const trimmed = value.trim();
    if (!trimmed) { fb(false, "Enter a value first."); return; }
    setSaving(true);
    try {
      await onSave(trimmed);
      setValue("");
      fb(true, "Saved.");
      logSystemAction("env_var", `${label} saved`, `Settings → ${label}`);
      writeAutoJournal();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to save.";
      fb(false, msg);
      logSystemAction("error", `Failed to save ${label}`, msg);
    } finally {
      setSaving(false);
    }
  };

  const handleClear = async () => {
    setSaving(true);
    try {
      await onClear();
      setValue("");
      fb(true, "Removed.");
      logSystemAction("env_var", `${label} cleared`, `Settings → ${label}`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to remove.";
      fb(false, msg);
      logSystemAction("error", `Failed to clear ${label}`, msg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="rounded-xl p-4 space-y-3"
      style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium" style={{ color: "var(--text)" }}>{label}</p>
          <p className="text-xs mt-0.5" style={{ color: "var(--text-quiet)" }}>{hint}</p>
        </div>
        {status ? (
          status.configured ? (
            <span className="flex items-center gap-1.5 text-xs font-medium" style={{ color: "#22c55e" }}>
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              Configured
              {status.source && status.source !== "none" && (
                <span
                  className="rounded px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wide"
                  style={{
                    background: status.source === "db"
                      ? "rgba(99,102,241,0.15)"
                      : "rgba(234,179,8,0.15)",
                    color: status.source === "db" ? "#818cf8" : "#ca8a04",
                  }}
                >
                  {status.source === "db" ? "DB" : "ENV"}
                </span>
              )}
              {status.preview && (
                <span className="font-mono ml-1" style={{ color: "var(--text-quiet)" }}>
                  {status.preview}
                </span>
              )}
            </span>
          ) : status.source === "db" ? (
            // Key is in DB but decryption failed (auth credential may have rotated)
            <span className="flex items-center gap-1.5 text-xs font-medium" style={{ color: "#f59e0b" }}>
              <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
              Re-save required
              <span
                className="rounded px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wide"
                style={{ background: "rgba(234,179,8,0.15)", color: "#ca8a04" }}
                title="Key is stored but cannot be decrypted — the server's auth credential may have changed. Re-save the key to fix."
              >
                DB ⚠
              </span>
            </span>
          ) : (
            <span className="flex items-center gap-1.5 text-xs" style={{ color: "var(--text-quiet)" }}>
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: "var(--border-strong)" }} />
              Not set
            </span>
          )
        ) : (
          <span className="text-xs" style={{ color: "var(--text-quiet)" }}>Loading…</span>
        )}
      </div>

      {/* Input */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <input
            type={secret && !shown ? "password" : "text"}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void handleSave(); }}
            placeholder={
              status?.configured && status.preview
                ? `Current: ${status.preview}`
                : placeholder
            }
            disabled={saving}
            className="w-full rounded-lg pr-9 pl-3 py-2 text-sm font-mono focus:outline-none disabled:opacity-50"
            style={{
              background: "var(--surface-muted)",
              border: "1px solid var(--border-strong)",
              color: "var(--text)",
            }}
          />
          {secret && (
            <button
              type="button"
              tabIndex={-1}
              onClick={() => setShown((s) => !s)}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 transition-opacity hover:opacity-70"
              style={{ color: "var(--text-quiet)" }}
            >
              {shown ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            </button>
          )}
        </div>

        <button
          type="button"
          onClick={() => void handleSave()}
          disabled={saving || !value.trim()}
          className="rounded-lg px-4 py-2 text-sm font-medium text-white transition-opacity disabled:opacity-40"
          style={{ background: "var(--accent)" }}
        >
          {saving ? "…" : "Save"}
        </button>

        {status?.configured && (
          <button
            type="button"
            onClick={() => void handleClear()}
            disabled={saving}
            className="rounded-lg p-2 transition-colors disabled:opacity-40"
            style={{
              background: "var(--surface-muted)",
              border: "1px solid var(--border-strong)",
              color: "var(--text-quiet)",
            }}
            title="Remove"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {feedback && (
        <p className="text-xs" style={{ color: feedback.ok ? "#22c55e" : "var(--danger)" }}>
          {feedback.msg}
        </p>
      )}
    </div>
  );
}

// ── Telegram Remote Access section ───────────────────────────────────────────

function TelegramSection({ fetchFn }: { fetchFn: FetchFn }) {
  const [config, setConfig] = useState<TelegramConfig | null>(null);
  const [tokenInput, setTokenInput] = useState("");
  const [tokenShown, setTokenShown] = useState(false);
  const [chatIdInput, setChatIdInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [feedback, setFeedback] = useState<{ ok: boolean; msg: string } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const fb = useCallback((ok: boolean, msg: string) => {
    setFeedback({ ok, msg });
    setTimeout(() => setFeedback(null), 4000);
  }, []);

  useEffect(() => {
    fetchTelegramConfig(fetchFn)
      .then(setConfig)
      .catch((err) => setLoadError(err instanceof Error ? err.message : "Failed to load Telegram config."));
  }, [fetchFn]);

  const webhookUrl = typeof window !== "undefined"
    ? `${getApiBaseUrl()}/api/v1/telegram/webhook`
    : `${process.env.NEXT_PUBLIC_API_URL ?? "https://your-backend.onrender.com"}/api/v1/telegram/webhook`;

  const handleSaveToken = async () => {
    const trimmed = tokenInput.trim();
    if (!trimmed) { fb(false, "Enter a bot token first."); return; }
    setSaving(true);
    try {
      const updated = await saveTelegramToken(trimmed, fetchFn);
      setConfig(updated);
      setTokenInput("");
      fb(true, updated.bot_username ? `Connected as @${updated.bot_username}` : "Token saved.");
      logSystemAction("integration", "Telegram bot token saved", updated.bot_username ? `@${updated.bot_username}` : undefined);
      writeAutoJournal();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to save token.";
      fb(false, msg);
      logSystemAction("error", "Failed to save Telegram token", msg);
    } finally {
      setSaving(false);
    }
  };

  const handleRemoveToken = async () => {
    setSaving(true);
    try {
      await deleteTelegramToken(fetchFn);
      setConfig({ has_token: false, bot_username: null, source: "none" });
      fb(true, "Token removed.");
      logSystemAction("integration", "Telegram bot token removed", "Settings → Remote Access");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to remove token.";
      fb(false, msg);
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    const chatId = chatIdInput.trim();
    if (!chatId) { fb(false, "Enter a chat ID to send the test message to."); return; }
    setTesting(true);
    try {
      await sendTelegramTest(chatId, fetchFn);
      fb(true, "Test message sent! Check your Telegram.");
      logRemoteCommand("telegram", "/test", "ok");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to send test message.";
      fb(false, msg);
      logRemoteCommand("telegram", "/test", "error");
    } finally {
      setTesting(false);
    }
  };

  return (
    <section className="space-y-4">
      <div className="flex items-center gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>
          Remote Access
        </h2>
        <span
          className="rounded-full px-2 py-0.5 text-[10px] font-medium"
          style={{ background: "rgba(34,197,94,0.12)", color: "#22c55e" }}
        >
          Telegram Bot
        </span>
      </div>

      <p className="text-xs" style={{ color: "var(--text-quiet)" }}>
        Control Mission Control remotely via a Telegram bot. Get your token from{" "}
        <span className="font-mono" style={{ color: "var(--text)" }}>@BotFather</span> on Telegram.
      </p>

      {loadError && (
        <div
          className="rounded-xl px-4 py-3 text-sm"
          style={{ background: "rgba(239,68,68,0.08)", color: "#ef4444", border: "1px solid rgba(239,68,68,0.2)" }}
        >
          {loadError}
        </div>
      )}

      {/* Status */}
      <div
        className="rounded-xl p-4 space-y-3"
        style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}
      >
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium" style={{ color: "var(--text)" }}>Bot Token</p>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-quiet)" }}>
              Obtained from @BotFather — stored encrypted in the database
            </p>
          </div>
          {config ? (
            config.has_token ? (
              <span className="flex items-center gap-1.5 text-xs font-medium" style={{ color: "#22c55e" }}>
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                {config.bot_username ? `@${config.bot_username}` : "Connected"}
                {config.source && config.source !== "none" && (
                  <span
                    className="rounded px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wide"
                    style={{
                      background: config.source === "db" ? "rgba(99,102,241,0.15)" : "rgba(234,179,8,0.15)",
                      color: config.source === "db" ? "#818cf8" : "#ca8a04",
                    }}
                  >
                    {config.source === "db" ? "DB" : "ENV"}
                  </span>
                )}
              </span>
            ) : (
              <span className="flex items-center gap-1.5 text-xs" style={{ color: "var(--text-quiet)" }}>
                <span className="h-1.5 w-1.5 rounded-full" style={{ background: "var(--border-strong)" }} />
                Not configured
              </span>
            )
          ) : (
            <span className="text-xs" style={{ color: "var(--text-quiet)" }}>Loading…</span>
          )}
        </div>

        {/* Token input */}
        <div className="flex gap-2">
          <div className="relative flex-1">
            <input
              type={tokenShown ? "text" : "password"}
              value={tokenInput}
              onChange={(e) => setTokenInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") void handleSaveToken(); }}
              placeholder={config?.has_token ? "Replace existing token…" : "123456:ABC-DEF…"}
              disabled={saving}
              className="w-full rounded-lg pr-9 pl-3 py-2 text-sm font-mono focus:outline-none disabled:opacity-50"
              style={{
                background: "var(--surface-muted)",
                border: "1px solid var(--border-strong)",
                color: "var(--text)",
              }}
            />
            <button
              type="button"
              tabIndex={-1}
              onClick={() => setTokenShown((s) => !s)}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 transition-opacity hover:opacity-70"
              style={{ color: "var(--text-quiet)" }}
            >
              {tokenShown ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            </button>
          </div>
          <button
            type="button"
            onClick={() => void handleSaveToken()}
            disabled={saving || !tokenInput.trim()}
            className="rounded-lg px-4 py-2 text-sm font-medium text-white transition-opacity disabled:opacity-40"
            style={{ background: "var(--accent)" }}
          >
            {saving ? "…" : "Save"}
          </button>
          {config?.has_token && (
            <button
              type="button"
              onClick={() => void handleRemoveToken()}
              disabled={saving}
              className="rounded-lg p-2 transition-colors disabled:opacity-40"
              style={{
                background: "var(--surface-muted)",
                border: "1px solid var(--border-strong)",
                color: "var(--text-quiet)",
              }}
              title="Remove token"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        {feedback && (
          <p className="text-xs" style={{ color: feedback.ok ? "#22c55e" : "var(--danger)" }}>
            {feedback.msg}
          </p>
        )}
      </div>

      {/* Test message */}
      {config?.has_token && (
        <div
          className="rounded-xl p-4 space-y-3"
          style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}
        >
          <div>
            <p className="text-sm font-medium" style={{ color: "var(--text)" }}>Send Test Message</p>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-quiet)" }}>
              Enter your Telegram chat ID (open @userinfobot on Telegram to find it)
            </p>
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              value={chatIdInput}
              onChange={(e) => setChatIdInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") void handleTest(); }}
              placeholder="Your chat ID, e.g. 123456789"
              disabled={testing}
              className="flex-1 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none disabled:opacity-50"
              style={{
                background: "var(--surface-muted)",
                border: "1px solid var(--border-strong)",
                color: "var(--text)",
              }}
            />
            <button
              type="button"
              onClick={() => void handleTest()}
              disabled={testing || !chatIdInput.trim()}
              className="rounded-lg px-4 py-2 text-sm font-medium text-white transition-opacity disabled:opacity-40"
              style={{ background: "var(--accent)" }}
            >
              {testing ? "…" : "Test"}
            </button>
          </div>
        </div>
      )}

      {/* Webhook URL + Setup instructions */}
      <div
        className="rounded-xl p-4 space-y-3"
        style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}
      >
        <p className="text-sm font-medium" style={{ color: "var(--text)" }}>Setup Instructions</p>
        <ol className="space-y-2 text-xs" style={{ color: "var(--text-quiet)" }}>
          <li>1. Open Telegram and message <span className="font-mono" style={{ color: "var(--text)" }}>@BotFather</span></li>
          <li>2. Send <span className="font-mono" style={{ color: "var(--text)" }}>/newbot</span> and follow the prompts</li>
          <li>3. Copy the bot token and paste it above, then click Save</li>
          <li>
            4. Register the webhook URL with Telegram:
            <div
              className="mt-1.5 rounded-lg px-3 py-2 font-mono text-[11px] select-all break-all"
              style={{ background: "var(--surface-muted)", color: "var(--text)", border: "1px solid var(--border-strong)" }}
            >
              {webhookUrl}
            </div>
          </li>
          <li className="mt-1">
            5. Run this once (replace TOKEN):
            <div
              className="mt-1.5 rounded-lg px-3 py-2 font-mono text-[11px] select-all break-all"
              style={{ background: "var(--surface-muted)", color: "var(--text)", border: "1px solid var(--border-strong)" }}
            >
              {`curl -X POST "https://api.telegram.org/botTOKEN/setWebhook" -d "url=${webhookUrl}"`}
            </div>
          </li>
        </ol>

        <div className="pt-1">
          <p className="text-xs font-medium mb-2" style={{ color: "var(--text-quiet)" }}>Available commands:</p>
          <div className="grid grid-cols-2 gap-1">
            {[
              ["/status", "System health summary"],
              ["/health", "Detailed health check"],
              ["/projects", "List projects"],
              ["/agents", "Active agents"],
              ["/logs", "Log access info"],
              ["/deploy", "Trigger Render deploy"],
            ].map(([cmd, desc]) => (
              <div key={cmd} className="flex items-start gap-1.5">
                <span className="font-mono text-[11px] shrink-0" style={{ color: "var(--text)" }}>{cmd}</span>
                <span className="text-[11px]" style={{ color: "var(--text-quiet)" }}>{desc}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

// ── Settings page ─────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const [keyStatuses, setKeyStatuses] = useState<AllKeyStatuses | null>(null);
  const [ghStatuses, setGhStatuses] = useState<GitHubStatuses | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Tracks whether the first load is complete — suppresses error display until then
  const [initialLoadDone, setInitialLoadDone] = useState(false);

  const { fetchWithAuth } = useAuthFetch();

  useEffect(() => {
    Promise.all([fetchKeyStatuses(fetchWithAuth), fetchGitHubStatuses(fetchWithAuth)])
      .then(([keys, gh]) => {
        setKeyStatuses(keys);
        setGhStatuses(gh);
        setLoadError(null);
        setInitialLoadDone(true);
      })
      .catch((err) => {
        setInitialLoadDone(true);
        const msg = err instanceof Error ? err.message : "Failed to load.";
        setLoadError(msg);
        logSystemAction("error", "Settings page failed to load", msg);
      });
  }, [fetchWithAuth]);

  const updateKey = (provider: Provider, s: FieldStatus) =>
    setKeyStatuses((prev) => prev ? { ...prev, [provider]: s } : prev);
  const clearKeyStatus = (provider: Provider) =>
    setKeyStatuses((prev) =>
      prev ? { ...prev, [provider]: { configured: false, preview: null } } : prev,
    );

  const updateGh = (field: GitHubField, s: FieldStatus) =>
    setGhStatuses((prev) => prev ? { ...prev, [field]: s } : prev);
  const clearGhStatus = (field: GitHubField) =>
    setGhStatuses((prev) =>
      prev ? { ...prev, [field]: { configured: false, preview: null } } : prev,
    );

  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel message="Sign in to access Digidle OS" forceRedirectUrl="/settings" />
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <main className="flex-1 overflow-y-auto" style={{ background: "var(--bg)" }}>
          <div className="max-w-2xl mx-auto px-6 py-8 space-y-8">

            {/* Header */}
            <div>
              <h1 className="text-xl font-semibold" style={{ color: "var(--text)" }}>Settings</h1>
              <p className="mt-1 text-sm" style={{ color: "var(--text-muted)" }}>
                All credentials are encrypted and stored in the database. Changes take effect immediately.
              </p>
            </div>

            {loadError && initialLoadDone && (
              <div
                className="rounded-xl px-4 py-3 text-sm"
                style={{ background: "rgba(239,68,68,0.1)", color: "#ef4444", border: "1px solid rgba(239,68,68,0.2)" }}
              >
                {loadError}
              </div>
            )}

            {/* Credentials — owner only */}
            <RoleGuard
              require="owner"
              denied={
                <section
                  className="rounded-xl px-4 py-3 text-sm space-y-1"
                  style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}
                >
                  <p className="font-medium" style={{ color: "var(--text)" }}>API Keys &amp; GitHub</p>
                  <p style={{ color: "var(--text-quiet)" }}>Credential management is restricted to owners.</p>
                </section>
              }
            >
              {/* API Keys */}
              <section className="space-y-3">
                <h2 className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>
                  API Keys
                </h2>
                {PROVIDERS.map(({ id, label, hint, placeholder }) => (
                  <FieldRow
                    key={id}
                    label={label}
                    hint={hint}
                    placeholder={placeholder}
                    secret={true}
                    status={keyStatuses?.[id]}
                    onSave={(v) => saveKey(id, v, fetchWithAuth).then((s) => { updateKey(id, s); return s; })}
                    onClear={() => clearKey(id, fetchWithAuth).then(() => clearKeyStatus(id))}
                  />
                ))}
              </section>

              {/* GitHub */}
              <section className="space-y-3">
                <h2 className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>
                  GitHub
                </h2>
                <p className="text-xs" style={{ color: "var(--text-quiet)" }}>
                  Used by the Save button to commit and push to your repository.
                </p>
                {GITHUB_FIELDS.map(({ id, label, hint, placeholder, secret }) => (
                  <FieldRow
                    key={id}
                    label={label}
                    hint={hint}
                    placeholder={placeholder}
                    secret={secret}
                    status={ghStatuses?.[id]}
                    onSave={(v) => saveGitHubField(id, v, fetchWithAuth).then((s) => { updateGh(id, s); return s; })}
                    onClear={() => clearGitHubField(id, fetchWithAuth).then(() => clearGhStatus(id))}
                  />
                ))}
              </section>
              {/* Remote Access — Telegram */}
              <TelegramSection fetchFn={fetchWithAuth} />
            </RoleGuard>

            {/* ── Integration Foundations ─────────────────────────────────── */}
            {/* These sections are placeholders for future integrations.       */}
            {/* Keys will be stored encrypted in the DB via the API Keys flow. */}
            <section className="space-y-3 opacity-60">
              <div className="flex items-center gap-2">
                <p className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>
                  Integrations
                </p>
                <span className="rounded-full px-2 py-0.5 text-[10px] font-medium" style={{ background: "rgba(99,102,241,0.15)", color: "#818cf8" }}>
                  Coming soon
                </span>
              </div>
              {[
                { name: "n8n", desc: "Workflow automation — connect webhooks and automate tasks", icon: "⚡" },
                { name: "ElevenLabs", desc: "AI voice synthesis — text-to-speech for agents", icon: "🔊" },
                { name: "Higgsfield", desc: "AI video generation — create video content from prompts", icon: "🎬" },
                { name: "Artlist", desc: "Music licensing — royalty-free audio for content", icon: "🎵" },
              ].map(({ name, desc, icon }) => (
                <div
                  key={name}
                  className="flex items-center justify-between rounded-xl px-4 py-3 border"
                  style={{ borderColor: "var(--border)", background: "var(--surface)" }}
                >
                  <div className="flex items-center gap-3">
                    <span className="text-lg">{icon}</span>
                    <div>
                      <p className="text-sm font-medium" style={{ color: "var(--text)" }}>{name}</p>
                      <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>{desc}</p>
                    </div>
                  </div>
                  <span className="text-xs rounded-full px-2.5 py-1" style={{ background: "var(--surface-muted)", color: "var(--text-quiet)" }}>
                    Not connected
                  </span>
                </div>
              ))}
            </section>

          </div>
        </main>
      </SignedIn>
    </DashboardShell>
  );
}

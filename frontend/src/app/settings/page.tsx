"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";
import { Eye, EyeOff, X } from "lucide-react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { getLocalAuthToken } from "@/auth/localAuth";
import { getApiBaseUrl } from "@/lib/api-base";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";

// ── Types ────────────────────────────────────────────────────────────────────

type Provider = "openai" | "gemini" | "anthropic";
type KeyStatus = { configured: boolean; preview: string | null };
type AllKeyStatuses = Record<Provider, KeyStatus>;

const PROVIDERS: { id: Provider; label: string; hint: string; placeholder: string }[] = [
  {
    id: "openai",
    label: "OpenAI",
    hint: "Used by ChatGPT tab",
    placeholder: "sk-proj-...",
  },
  {
    id: "gemini",
    label: "Gemini",
    hint: "Used by Gemini tab",
    placeholder: "AIza...",
  },
  {
    id: "anthropic",
    label: "Claude (direct)",
    hint: "Anthropic API key — for direct Claude access",
    placeholder: "sk-ant-...",
  },
];

// ── API helpers ──────────────────────────────────────────────────────────────

function authHeaders(): Record<string, string> {
  const token = getLocalAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function fetchStatuses(): Promise<AllKeyStatuses> {
  const res = await fetch(`${getApiBaseUrl()}/api/v1/settings/api-keys`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<AllKeyStatuses>;
}

async function saveKey(provider: Provider, key: string): Promise<KeyStatus> {
  const res = await fetch(`${getApiBaseUrl()}/api/v1/settings/api-keys/${provider}`, {
    method: "PUT",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({ key }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<KeyStatus>;
}

async function clearKey(provider: Provider): Promise<void> {
  await fetch(`${getApiBaseUrl()}/api/v1/settings/api-keys/${provider}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
}

// ── Key row ──────────────────────────────────────────────────────────────────

function KeyRow({
  id,
  label,
  hint,
  placeholder,
  status,
  onSaved,
  onCleared,
}: {
  id: Provider;
  label: string;
  hint: string;
  placeholder: string;
  status: KeyStatus | undefined;
  onSaved: (s: KeyStatus) => void;
  onCleared: () => void;
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
    if (!trimmed) { fb(false, "Enter a key first."); return; }
    setSaving(true);
    try {
      const s = await saveKey(id, trimmed);
      onSaved(s);
      setValue("");
      fb(true, "Saved.");
    } catch (err) {
      fb(false, err instanceof Error ? err.message : "Failed to save.");
    } finally {
      setSaving(false);
    }
  };

  const handleClear = async () => {
    setSaving(true);
    try {
      await clearKey(id);
      onCleared();
      setValue("");
      fb(true, "Removed.");
    } catch {
      fb(false, "Failed to remove.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="rounded-xl p-4 space-y-3"
      style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}
    >
      {/* Header row */}
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
              {status.preview && (
                <span className="font-mono ml-1" style={{ color: "var(--text-quiet)" }}>
                  {status.preview}
                </span>
              )}
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

      {/* Input row */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <input
            type={shown ? "text" : "password"}
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
          <button
            type="button"
            tabIndex={-1}
            onClick={() => setShown((s) => !s)}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 transition-opacity hover:opacity-70"
            style={{ color: "var(--text-quiet)" }}
          >
            {shown ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
          </button>
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
            title="Remove key"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {/* Feedback */}
      {feedback && (
        <p
          className="text-xs"
          style={{ color: feedback.ok ? "#22c55e" : "var(--danger)" }}
        >
          {feedback.msg}
        </p>
      )}
    </div>
  );
}

// ── Settings page ────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const [statuses, setStatuses] = useState<AllKeyStatuses | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    fetchStatuses()
      .then((data) => { setStatuses(data); setLoadError(null); })
      .catch((err) => setLoadError(err instanceof Error ? err.message : "Failed to load."));
  }, []);

  const updateStatus = (provider: Provider, s: KeyStatus) =>
    setStatuses((prev) => prev ? { ...prev, [provider]: s } : prev);

  const clearStatus = (provider: Provider) =>
    setStatuses((prev) =>
      prev ? { ...prev, [provider]: { configured: false, preview: null } } : prev,
    );

  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel
          message="Sign in to access Digidle OS"
          forceRedirectUrl="/settings"
        />
      </SignedOut>

      <SignedIn>
        <DashboardSidebar />

        <main
          className="flex-1 overflow-y-auto"
          style={{ background: "var(--bg)" }}
        >
          <div className="max-w-2xl mx-auto px-6 py-8 space-y-8">

            {/* Page header */}
            <div>
              <h1
                className="text-xl font-semibold"
                style={{ color: "var(--text)" }}
              >
                Settings
              </h1>
              <p className="mt-1 text-sm" style={{ color: "var(--text-muted)" }}>
                API keys are encrypted and stored in the database. Changes take effect immediately.
              </p>
            </div>

            {/* API Keys */}
            <section className="space-y-3">
              <h2 className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>
                API Keys
              </h2>

              {loadError && (
                <div
                  className="rounded-xl px-4 py-3 text-sm"
                  style={{ background: "rgba(239,68,68,0.1)", color: "#ef4444", border: "1px solid rgba(239,68,68,0.2)" }}
                >
                  {loadError}
                </div>
              )}

              {PROVIDERS.map(({ id, label, hint, placeholder }) => (
                <KeyRow
                  key={id}
                  id={id}
                  label={label}
                  hint={hint}
                  placeholder={placeholder}
                  status={statuses?.[id]}
                  onSaved={(s) => updateStatus(id, s)}
                  onCleared={() => clearStatus(id)}
                />
              ))}
            </section>

          </div>
        </main>
      </SignedIn>
    </DashboardShell>
  );
}

"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";
import { Eye, EyeOff, Loader2, Trash2, Zap } from "lucide-react";

import { SectionShell } from "@/components/of-intelligence/SectionShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import { ofiApi, type CredentialStatus, type PingResponse } from "@/lib/of-intelligence/api";

export default function OfIntelligenceSettingsPage() {
  const { fetchWithAuth } = useAuthFetch();

  const [creds, setCreds] = useState<CredentialStatus | null>(null);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [baseUrlInput, setBaseUrlInput] = useState("");
  const [revealApiKey, setRevealApiKey] = useState(false);
  const [busy, setBusy] = useState(false);
  const [ping, setPing] = useState<PingResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await ofiApi.credentials(fetchWithAuth);
      setCreds(res);
      setBaseUrlInput(res.base_url);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [fetchWithAuth]);

  useEffect(() => { void load(); }, [load]);

  const onSave = useCallback(async () => {
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const body: { api_key?: string; base_url?: string } = {};
      if (apiKeyInput.trim()) body.api_key = apiKeyInput.trim();
      if (baseUrlInput.trim() && baseUrlInput.trim() !== creds?.base_url) {
        body.base_url = baseUrlInput.trim();
      }
      if (Object.keys(body).length === 0) {
        setInfo("No changes to save.");
        return;
      }
      const res = await ofiApi.saveCredentials(fetchWithAuth, body);
      setCreds(res);
      setApiKeyInput("");
      setInfo("Saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [apiKeyInput, baseUrlInput, creds, fetchWithAuth]);

  const onClear = useCallback(async () => {
    if (!confirm("Clear the OnlyMonster API key from the database? Local-dev .env fallback will still apply.")) return;
    setBusy(true);
    setError(null);
    try {
      await ofiApi.deleteCredentials(fetchWithAuth);
      await load();
      setInfo("API key cleared.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [fetchWithAuth, load]);

  const onTest = useCallback(async () => {
    setBusy(true);
    setError(null);
    setPing(null);
    try {
      const res = await ofiApi.testConnection(fetchWithAuth);
      setPing(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [fetchWithAuth]);

  return (
    <SectionShell
      title="Settings"
      description="OnlyMonster API credentials, sync defaults, and Obsidian export options. The API key never leaves the backend."
    >
      <div className="space-y-6 max-w-3xl">
        <section
          className="rounded-xl border p-5"
          style={{ background: "var(--surface)", borderColor: "var(--border)" }}
        >
          <h2 className="text-sm font-semibold" style={{ color: "var(--text)" }}>OnlyMonster API key</h2>
          <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
            Stored encrypted in the database. Falls back to <code>ONLYMONSTER_API_KEY</code> in <code>.env</code> for local dev.
            The key is never sent to the browser — only the source flag and a masked preview.
          </p>

          <div className="mt-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs" style={{ color: "var(--text-quiet)" }}>
                Current source: <span style={{ color: "var(--text)" }}>{creds?.api_key_source ?? "unknown"}</span>
              </span>
              {creds?.api_key_preview && (
                <span className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>{creds.api_key_preview}</span>
              )}
            </div>

            <div className="flex gap-2">
              <div className="relative flex-1">
                <input
                  type={revealApiKey ? "text" : "password"}
                  value={apiKeyInput}
                  onChange={(e) => setApiKeyInput(e.target.value)}
                  placeholder="om_..."
                  className="w-full rounded-md border px-3 py-2 text-sm"
                  style={{
                    background: "var(--bg)",
                    borderColor: "var(--border)",
                    color: "var(--text)",
                  }}
                />
                <button
                  type="button"
                  onClick={() => setRevealApiKey((v) => !v)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1"
                  style={{ color: "var(--text-quiet)" }}
                  aria-label={revealApiKey ? "Hide" : "Show"}
                >
                  {revealApiKey ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                </button>
              </div>
              <button
                type="button"
                onClick={() => void onSave()}
                disabled={busy || !apiKeyInput.trim()}
                className="rounded-md px-3 py-2 text-sm font-medium disabled:opacity-50"
                style={{ background: "var(--accent-strong)", color: "white" }}
              >
                Save
              </button>
              {creds?.has_token && creds.api_key_source === "db" && (
                <button
                  type="button"
                  onClick={() => void onClear()}
                  disabled={busy}
                  className="rounded-md border px-3 py-2 text-sm"
                  style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
                  aria-label="Clear API key"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </div>
        </section>

        <section
          className="rounded-xl border p-5"
          style={{ background: "var(--surface)", borderColor: "var(--border)" }}
        >
          <h2 className="text-sm font-semibold" style={{ color: "var(--text)" }}>API base URL</h2>
          <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
            Override per environment. Defaults to <code>ONLYMONSTER_API_BASE_URL</code>.
          </p>
          <div className="mt-3 flex gap-2">
            <input
              type="url"
              value={baseUrlInput}
              onChange={(e) => setBaseUrlInput(e.target.value)}
              placeholder="https://api.onlymonster.ai/v1"
              className="flex-1 rounded-md border px-3 py-2 text-sm font-mono"
              style={{
                background: "var(--bg)",
                borderColor: "var(--border)",
                color: "var(--text)",
              }}
            />
            <button
              type="button"
              onClick={() => void onSave()}
              disabled={busy || baseUrlInput.trim() === creds?.base_url}
              className="rounded-md border px-3 py-2 text-sm disabled:opacity-50"
              style={{ borderColor: "var(--border)", color: "var(--text)" }}
            >
              Save URL
            </button>
          </div>
        </section>

        <section
          className="rounded-xl border p-5"
          style={{ background: "var(--surface)", borderColor: "var(--border)" }}
        >
          <h2 className="text-sm font-semibold" style={{ color: "var(--text)" }}>Connection test</h2>
          <button
            type="button"
            onClick={() => void onTest()}
            disabled={busy || !creds?.has_token}
            className="mt-3 inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50"
            style={{ background: "var(--accent-strong)", color: "white" }}
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
            Run test
          </button>
          {ping && (
            <div className="mt-3 space-y-2">
              <div
                className="rounded-md border p-3 text-sm"
                style={{
                  borderColor: ping.ok ? "rgb(16,185,129)" : "rgb(248,113,113)",
                  background: "var(--bg)",
                }}
              >
                <p className="font-medium" style={{ color: ping.ok ? "rgb(5,150,105)" : "rgb(225,29,72)" }}>
                  {ping.ok
                    ? `ok: true · status_code: ${ping.status_code ?? "—"}`
                    : `ok: false · status_code: ${ping.status_code ?? "—"} · error_source: ${ping.error_source}`}
                </p>
                {ping.message && (
                  <p className="mt-1" style={{ color: "var(--text)" }}>{ping.message}</p>
                )}
                {ping.tested_url && (
                  <p className="mt-1 text-xs font-mono" style={{ color: "var(--text-quiet)" }}>
                    tested_url: {ping.tested_url}
                  </p>
                )}
                {ping.latency_ms != null && (
                  <p className="mt-1 text-xs" style={{ color: "var(--text-quiet)" }}>
                    latency: {Math.round(ping.latency_ms)}ms · key source: {ping.api_key_source}
                  </p>
                )}
              </div>
            </div>
          )}
        </section>

        {(error || info) && (
          <div
            className="rounded-md border p-3 text-sm"
            style={{
              borderColor: error ? "rgb(248,113,113)" : "var(--border)",
              color: error ? "rgb(225,29,72)" : "var(--text-muted)",
            }}
          >
            {error || info}
          </div>
        )}

        <section
          className="rounded-xl border p-5"
          style={{ background: "var(--surface)", borderColor: "var(--border)" }}
        >
          <h2 className="text-sm font-semibold" style={{ color: "var(--text)" }}>Sync &amp; report defaults</h2>
          <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
            Daily sync, QC report time, alert thresholds, Obsidian export path, and per-account monitoring lists will live
            here.  Phase 1 ships the backend hooks for these settings; the UI form arrives once the daily-sync scheduler is wired.
          </p>
        </section>
      </div>
    </SectionShell>
  );
}

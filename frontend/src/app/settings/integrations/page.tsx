"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";
import { Eye, EyeOff, ExternalLink, X } from "lucide-react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { getApiBaseUrl } from "@/lib/api-base";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";

// ── Types ─────────────────────────────────────────────────────────────────────

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

// ── Page body ─────────────────────────────────────────────────────────────────

function IntegrationsBody() {
  const { fetchWithAuth } = useAuthFetch();
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [loading, setLoading]           = useState(true);
  const [error, setError]               = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    fetchIntegrations(fetchWithAuth)
      .then(setIntegrations)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, [fetchWithAuth]);

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

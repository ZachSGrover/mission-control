"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Archive,
  CheckCircle2,
  ClipboardList,
  Hammer,
  Loader2,
  Plus,
  RefreshCw,
  Send,
  ShieldCheck,
} from "lucide-react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import { useRole } from "@/hooks/use-role";
import { getApiBaseUrl } from "@/lib/api-base";

// ── Types (mirrors backend BotDraftResponse) ──────────────────────────────────

const RISK_LEVELS = ["low", "medium", "high"] as const;
type RiskLevel = (typeof RISK_LEVELS)[number];

type DraftStatus = "draft" | "pending_approval" | "approved" | "archived";

interface BotDraft {
  id: string;
  slug: string;
  name: string;
  purpose: string;
  category: string;
  description: string | null;
  owner: string | null;
  status: DraftStatus;
  sandbox_mode: boolean;
  risk_level: RiskLevel;
  approval_required: boolean;
  trigger_type: string | null;
  input_requirements: string | null;
  output_requirements: string | null;
  prompt_template: string | null;
  dashboard_notes: string | null;
  tools_needed: string[];
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
}

type FetchFn = (url: string, init?: RequestInit) => Promise<Response>;

// ── API helpers ───────────────────────────────────────────────────────────────

async function fetchDrafts(fetchFn: FetchFn): Promise<BotDraft[]> {
  const res = await fetchFn(`${getApiBaseUrl()}/api/v1/bot-drafts`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as BotDraft[];
}

async function createDraft(body: Partial<BotDraft>, fetchFn: FetchFn): Promise<BotDraft> {
  const res = await fetchFn(`${getApiBaseUrl()}/api/v1/bot-drafts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = (await res.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(detail?.detail ?? `HTTP ${res.status}`);
  }
  return (await res.json()) as BotDraft;
}

async function updateDraft(
  id: string,
  body: Partial<BotDraft>,
  fetchFn: FetchFn,
): Promise<BotDraft> {
  const res = await fetchFn(`${getApiBaseUrl()}/api/v1/bot-drafts/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = (await res.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(detail?.detail ?? `HTTP ${res.status}`);
  }
  return (await res.json()) as BotDraft;
}

async function archiveDraft(id: string, fetchFn: FetchFn): Promise<BotDraft> {
  const res = await fetchFn(`${getApiBaseUrl()}/api/v1/bot-drafts/${id}/archive`, {
    method: "POST",
  });
  if (!res.ok) {
    const detail = (await res.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(detail?.detail ?? `HTTP ${res.status}`);
  }
  return (await res.json()) as BotDraft;
}

async function requestApproval(id: string, fetchFn: FetchFn): Promise<BotDraft> {
  const res = await fetchFn(
    `${getApiBaseUrl()}/api/v1/bot-drafts/${id}/request-approval`,
    { method: "POST" },
  );
  if (!res.ok) {
    const detail = (await res.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(detail?.detail ?? `HTTP ${res.status}`);
  }
  return (await res.json()) as BotDraft;
}

async function approveDraft(id: string, fetchFn: FetchFn): Promise<BotDraft> {
  const res = await fetchFn(
    `${getApiBaseUrl()}/api/v1/bot-drafts/${id}/approve`,
    { method: "POST" },
  );
  if (!res.ok) {
    const detail = (await res.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(detail?.detail ?? `HTTP ${res.status}`);
  }
  return (await res.json()) as BotDraft;
}

// ── Form ──────────────────────────────────────────────────────────────────────

interface FormState {
  slug: string;
  name: string;
  purpose: string;
  category: string;
  description: string;
  owner: string;
  risk_level: RiskLevel;
  approval_required: boolean;
  trigger_type: string;
  input_requirements: string;
  output_requirements: string;
  prompt_template: string;
  dashboard_notes: string;
  tools_needed: string;
}

function emptyForm(): FormState {
  return {
    slug: "",
    name: "",
    purpose: "",
    category: "general",
    description: "",
    owner: "",
    risk_level: "low",
    approval_required: true,
    trigger_type: "manual",
    input_requirements: "",
    output_requirements: "",
    prompt_template: "",
    dashboard_notes: "",
    tools_needed: "",
  };
}

function formFromDraft(d: BotDraft): FormState {
  return {
    slug: d.slug,
    name: d.name,
    purpose: d.purpose,
    category: d.category,
    description: d.description ?? "",
    owner: d.owner ?? "",
    risk_level: d.risk_level,
    approval_required: d.approval_required,
    trigger_type: d.trigger_type ?? "",
    input_requirements: d.input_requirements ?? "",
    output_requirements: d.output_requirements ?? "",
    prompt_template: d.prompt_template ?? "",
    dashboard_notes: d.dashboard_notes ?? "",
    tools_needed: d.tools_needed.join(", "),
  };
}

function bodyFromForm(form: FormState, includeSlug: boolean): Partial<BotDraft> {
  const tools = form.tools_needed
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
  const body: Partial<BotDraft> & { tools_needed: string[] } = {
    name: form.name.trim(),
    purpose: form.purpose.trim(),
    category: form.category.trim() || "general",
    description: form.description.trim() || null,
    owner: form.owner.trim() || null,
    risk_level: form.risk_level,
    approval_required: form.approval_required,
    trigger_type: form.trigger_type.trim() || null,
    input_requirements: form.input_requirements.trim() || null,
    output_requirements: form.output_requirements.trim() || null,
    prompt_template: form.prompt_template.trim() || null,
    dashboard_notes: form.dashboard_notes.trim() || null,
    tools_needed: tools,
  };
  if (includeSlug) body.slug = form.slug.trim().toLowerCase();
  return body;
}

function StatusPill({ status }: { status: DraftStatus }) {
  const map: Record<DraftStatus, { bg: string; fg: string; label: string }> = {
    draft: { bg: "rgba(107,114,128,0.15)", fg: "#9ca3af", label: "Draft" },
    pending_approval: {
      bg: "rgba(234,179,8,0.18)",
      fg: "#eab308",
      label: "Pending approval",
    },
    approved: { bg: "rgba(34,197,94,0.18)", fg: "#22c55e", label: "Approved" },
    archived: { bg: "rgba(107,114,128,0.10)", fg: "#9ca3af", label: "Archived" },
  };
  const c = map[status];
  return (
    <span
      className="rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider"
      style={{ background: c.bg, color: c.fg }}
    >
      {c.label}
    </span>
  );
}

function RiskBadge({ risk }: { risk: RiskLevel }) {
  const colors: Record<RiskLevel, { bg: string; fg: string }> = {
    low: { bg: "rgba(34,197,94,0.15)", fg: "#22c55e" },
    medium: { bg: "rgba(234,179,8,0.18)", fg: "#eab308" },
    high: { bg: "rgba(239,68,68,0.18)", fg: "#ef4444" },
  };
  const c = colors[risk];
  return (
    <span
      className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider"
      style={{ background: c.bg, color: c.fg }}
    >
      risk: {risk}
    </span>
  );
}

// ── Bot draft form ─────────────────────────────────────────────────────────

function BotDraftForm({
  initial,
  isEditing,
  busy,
  onSubmit,
  onCancel,
}: {
  initial: FormState;
  isEditing: boolean;
  busy: boolean;
  onSubmit: (body: Partial<BotDraft>) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<FormState>(initial);

  useEffect(() => {
    setForm(initial);
  }, [initial]);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const inputBase = "w-full rounded-md px-3 py-2 text-sm focus:outline-none disabled:opacity-50";
  const inputStyle = {
    background: "var(--surface-muted)",
    border: "1px solid var(--border)",
    color: "var(--text)",
  } as const;

  return (
    <form
      data-testid="bot-builder-form"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(bodyFromForm(form, !isEditing));
      }}
      className="rounded-xl p-4 space-y-3"
      style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="text-xs space-y-1">
          <span style={{ color: "var(--text-quiet)" }}>Slug</span>
          <input
            type="text"
            value={form.slug}
            disabled={isEditing || busy}
            onChange={(e) => update("slug", e.target.value)}
            placeholder="rt-bot-v1"
            data-testid="bot-builder-slug"
            className={inputBase}
            style={inputStyle}
            required={!isEditing}
          />
        </label>
        <label className="text-xs space-y-1">
          <span style={{ color: "var(--text-quiet)" }}>Name</span>
          <input
            type="text"
            value={form.name}
            disabled={busy}
            onChange={(e) => update("name", e.target.value)}
            data-testid="bot-builder-name"
            className={inputBase}
            style={inputStyle}
            required
          />
        </label>
      </div>

      <label className="text-xs space-y-1 block">
        <span style={{ color: "var(--text-quiet)" }}>Purpose</span>
        <input
          type="text"
          value={form.purpose}
          disabled={busy}
          onChange={(e) => update("purpose", e.target.value)}
          className={inputBase}
          style={inputStyle}
          required
        />
      </label>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="text-xs space-y-1">
          <span style={{ color: "var(--text-quiet)" }}>Category</span>
          <input
            type="text"
            value={form.category}
            disabled={busy}
            onChange={(e) => update("category", e.target.value)}
            className={inputBase}
            style={inputStyle}
          />
        </label>
        <label className="text-xs space-y-1">
          <span style={{ color: "var(--text-quiet)" }}>Owner (label)</span>
          <input
            type="text"
            value={form.owner}
            disabled={busy}
            onChange={(e) => update("owner", e.target.value)}
            className={inputBase}
            style={inputStyle}
            placeholder="founder, growth, …"
          />
        </label>
        <label className="text-xs space-y-1">
          <span style={{ color: "var(--text-quiet)" }}>Risk level</span>
          <select
            value={form.risk_level}
            disabled={busy}
            onChange={(e) => update("risk_level", e.target.value as RiskLevel)}
            className={inputBase}
            style={inputStyle}
          >
            {RISK_LEVELS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className="text-xs space-y-1 block">
        <span style={{ color: "var(--text-quiet)" }}>Description</span>
        <textarea
          value={form.description}
          disabled={busy}
          onChange={(e) => update("description", e.target.value)}
          className={inputBase}
          style={inputStyle}
          rows={2}
        />
      </label>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="text-xs space-y-1">
          <span style={{ color: "var(--text-quiet)" }}>Trigger type</span>
          <input
            type="text"
            value={form.trigger_type}
            disabled={busy}
            onChange={(e) => update("trigger_type", e.target.value)}
            className={inputBase}
            style={inputStyle}
            placeholder="manual, cron:0 9 * * *, …"
          />
        </label>
        <label className="text-xs space-y-1">
          <span style={{ color: "var(--text-quiet)" }}>Tools needed (comma-separated)</span>
          <input
            type="text"
            value={form.tools_needed}
            disabled={busy}
            onChange={(e) => update("tools_needed", e.target.value)}
            className={inputBase}
            style={inputStyle}
            placeholder="timeline-reader, scheduler"
          />
        </label>
      </div>

      <label className="text-xs space-y-1 block">
        <span style={{ color: "var(--text-quiet)" }}>Input requirements</span>
        <textarea
          value={form.input_requirements}
          disabled={busy}
          onChange={(e) => update("input_requirements", e.target.value)}
          className={inputBase}
          style={inputStyle}
          rows={2}
        />
      </label>

      <label className="text-xs space-y-1 block">
        <span style={{ color: "var(--text-quiet)" }}>Output requirements</span>
        <textarea
          value={form.output_requirements}
          disabled={busy}
          onChange={(e) => update("output_requirements", e.target.value)}
          className={inputBase}
          style={inputStyle}
          rows={2}
        />
      </label>

      <label className="text-xs space-y-1 block">
        <span style={{ color: "var(--text-quiet)" }}>Prompt template</span>
        <textarea
          value={form.prompt_template}
          disabled={busy}
          onChange={(e) => update("prompt_template", e.target.value)}
          className={inputBase}
          style={inputStyle}
          rows={3}
        />
      </label>

      <label className="text-xs space-y-1 block">
        <span style={{ color: "var(--text-quiet)" }}>Dashboard notes</span>
        <textarea
          value={form.dashboard_notes}
          disabled={busy}
          onChange={(e) => update("dashboard_notes", e.target.value)}
          className={inputBase}
          style={inputStyle}
          rows={2}
        />
      </label>

      <label className="inline-flex items-center gap-2 text-xs">
        <input
          type="checkbox"
          checked={form.approval_required}
          disabled={busy}
          onChange={(e) => update("approval_required", e.target.checked)}
        />
        <span style={{ color: "var(--text-muted)" }}>
          Requires owner approval before activation
        </span>
      </label>

      <div className="flex items-center gap-2 pt-1">
        <button
          type="submit"
          disabled={busy}
          data-testid="bot-builder-save"
          className="inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50"
          style={{ background: "var(--accent)", color: "#fff" }}
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
          {isEditing ? "Save changes" : "Create draft"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="rounded-md px-3 py-1.5 text-sm"
          style={{
            background: "var(--surface-muted)",
            color: "var(--text-muted)",
            border: "1px solid var(--border)",
          }}
        >
          Cancel
        </button>
        <p className="ml-auto text-[11px]" style={{ color: "var(--text-quiet)" }}>
          Sandbox-only.  No live actions, no secrets.
        </p>
      </div>
    </form>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

function BotBuilderContent() {
  const { fetchWithAuth } = useAuthFetch();
  const { realRole } = useRole();
  const isOwner = realRole === "owner";

  const [drafts, setDrafts] = useState<BotDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [opError, setOpError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await fetchDrafts(fetchWithAuth);
      setDrafts(data);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Failed to load drafts.");
    } finally {
      setLoading(false);
    }
  }, [fetchWithAuth]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const editingDraft = useMemo(
    () => drafts.find((d) => d.id === editingId) ?? null,
    [drafts, editingId],
  );

  const handleCreate = async (body: Partial<BotDraft>) => {
    setBusy(true);
    setOpError(null);
    try {
      const created = await createDraft(body, fetchWithAuth);
      setDrafts((prev) => [...prev, created]);
      setCreating(false);
    } catch (e) {
      setOpError(e instanceof Error ? e.message : "Failed to create draft.");
    } finally {
      setBusy(false);
    }
  };

  const handleUpdate = async (body: Partial<BotDraft>) => {
    if (!editingId) return;
    setBusy(true);
    setOpError(null);
    try {
      const updated = await updateDraft(editingId, body, fetchWithAuth);
      setDrafts((prev) => prev.map((d) => (d.id === updated.id ? updated : d)));
      setEditingId(null);
    } catch (e) {
      setOpError(e instanceof Error ? e.message : "Failed to update draft.");
    } finally {
      setBusy(false);
    }
  };

  const onArchive = async (d: BotDraft) => {
    setBusy(true);
    setOpError(null);
    try {
      const next = await archiveDraft(d.id, fetchWithAuth);
      setDrafts((prev) => prev.map((row) => (row.id === next.id ? next : row)));
    } catch (e) {
      setOpError(e instanceof Error ? e.message : "Failed to archive draft.");
    } finally {
      setBusy(false);
    }
  };

  const onRequestApproval = async (d: BotDraft) => {
    setBusy(true);
    setOpError(null);
    try {
      const next = await requestApproval(d.id, fetchWithAuth);
      setDrafts((prev) => prev.map((row) => (row.id === next.id ? next : row)));
    } catch (e) {
      setOpError(e instanceof Error ? e.message : "Failed to request approval.");
    } finally {
      setBusy(false);
    }
  };

  const onApprove = async (d: BotDraft) => {
    setBusy(true);
    setOpError(null);
    try {
      const next = await approveDraft(d.id, fetchWithAuth);
      setDrafts((prev) => prev.map((row) => (row.id === next.id ? next : row)));
    } catch (e) {
      setOpError(e instanceof Error ? e.message : "Failed to approve draft.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex-1 overflow-y-auto" style={{ background: "var(--bg)" }}>
      <div className="max-w-3xl mx-auto px-6 py-8 space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1
              className="flex items-center gap-2 text-xl font-semibold"
              style={{ color: "var(--text)" }}
            >
              <Hammer className="h-5 w-5" aria-hidden="true" />
              Bot Builder
            </h1>
            <p className="mt-1 text-sm" style={{ color: "var(--text-muted)" }}>
              Author a bot spec.  Drafts are sandbox-only — they never call live
              platform APIs and cannot run code.  When the spec is ready, request
              owner approval; activation remains a deliberate, separate step.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void refresh()}
              className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs"
              style={{
                background: "var(--surface-strong)",
                border: "1px solid var(--border)",
                color: "var(--text-muted)",
              }}
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh
            </button>
            <button
              type="button"
              onClick={() => {
                setCreating(true);
                setEditingId(null);
                setOpError(null);
              }}
              disabled={busy}
              data-testid="bot-builder-new"
              className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-medium text-white"
              style={{ background: "var(--accent)" }}
            >
              <Plus className="h-3.5 w-3.5" />
              New draft
            </button>
          </div>
        </div>

        <div
          className="rounded-xl px-4 py-3 text-xs space-y-1"
          style={{
            background: "rgba(168,85,247,0.08)",
            border: "1px solid rgba(168,85,247,0.2)",
            color: "var(--text-muted)",
          }}
        >
          <p className="flex items-center gap-1.5 font-medium" style={{ color: "var(--text)" }}>
            <ShieldCheck className="h-3.5 w-3.5" /> Safety contract
          </p>
          <p>
            Drafts cannot include API keys, tokens, cookies, webhook URLs, or
            DSN URLs.  Sandbox mode is forced on; the API rejects any attempt
            to flip it off.  Activation is intentionally not implemented in
            v1.
          </p>
        </div>

        {loadError && (
          <div
            className="rounded-xl px-4 py-3 text-sm"
            style={{
              background: "rgba(239,68,68,0.1)",
              color: "#ef4444",
              border: "1px solid rgba(239,68,68,0.2)",
            }}
          >
            {loadError}
          </div>
        )}

        {opError && (
          <div
            className="rounded-xl px-4 py-3 text-sm"
            style={{
              background: "rgba(239,68,68,0.1)",
              color: "#ef4444",
              border: "1px solid rgba(239,68,68,0.2)",
            }}
            data-testid="bot-builder-error"
          >
            <AlertTriangle className="inline h-3.5 w-3.5 mr-1" />
            {opError}
          </div>
        )}

        {creating && (
          <BotDraftForm
            initial={emptyForm()}
            isEditing={false}
            busy={busy}
            onSubmit={(body) => void handleCreate(body)}
            onCancel={() => setCreating(false)}
          />
        )}

        {editingDraft && (
          <BotDraftForm
            initial={formFromDraft(editingDraft)}
            isEditing
            busy={busy}
            onSubmit={(body) => void handleUpdate(body)}
            onCancel={() => setEditingId(null)}
          />
        )}

        {loading ? (
          <p className="text-sm" style={{ color: "var(--text-quiet)" }}>
            Loading drafts…
          </p>
        ) : drafts.length === 0 ? (
          <div
            className="rounded-xl px-4 py-6 text-center text-sm space-y-2"
            style={{
              background: "var(--surface-strong)",
              border: "1px dashed var(--border)",
              color: "var(--text-quiet)",
            }}
            data-testid="bot-builder-empty"
          >
            <ClipboardList className="mx-auto h-6 w-6" aria-hidden="true" />
            <p>No bot drafts yet.  Click <strong>New draft</strong> to author one.</p>
          </div>
        ) : (
          <div className="space-y-3" data-testid="bot-builder-list">
            {drafts.map((d) => (
              <article
                key={d.id}
                data-testid="bot-builder-row"
                className="rounded-xl px-4 py-3 space-y-2"
                style={{
                  background: "var(--surface-strong)",
                  border: "1px solid var(--border)",
                  opacity: d.status === "archived" ? 0.65 : 1,
                }}
              >
                <header className="flex flex-wrap items-center gap-2">
                  <p className="text-sm font-medium" style={{ color: "var(--text)" }}>
                    {d.name}
                  </p>
                  <span
                    className="text-[10px] font-mono uppercase"
                    style={{ color: "var(--text-quiet)" }}
                  >
                    {d.slug}
                  </span>
                  <StatusPill status={d.status} />
                  <RiskBadge risk={d.risk_level} />
                  {d.sandbox_mode && (
                    <span
                      className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider"
                      style={{ background: "rgba(168,85,247,0.10)", color: "#c084fc" }}
                    >
                      sandbox
                    </span>
                  )}
                  {d.approval_required && (
                    <span
                      className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider"
                      style={{ background: "rgba(234,179,8,0.18)", color: "#eab308" }}
                    >
                      requires approval
                    </span>
                  )}
                </header>
                <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                  {d.purpose}
                </p>
                {d.description && (
                  <p className="text-xs" style={{ color: "var(--text-quiet)" }}>
                    {d.description}
                  </p>
                )}
                <div className="flex flex-wrap gap-1">
                  {d.tools_needed.map((tool) => (
                    <span
                      key={tool}
                      className="rounded-full px-2 py-0.5 text-[10px]"
                      style={{
                        background: "var(--surface-muted)",
                        color: "var(--text-muted)",
                      }}
                    >
                      {tool}
                    </span>
                  ))}
                </div>
                <footer className="flex flex-wrap gap-1 pt-1">
                  {d.status !== "archived" && (
                    <button
                      type="button"
                      onClick={() => {
                        setEditingId(d.id);
                        setCreating(false);
                        setOpError(null);
                      }}
                      disabled={busy}
                      data-testid="bot-builder-edit"
                      className="rounded-md px-2 py-1 text-[11px]"
                      style={{
                        background: "var(--surface-muted)",
                        color: "var(--text)",
                        border: "1px solid var(--border)",
                      }}
                    >
                      Edit
                    </button>
                  )}
                  {d.status === "draft" && (
                    <button
                      type="button"
                      onClick={() => void onRequestApproval(d)}
                      disabled={busy}
                      data-testid="bot-builder-request-approval"
                      className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px]"
                      style={{
                        background: "rgba(234,179,8,0.18)",
                        color: "#eab308",
                      }}
                    >
                      <Send className="h-3 w-3" />
                      Request approval
                    </button>
                  )}
                  {isOwner && d.status !== "archived" && d.status !== "approved" && (
                    <button
                      type="button"
                      onClick={() => void onApprove(d)}
                      disabled={busy}
                      data-testid="bot-builder-approve"
                      className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px]"
                      style={{
                        background: "rgba(34,197,94,0.18)",
                        color: "#22c55e",
                      }}
                    >
                      <CheckCircle2 className="h-3 w-3" />
                      Approve
                    </button>
                  )}
                  {d.status !== "archived" && (
                    <button
                      type="button"
                      onClick={() => void onArchive(d)}
                      disabled={busy}
                      data-testid="bot-builder-archive"
                      className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px]"
                      style={{
                        background: "var(--surface-muted)",
                        color: "var(--text-muted)",
                        border: "1px solid var(--border)",
                      }}
                    >
                      <Archive className="h-3 w-3" />
                      Archive
                    </button>
                  )}
                </footer>
              </article>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}

export default function BotBuilderPage() {
  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel
          message="Sign in to access the Bot Builder"
          forceRedirectUrl="/bots/builder"
        />
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
          <BotBuilderContent />
        </RoleGuard>
      </SignedIn>
    </DashboardShell>
  );
}

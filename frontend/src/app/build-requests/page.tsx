"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ClipboardCheck,
  ClipboardList,
  Loader2,
  Plus,
  RefreshCw,
  Send,
  ShieldCheck,
  XCircle,
} from "lucide-react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import { useRole } from "@/hooks/use-role";
import { getApiBaseUrl } from "@/lib/api-base";

// ── Types (mirrors backend BuildRequestResponse) ────────────────────────────

const REQUEST_TYPES = [
  "bot_build",
  "agent_build",
  "feature",
  "bug_fix",
  "ui_change",
  "workflow",
  "integration",
  "documentation",
  "other",
] as const;
type RequestType = (typeof REQUEST_TYPES)[number];

const PRIORITIES = ["low", "normal", "high", "urgent"] as const;
type Priority = (typeof PRIORITIES)[number];

const RISK_LEVELS = ["low", "medium", "high"] as const;
type RiskLevel = (typeof RISK_LEVELS)[number];

const STATUSES = [
  "draft",
  "submitted",
  "needs_changes",
  "approved",
  "rejected",
  "building",
  "completed",
  "cancelled",
] as const;
type BuildRequestStatus = (typeof STATUSES)[number];

interface BuildRequest {
  id: string;
  title: string;
  slug: string;
  request_type: RequestType;
  summary: string;
  description: string | null;
  business_reason: string | null;
  requested_by_user_id: string;
  requested_by_email: string | null;
  requested_by_role: string | null;
  status: BuildRequestStatus;
  priority: Priority;
  risk_level: RiskLevel;
  target_area: string | null;
  related_bot_draft_id: string | null;
  related_agent_id: string | null;
  requested_branch_name: string | null;
  approved_by_user_id: string | null;
  approved_at: string | null;
  rejected_by_user_id: string | null;
  rejected_at: string | null;
  rejection_reason: string | null;
  owner_notes: string | null;
  safe_mode_required: boolean;
  external_actions_requested: boolean;
  secrets_required: boolean;
  platforms_requested: string[] | null;
  acceptance_criteria: string[] | null;
  created_at: string;
  updated_at: string;
}

type FetchFn = (url: string, init?: RequestInit) => Promise<Response>;

// ── API helpers ─────────────────────────────────────────────────────────────

async function fetchList(fetchFn: FetchFn, status?: string): Promise<BuildRequest[]> {
  const url = new URL(`${getApiBaseUrl()}/api/v1/build-requests`);
  if (status) url.searchParams.set("status", status);
  const res = await fetchFn(url.toString());
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  // The backend returns a JSON array, but a misconfigured proxy, an HTML
  // error page slipping through `res.ok`, or a future change could produce
  // null / object / undefined. Coerce to an array so callers (`.length`,
  // `.map`, `rows[0]`) never crash on shape drift.
  const data = (await res.json()) as unknown;
  return Array.isArray(data) ? (data as BuildRequest[]) : [];
}

async function postBody<T>(
  fetchFn: FetchFn,
  path: string,
  body: unknown,
  method: "POST" | "PATCH" = "POST",
): Promise<T> {
  const res = await fetchFn(`${getApiBaseUrl()}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) {
    const detail = (await res.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(detail?.detail ?? `HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

// ── Form ────────────────────────────────────────────────────────────────────

interface FormState {
  title: string;
  slug: string;
  request_type: RequestType;
  summary: string;
  description: string;
  business_reason: string;
  priority: Priority;
  risk_level: RiskLevel;
  target_area: string;
  requested_branch_name: string;
  external_actions_requested: boolean;
  secrets_required: boolean;
  platforms_requested: string;
  acceptance_criteria: string;
}

function emptyForm(): FormState {
  return {
    title: "",
    slug: "",
    request_type: "feature",
    summary: "",
    description: "",
    business_reason: "",
    priority: "normal",
    risk_level: "low",
    target_area: "",
    requested_branch_name: "",
    external_actions_requested: false,
    secrets_required: false,
    platforms_requested: "",
    acceptance_criteria: "",
  };
}

function formFromRow(r: BuildRequest): FormState {
  return {
    title: r.title,
    slug: r.slug,
    request_type: r.request_type,
    summary: r.summary,
    description: r.description ?? "",
    business_reason: r.business_reason ?? "",
    priority: r.priority,
    risk_level: r.risk_level,
    target_area: r.target_area ?? "",
    requested_branch_name: r.requested_branch_name ?? "",
    external_actions_requested: r.external_actions_requested,
    secrets_required: r.secrets_required,
    platforms_requested: (Array.isArray(r.platforms_requested) ? r.platforms_requested : []).join(", "),
    acceptance_criteria: (Array.isArray(r.acceptance_criteria) ? r.acceptance_criteria : []).join("\n"),
  };
}

function bodyFromForm(form: FormState, includeSlug: boolean): Record<string, unknown> {
  const platforms = form.platforms_requested
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const acs = form.acceptance_criteria
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
  const body: Record<string, unknown> = {
    title: form.title.trim(),
    request_type: form.request_type,
    summary: form.summary.trim(),
    description: form.description.trim() || null,
    business_reason: form.business_reason.trim() || null,
    priority: form.priority,
    risk_level: form.risk_level,
    target_area: form.target_area.trim() || null,
    requested_branch_name: form.requested_branch_name.trim() || null,
    external_actions_requested: form.external_actions_requested,
    secrets_required: form.secrets_required,
    platforms_requested: platforms.length ? platforms : null,
    acceptance_criteria: acs.length ? acs : null,
  };
  if (includeSlug && form.slug.trim()) body.slug = form.slug.trim().toLowerCase();
  return body;
}

// ── Pills ───────────────────────────────────────────────────────────────────

const STATUS_COLOR: Record<BuildRequestStatus, { bg: string; fg: string; label: string }> = {
  draft: { bg: "rgba(107,114,128,0.15)", fg: "#9ca3af", label: "Draft" },
  submitted: { bg: "rgba(59,130,246,0.18)", fg: "#3b82f6", label: "Submitted" },
  needs_changes: { bg: "rgba(234,179,8,0.18)", fg: "#eab308", label: "Needs changes" },
  approved: { bg: "rgba(34,197,94,0.18)", fg: "#22c55e", label: "Approved" },
  rejected: { bg: "rgba(239,68,68,0.18)", fg: "#ef4444", label: "Rejected" },
  building: { bg: "rgba(168,85,247,0.18)", fg: "#c084fc", label: "Building" },
  completed: { bg: "rgba(34,197,94,0.10)", fg: "#86efac", label: "Completed" },
  cancelled: { bg: "rgba(107,114,128,0.10)", fg: "#9ca3af", label: "Cancelled" },
};

function StatusPill({ status }: { status: BuildRequestStatus }) {
  const c = STATUS_COLOR[status];
  return (
    <span
      className="rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider"
      style={{ background: c.bg, color: c.fg }}
      data-testid={`status-pill-${status}`}
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

function PriorityPill({ priority }: { priority: Priority }) {
  const colors: Record<Priority, { bg: string; fg: string }> = {
    low: { bg: "rgba(107,114,128,0.15)", fg: "#9ca3af" },
    normal: { bg: "rgba(59,130,246,0.15)", fg: "#60a5fa" },
    high: { bg: "rgba(234,179,8,0.18)", fg: "#eab308" },
    urgent: { bg: "rgba(239,68,68,0.18)", fg: "#ef4444" },
  };
  const c = colors[priority];
  return (
    <span
      className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider"
      style={{ background: c.bg, color: c.fg }}
    >
      {priority}
    </span>
  );
}

// ── Form component ─────────────────────────────────────────────────────────

function BuildRequestForm({
  initial,
  isEditing,
  busy,
  onSubmit,
  onCancel,
}: {
  initial: FormState;
  isEditing: boolean;
  busy: boolean;
  onSubmit: (body: Record<string, unknown>) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<FormState>(initial);

  useEffect(() => {
    setForm(initial);
  }, [initial]);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const inputBase =
    "w-full rounded-md px-3 py-2 text-sm focus:outline-none disabled:opacity-50";
  const inputStyle = {
    background: "var(--surface-muted)",
    border: "1px solid var(--border)",
    color: "var(--text)",
  } as const;

  const showWarning = form.external_actions_requested || form.secrets_required || form.risk_level === "high";

  return (
    <form
      data-testid="build-request-form"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(bodyFromForm(form, !isEditing));
      }}
      className="rounded-xl p-4 space-y-3"
      style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="text-xs space-y-1">
          <span style={{ color: "var(--text-quiet)" }}>Title</span>
          <input
            type="text"
            value={form.title}
            disabled={busy}
            onChange={(e) => update("title", e.target.value)}
            className={inputBase}
            style={inputStyle}
            data-testid="br-title"
            required
          />
        </label>
        <label className="text-xs space-y-1">
          <span style={{ color: "var(--text-quiet)" }}>Slug (optional)</span>
          <input
            type="text"
            value={form.slug}
            disabled={isEditing || busy}
            onChange={(e) => update("slug", e.target.value)}
            className={inputBase}
            style={inputStyle}
            placeholder="auto-derived from title"
          />
        </label>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="text-xs space-y-1">
          <span style={{ color: "var(--text-quiet)" }}>Request type</span>
          <select
            value={form.request_type}
            disabled={busy}
            onChange={(e) => update("request_type", e.target.value as RequestType)}
            className={inputBase}
            style={inputStyle}
            data-testid="br-type"
          >
            {REQUEST_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs space-y-1">
          <span style={{ color: "var(--text-quiet)" }}>Priority</span>
          <select
            value={form.priority}
            disabled={busy}
            onChange={(e) => update("priority", e.target.value as Priority)}
            className={inputBase}
            style={inputStyle}
          >
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
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
        <span style={{ color: "var(--text-quiet)" }}>Summary (1-2 sentences)</span>
        <input
          type="text"
          value={form.summary}
          disabled={busy}
          onChange={(e) => update("summary", e.target.value)}
          className={inputBase}
          style={inputStyle}
          required
        />
      </label>

      <label className="text-xs space-y-1 block">
        <span style={{ color: "var(--text-quiet)" }}>Target area</span>
        <input
          type="text"
          value={form.target_area}
          disabled={busy}
          onChange={(e) => update("target_area", e.target.value)}
          className={inputBase}
          style={inputStyle}
          placeholder="bots/rt-bot, frontend/sidebar, …"
        />
      </label>

      <label className="text-xs space-y-1 block">
        <span style={{ color: "var(--text-quiet)" }}>Description</span>
        <textarea
          value={form.description}
          disabled={busy}
          onChange={(e) => update("description", e.target.value)}
          className={inputBase}
          style={inputStyle}
          rows={4}
        />
      </label>

      <label className="text-xs space-y-1 block">
        <span style={{ color: "var(--text-quiet)" }}>Business reason</span>
        <textarea
          value={form.business_reason}
          disabled={busy}
          onChange={(e) => update("business_reason", e.target.value)}
          className={inputBase}
          style={inputStyle}
          rows={2}
        />
      </label>

      <label className="text-xs space-y-1 block">
        <span style={{ color: "var(--text-quiet)" }}>
          Acceptance criteria (one per line)
        </span>
        <textarea
          value={form.acceptance_criteria}
          disabled={busy}
          onChange={(e) => update("acceptance_criteria", e.target.value)}
          className={inputBase}
          style={inputStyle}
          rows={3}
        />
      </label>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="text-xs space-y-1">
          <span style={{ color: "var(--text-quiet)" }}>
            Platforms requested (comma-sep)
          </span>
          <input
            type="text"
            value={form.platforms_requested}
            disabled={busy}
            onChange={(e) => update("platforms_requested", e.target.value)}
            className={inputBase}
            style={inputStyle}
            placeholder="X, Telegram, Discord"
          />
        </label>
        <label className="text-xs space-y-1">
          <span style={{ color: "var(--text-quiet)" }}>
            Suggested branch name (metadata only)
          </span>
          <input
            type="text"
            value={form.requested_branch_name}
            disabled={busy}
            onChange={(e) => update("requested_branch_name", e.target.value)}
            className={inputBase}
            style={inputStyle}
            placeholder="feat/example-thing"
          />
        </label>
      </div>

      <div className="flex flex-wrap gap-4 pt-1">
        <label className="inline-flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={form.external_actions_requested}
            disabled={busy}
            onChange={(e) => update("external_actions_requested", e.target.checked)}
            data-testid="br-external"
          />
          <span style={{ color: "var(--text-muted)" }}>
            External actions requested
          </span>
        </label>
        <label className="inline-flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={form.secrets_required}
            disabled={busy}
            onChange={(e) => update("secrets_required", e.target.checked)}
            data-testid="br-secrets"
          />
          <span style={{ color: "var(--text-muted)" }}>Secrets required</span>
        </label>
      </div>

      {showWarning && (
        <div
          data-testid="br-warning"
          className="rounded-lg px-3 py-2 text-xs flex items-start gap-2"
          style={{
            background: "rgba(234,179,8,0.10)",
            color: "#eab308",
            border: "1px solid rgba(234,179,8,0.25)",
          }}
        >
          <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
          <span>
            This request needs owner approval and a careful review before any
            work starts.  Operators may submit it; only the owner can approve.
          </span>
        </div>
      )}

      <div className="flex items-center gap-2 pt-1">
        <button
          type="submit"
          disabled={busy}
          data-testid="br-save"
          className="inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50"
          style={{ background: "var(--accent)", color: "#fff" }}
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
          {isEditing ? "Save changes" : "Create request"}
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
          Build requests do not run code or deploy.  Owner approval is required.
        </p>
      </div>
    </form>
  );
}

// ── Detail panel ───────────────────────────────────────────────────────────

function DetailPanel({
  row,
  isOwner,
  isAuthor,
  busy,
  onEdit,
  onSubmit,
  onApprove,
  onReject,
  onRequestChanges,
  onCancel,
  onMarkBuilding,
  onMarkCompleted,
  onClose,
}: {
  row: BuildRequest;
  isOwner: boolean;
  isAuthor: boolean;
  busy: boolean;
  onEdit: () => void;
  onSubmit: () => void;
  onApprove: (notes: string) => void;
  onReject: (reason: string) => void;
  onRequestChanges: (notes: string) => void;
  onCancel: (notes: string) => void;
  onMarkBuilding: () => void;
  onMarkCompleted: () => void;
  onClose: () => void;
}) {
  const [reason, setReason] = useState("");
  const [notes, setNotes] = useState("");
  const editable =
    (isOwner && !["rejected", "cancelled", "completed"].includes(row.status)) ||
    (isAuthor && (row.status === "draft" || row.status === "needs_changes"));
  const canSubmit = (isOwner || isAuthor) && (row.status === "draft" || row.status === "needs_changes");
  const canCancel =
    (isAuthor && (row.status === "draft" || row.status === "submitted" || row.status === "needs_changes")) ||
    (isOwner && !["rejected", "cancelled", "completed"].includes(row.status));
  const canApprove = isOwner && (row.status === "submitted" || row.status === "needs_changes");
  const canReject = isOwner && (row.status === "submitted" || row.status === "needs_changes");
  const canRequestChanges = isOwner && row.status === "submitted";
  const canMarkBuilding = isOwner && row.status === "approved";
  const canMarkCompleted = isOwner && (row.status === "building" || row.status === "approved");

  return (
    <article
      data-testid="br-detail"
      className="rounded-xl p-5 space-y-4"
      style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}
    >
      <header className="flex items-start gap-3">
        <button
          type="button"
          onClick={onClose}
          className="rounded-md p-1 text-xs"
          style={{ color: "var(--text-muted)" }}
          aria-label="Close detail"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <div className="flex-1 space-y-1">
          <p className="text-base font-semibold" style={{ color: "var(--text)" }}>
            {row.title}
          </p>
          <p className="text-[11px] font-mono" style={{ color: "var(--text-quiet)" }}>
            {row.slug} · {row.request_type}
          </p>
          <div className="flex flex-wrap gap-1.5 pt-1">
            <StatusPill status={row.status} />
            <PriorityPill priority={row.priority} />
            <RiskBadge risk={row.risk_level} />
            {row.safe_mode_required && (
              <span
                className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider"
                style={{ background: "rgba(168,85,247,0.10)", color: "#c084fc" }}
              >
                safe-mode
              </span>
            )}
            {row.external_actions_requested && (
              <span
                className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider"
                style={{ background: "rgba(234,179,8,0.18)", color: "#eab308" }}
              >
                external actions
              </span>
            )}
            {row.secrets_required && (
              <span
                className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider"
                style={{ background: "rgba(239,68,68,0.18)", color: "#ef4444" }}
              >
                secrets needed
              </span>
            )}
          </div>
        </div>
      </header>

      <p className="text-sm" style={{ color: "var(--text-muted)" }}>
        {row.summary}
      </p>

      {row.description && (
        <section className="space-y-1">
          <p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-quiet)" }}>
            Description
          </p>
          <p className="text-sm whitespace-pre-wrap" style={{ color: "var(--text-muted)" }}>
            {row.description}
          </p>
        </section>
      )}

      {row.business_reason && (
        <section className="space-y-1">
          <p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-quiet)" }}>
            Business reason
          </p>
          <p className="text-sm whitespace-pre-wrap" style={{ color: "var(--text-muted)" }}>
            {row.business_reason}
          </p>
        </section>
      )}

      {Array.isArray(row.acceptance_criteria) && row.acceptance_criteria.length > 0 && (
        <section className="space-y-1">
          <p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-quiet)" }}>
            Acceptance criteria
          </p>
          <ul className="list-disc pl-5 space-y-0.5 text-sm" style={{ color: "var(--text-muted)" }}>
            {row.acceptance_criteria.map((ac, i) => (
              <li key={i}>{ac}</li>
            ))}
          </ul>
        </section>
      )}

      {Array.isArray(row.platforms_requested) && row.platforms_requested.length > 0 && (
        <section className="flex flex-wrap gap-1.5">
          {row.platforms_requested.map((p) => (
            <span
              key={p}
              className="rounded-full px-2 py-0.5 text-[10px]"
              style={{ background: "var(--surface-muted)", color: "var(--text-muted)" }}
            >
              {p}
            </span>
          ))}
        </section>
      )}

      {row.requested_branch_name && (
        <p className="text-[11px]" style={{ color: "var(--text-quiet)" }}>
          Suggested branch: <code>{row.requested_branch_name}</code> (metadata only,
          no branch is created in v1)
        </p>
      )}

      {row.owner_notes && (
        <section
          className="rounded-lg px-3 py-2 text-sm space-y-1"
          style={{ background: "rgba(59,130,246,0.10)", border: "1px solid rgba(59,130,246,0.25)" }}
        >
          <p className="text-[10px] uppercase tracking-wider" style={{ color: "#60a5fa" }}>
            Owner notes
          </p>
          <p style={{ color: "var(--text-muted)" }}>{row.owner_notes}</p>
        </section>
      )}

      {row.rejection_reason && (
        <section
          className="rounded-lg px-3 py-2 text-sm space-y-1"
          style={{ background: "rgba(239,68,68,0.10)", border: "1px solid rgba(239,68,68,0.25)" }}
        >
          <p className="text-[10px] uppercase tracking-wider" style={{ color: "#ef4444" }}>
            Rejection reason
          </p>
          <p style={{ color: "var(--text-muted)" }}>{row.rejection_reason}</p>
        </section>
      )}

      <p className="text-[11px]" style={{ color: "var(--text-quiet)" }}>
        Requested by {row.requested_by_email ?? row.requested_by_user_id} (
        {row.requested_by_role ?? "?"})
      </p>

      {/* ── Action zone ── */}
      <div className="flex flex-wrap gap-1.5 pt-1">
        {editable && (
          <button
            type="button"
            onClick={onEdit}
            disabled={busy}
            data-testid="br-edit"
            className="rounded-md px-2.5 py-1 text-xs"
            style={{
              background: "var(--surface-muted)",
              color: "var(--text)",
              border: "1px solid var(--border)",
            }}
          >
            Edit
          </button>
        )}
        {canSubmit && (
          <button
            type="button"
            onClick={onSubmit}
            disabled={busy}
            data-testid="br-submit"
            className="inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs"
            style={{ background: "rgba(59,130,246,0.18)", color: "#3b82f6" }}
          >
            <Send className="h-3 w-3" />
            Submit for approval
          </button>
        )}
        {canCancel && (
          <button
            type="button"
            onClick={() => onCancel(notes)}
            disabled={busy}
            data-testid="br-cancel-action"
            className="rounded-md px-2.5 py-1 text-xs"
            style={{
              background: "var(--surface-muted)",
              color: "var(--text-muted)",
              border: "1px solid var(--border)",
            }}
          >
            Cancel request
          </button>
        )}
        {canMarkBuilding && (
          <button
            type="button"
            onClick={onMarkBuilding}
            disabled={busy}
            data-testid="br-mark-building"
            className="rounded-md px-2.5 py-1 text-xs"
            style={{ background: "rgba(168,85,247,0.18)", color: "#c084fc" }}
          >
            Mark building
          </button>
        )}
        {canMarkCompleted && (
          <button
            type="button"
            onClick={onMarkCompleted}
            disabled={busy}
            data-testid="br-mark-completed"
            className="rounded-md px-2.5 py-1 text-xs"
            style={{ background: "rgba(34,197,94,0.18)", color: "#22c55e" }}
          >
            Mark completed
          </button>
        )}
      </div>

      {/* ── Owner-only approval controls ── */}
      {(canApprove || canReject || canRequestChanges) && (
        <div
          data-testid="br-owner-controls"
          className="rounded-lg p-3 space-y-2"
          style={{ background: "var(--surface-muted)", border: "1px solid var(--border)" }}
        >
          <p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-quiet)" }}>
            Owner approval
          </p>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Notes (used for approve / request-changes)"
            rows={2}
            className="w-full rounded-md px-3 py-2 text-sm"
            style={{
              background: "var(--surface)",
              border: "1px solid var(--border)",
              color: "var(--text)",
            }}
          />
          <div className="flex flex-wrap gap-1.5">
            {canApprove && (
              <button
                type="button"
                onClick={() => onApprove(notes)}
                disabled={busy}
                data-testid="br-approve"
                className="inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs"
                style={{ background: "rgba(34,197,94,0.18)", color: "#22c55e" }}
              >
                <CheckCircle2 className="h-3 w-3" />
                Approve
              </button>
            )}
            {canRequestChanges && (
              <button
                type="button"
                onClick={() => onRequestChanges(notes)}
                disabled={busy || !notes.trim()}
                data-testid="br-request-changes"
                className="inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs"
                style={{ background: "rgba(234,179,8,0.18)", color: "#eab308" }}
              >
                Request changes
              </button>
            )}
          </div>
          {canReject && (
            <div className="space-y-1 pt-1">
              <textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Reason for rejection (required)"
                rows={2}
                className="w-full rounded-md px-3 py-2 text-sm"
                style={{
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  color: "var(--text)",
                }}
              />
              <button
                type="button"
                onClick={() => onReject(reason)}
                disabled={busy || !reason.trim()}
                data-testid="br-reject"
                className="inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs"
                style={{ background: "rgba(239,68,68,0.18)", color: "#ef4444" }}
              >
                <XCircle className="h-3 w-3" />
                Reject
              </button>
            </div>
          )}
        </div>
      )}
    </article>
  );
}

// ── Page ────────────────────────────────────────────────────────────────────

function BuildRequestsContent() {
  const { fetchWithAuth } = useAuthFetch();
  const { realRole } = useRole();
  const isOwner = realRole === "owner";

  const [rows, setRows] = useState<BuildRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [opError, setOpError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await fetchList(fetchWithAuth, statusFilter || undefined);
      setRows(data);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Failed to load build requests.");
    } finally {
      setLoading(false);
    }
  }, [fetchWithAuth, statusFilter]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const selected = useMemo(
    () => rows.find((r) => r.id === selectedId) ?? null,
    [rows, selectedId],
  );
  const editing = useMemo(
    () => rows.find((r) => r.id === editingId) ?? null,
    [rows, editingId],
  );

  const guardedActorId = (row: BuildRequest) =>
    row.requested_by_email ?? row.requested_by_user_id;

  const handleCreate = async (body: Record<string, unknown>) => {
    setBusy(true);
    setOpError(null);
    try {
      const created = await postBody<BuildRequest>(
        fetchWithAuth,
        `/api/v1/build-requests`,
        body,
        "POST",
      );
      setRows((prev) => [created, ...prev]);
      setCreating(false);
      setSelectedId(created.id);
    } catch (e) {
      setOpError(e instanceof Error ? e.message : "Failed to create request.");
    } finally {
      setBusy(false);
    }
  };

  const handleUpdate = async (body: Record<string, unknown>) => {
    if (!editingId) return;
    setBusy(true);
    setOpError(null);
    try {
      const updated = await postBody<BuildRequest>(
        fetchWithAuth,
        `/api/v1/build-requests/${editingId}`,
        body,
        "PATCH",
      );
      setRows((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
      setEditingId(null);
    } catch (e) {
      setOpError(e instanceof Error ? e.message : "Failed to update request.");
    } finally {
      setBusy(false);
    }
  };

  const runAction = async (
    id: string,
    path: string,
    body: unknown = {},
  ): Promise<void> => {
    setBusy(true);
    setOpError(null);
    try {
      const updated = await postBody<BuildRequest>(
        fetchWithAuth,
        `/api/v1/build-requests/${id}/${path}`,
        body,
      );
      setRows((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
    } catch (e) {
      setOpError(e instanceof Error ? e.message : `Failed: ${path}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex-1 overflow-y-auto" style={{ background: "var(--bg)" }}>
      <div className="max-w-4xl mx-auto px-6 py-8 space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1
              className="flex items-center gap-2 text-xl font-semibold"
              style={{ color: "var(--text)" }}
            >
              <ClipboardCheck className="h-5 w-5" aria-hidden="true" />
              Build Requests
            </h1>
            <p className="mt-1 text-sm" style={{ color: "var(--text-muted)" }}>
              Submit and track structured change requests.  Owner approval is
              required before any work begins.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="rounded-lg px-3 py-1.5 text-xs"
              style={{
                background: "var(--surface-strong)",
                border: "1px solid var(--border)",
                color: "var(--text-muted)",
              }}
              data-testid="br-status-filter"
            >
              <option value="">All statuses</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {STATUS_COLOR[s].label}
                </option>
              ))}
            </select>
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
                setSelectedId(null);
                setOpError(null);
              }}
              disabled={busy}
              data-testid="br-new"
              className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-medium text-white"
              style={{ background: "var(--accent)" }}
            >
              <Plus className="h-3.5 w-3.5" />
              New build request
            </button>
          </div>
        </div>

        <div
          data-testid="br-safety-banner"
          className="rounded-xl px-4 py-3 text-xs space-y-1"
          style={{
            background: "rgba(168,85,247,0.08)",
            border: "1px solid rgba(168,85,247,0.2)",
            color: "var(--text-muted)",
          }}
        >
          <p className="flex items-center gap-1.5 font-medium" style={{ color: "var(--text)" }}>
            <ShieldCheck className="h-3.5 w-3.5" />
            Build requests do not run code or deploy. Owner approval is required.
          </p>
          <p>
            v1 is intake + approval only.  No git or gh commands run.  No
            branches are created.  No deploys are triggered.  Operators may
            submit and edit their own drafts; owners review, approve, reject,
            or send back for changes.
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
            data-testid="br-error"
          >
            <AlertTriangle className="inline h-3.5 w-3.5 mr-1" />
            {opError}
          </div>
        )}

        {creating && (
          <BuildRequestForm
            initial={emptyForm()}
            isEditing={false}
            busy={busy}
            onSubmit={(body) => void handleCreate(body)}
            onCancel={() => setCreating(false)}
          />
        )}

        {editing && (
          <BuildRequestForm
            initial={formFromRow(editing)}
            isEditing
            busy={busy}
            onSubmit={(body) => void handleUpdate(body)}
            onCancel={() => setEditingId(null)}
          />
        )}

        {selected && !editing && (
          <DetailPanel
            row={selected}
            isOwner={isOwner}
            isAuthor={selected.requested_by_user_id !== ""}
            busy={busy}
            onEdit={() => {
              setEditingId(selected.id);
              setSelectedId(null);
            }}
            onClose={() => setSelectedId(null)}
            onSubmit={() => void runAction(selected.id, "submit")}
            onApprove={(notes) =>
              void runAction(selected.id, "approve", notes ? { notes } : {})
            }
            onReject={(reason) => void runAction(selected.id, "reject", { reason })}
            onRequestChanges={(notes) =>
              void runAction(selected.id, "request-changes", { notes })
            }
            onCancel={(notes) =>
              void runAction(selected.id, "cancel", notes ? { notes } : {})
            }
            onMarkBuilding={() => void runAction(selected.id, "mark-building")}
            onMarkCompleted={() => void runAction(selected.id, "mark-completed")}
          />
        )}

        {loading ? (
          <p className="text-sm" style={{ color: "var(--text-quiet)" }}>
            Loading build requests…
          </p>
        ) : rows.length === 0 ? (
          <div
            className="rounded-xl px-4 py-6 text-center text-sm space-y-2"
            style={{
              background: "var(--surface-strong)",
              border: "1px dashed var(--border)",
              color: "var(--text-quiet)",
            }}
            data-testid="br-empty"
          >
            <ClipboardList className="mx-auto h-6 w-6" aria-hidden="true" />
            <p>
              No build requests yet.  Click <strong>New build request</strong> to
              propose a change.
            </p>
          </div>
        ) : (
          <div className="space-y-3" data-testid="br-list">
            {rows.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => {
                  setSelectedId(r.id);
                  setEditingId(null);
                  setCreating(false);
                }}
                data-testid="br-row"
                className="w-full text-left rounded-xl px-4 py-3 space-y-1.5 transition-colors"
                style={{
                  background: "var(--surface-strong)",
                  border: "1px solid var(--border)",
                  opacity:
                    r.status === "rejected" || r.status === "cancelled" ? 0.65 : 1,
                }}
              >
                <header className="flex flex-wrap items-center gap-2">
                  <p className="text-sm font-medium" style={{ color: "var(--text)" }}>
                    {r.title}
                  </p>
                  <span
                    className="text-[10px] font-mono uppercase"
                    style={{ color: "var(--text-quiet)" }}
                  >
                    {r.slug}
                  </span>
                  <StatusPill status={r.status} />
                  <PriorityPill priority={r.priority} />
                  <RiskBadge risk={r.risk_level} />
                  {r.external_actions_requested && (
                    <span
                      className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider"
                      style={{ background: "rgba(234,179,8,0.18)", color: "#eab308" }}
                      title="External actions requested"
                    >
                      ext
                    </span>
                  )}
                  {r.secrets_required && (
                    <span
                      className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider"
                      style={{ background: "rgba(239,68,68,0.18)", color: "#ef4444" }}
                      title="Secrets required"
                    >
                      secrets
                    </span>
                  )}
                </header>
                <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                  {r.summary}
                </p>
                <p className="text-[10px]" style={{ color: "var(--text-quiet)" }}>
                  by {guardedActorId(r)}
                </p>
              </button>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}

export default function BuildRequestsPage() {
  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel
          message="Sign in to access Build Requests"
          forceRedirectUrl="/build-requests"
        />
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <RoleGuard
          require="builder"
          denied={
            <main
              className="flex-1 flex items-center justify-center"
              style={{ background: "var(--bg)" }}
            >
              <p className="text-sm" style={{ color: "var(--text-quiet)" }}>
                You need at least builder access to view Build Requests.
              </p>
            </main>
          }
        >
          <BuildRequestsContent />
        </RoleGuard>
      </SignedIn>
    </DashboardShell>
  );
}

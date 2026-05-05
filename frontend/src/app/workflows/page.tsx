"use client";

export const dynamic = "force-dynamic";

import { useState, useEffect, useCallback } from "react";
import {
  Activity,
  Play,
  Zap,
  AlertCircle,
  CheckCircle2,
  Loader2,
  RefreshCw,
  ChevronDown,
  ChevronRight,
  Plus,
  X,
  Clock,
  ToggleLeft,
  ToggleRight,
  Trash2,
} from "lucide-react";

import { useAuth } from "@/auth/clerk";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";
import { useOrganizationMembership } from "@/lib/use-organization-membership";
import { logSystemAction } from "@/lib/action-logger";

// ── Types ─────────────────────────────────────────────────────────────────────

interface HealthCheck {
  name: string;
  status: "pass" | "fail" | "warn";
  message?: string;
  latency_ms?: number;
}

interface HealthReport {
  status: "healthy" | "degraded" | "down";
  checks: HealthCheck[];
  pass: number;
  fail: number;
  warn?: number;
  timestamp?: string;
}

interface DeployResult {
  success: boolean;
  deploy_id?: string;
  message?: string;
  error?: string;
}

interface ErrorItem {
  level: "error" | "warning";
  message: string;
  suggestion?: string;
}

interface ErrorReport {
  errors: ErrorItem[];
  warnings: ErrorItem[];
  suggestions: string[];
  timestamp?: string;
}

type WorkflowTrigger = "manual" | "scheduled";
type WorkflowRunStatus = "success" | "error" | "running" | null;

interface SavedWorkflow {
  id: string;
  name: string;
  description: string;
  trigger: WorkflowTrigger;
  lastRunAt: string | null;
  lastRunStatus: WorkflowRunStatus;
  createdAt: string;
  enabled: boolean;
}

// ── LocalStorage helpers ──────────────────────────────────────────────────────

const LS_KEY = "mc_workflows_v1";

function loadWorkflows(): SavedWorkflow[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(LS_KEY);
    return raw ? (JSON.parse(raw) as SavedWorkflow[]) : [];
  } catch {
    return [];
  }
}

function saveWorkflows(workflows: SavedWorkflow[]): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(LS_KEY, JSON.stringify(workflows));
}

// ── Status badge helpers ──────────────────────────────────────────────────────

function HealthStatusBadge({ status }: { status: "healthy" | "degraded" | "down" }) {
  const colors = {
    healthy: "bg-green-500/15 text-green-400 border border-green-500/30",
    degraded: "bg-amber-500/15 text-amber-400 border border-amber-500/30",
    down: "bg-red-500/15 text-red-400 border border-red-500/30",
  };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${colors[status]}`}>
      {status === "healthy" ? (
        <CheckCircle2 className="h-3 w-3" />
      ) : (
        <AlertCircle className="h-3 w-3" />
      )}
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

function CheckStatusDot({ status }: { status: "pass" | "fail" | "warn" }) {
  const colors = {
    pass: "bg-green-400",
    fail: "bg-red-400",
    warn: "bg-amber-400",
  };
  return <span className={`inline-block h-2 w-2 rounded-full ${colors[status]}`} />;
}

function RunStatusBadge({ status }: { status: WorkflowRunStatus }) {
  if (!status) return <span className="text-xs" style={{ color: "var(--text-quiet)" }}>Never run</span>;
  const configs = {
    success: { cls: "bg-green-500/15 text-green-400 border border-green-500/30", label: "Success" },
    error: { cls: "bg-red-500/15 text-red-400 border border-red-500/30", label: "Error" },
    running: { cls: "bg-blue-500/15 text-blue-400 border border-blue-500/30", label: "Running" },
  };
  const { cls, label } = configs[status];
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {label}
    </span>
  );
}

// ── Health Check Card ─────────────────────────────────────────────────────────

function HealthCheckCard({ getToken }: { getToken: () => Promise<string | null> }) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<HealthReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      logSystemAction("deploy", "Health check triggered");
      const token = await getToken();
      const res = await fetch("/api/v1/workflows/health-check", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.detail ?? `HTTP ${res.status}`);
      }
      const data = (await res.json()) as HealthReport;
      setResult(data);
      logSystemAction(
        data.status === "healthy" ? "deploy" : "error",
        `Health check completed: ${data.status}`,
        `${data.pass} pass, ${data.fail} fail`,
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setError(msg);
      logSystemAction("error", "Health check failed", msg);
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  return (
    <div
      className="rounded-xl border p-5 flex flex-col gap-4"
      style={{
        background: "var(--surface)",
        borderColor: "var(--border)",
        boxShadow: "var(--shadow-card)",
      }}
    >
      <div className="flex items-start gap-3">
        <div
          className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg"
          style={{ background: "var(--accent-soft)" }}
        >
          <Activity className="h-4 w-4" style={{ color: "var(--accent-strong)" }} />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-sm" style={{ color: "var(--text)" }}>
            Health Check
          </h3>
          <p className="text-xs mt-0.5 leading-relaxed" style={{ color: "var(--text-muted)" }}>
            Run a full system health check across backend, CORS, auth, and frontend endpoints
          </p>
        </div>
        <button
          onClick={run}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50"
          style={{
            background: "var(--accent-soft)",
            color: "var(--accent-strong)",
            border: "1px solid rgba(59,130,246,0.3)",
          }}
        >
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
          {loading ? "Running…" : "Run Check"}
        </button>
      </div>

      {error && (
        <div
          className="rounded-lg px-3 py-2 text-xs flex items-start gap-2"
          style={{ background: "rgba(239,68,68,0.1)", color: "#f87171", border: "1px solid rgba(239,68,68,0.25)" }}
        >
          <AlertCircle className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" />
          {error}
        </div>
      )}

      {result && (
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <HealthStatusBadge status={result.status} />
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                {result.pass} pass · {result.fail} fail{result.warn ? ` · ${result.warn} warn` : ""}
              </span>
            </div>
            <button
              onClick={() => setExpanded((v) => !v)}
              className="flex items-center gap-1 text-xs transition-colors"
              style={{ color: "var(--text-muted)" }}
            >
              {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
              {expanded ? "Hide" : "Show"} checks
            </button>
          </div>

          {expanded && result.checks.length > 0 && (
            <div
              className="rounded-lg divide-y overflow-hidden"
              style={{ borderColor: "var(--border)", border: "1px solid var(--border)" }}
            >
              {result.checks.map((check, i) => (
                <div
                  key={i}
                  className="flex items-center gap-2.5 px-3 py-2"
                  style={{ background: "var(--surface-muted)" }}
                >
                  <CheckStatusDot status={check.status} />
                  <span className="text-xs flex-1 min-w-0" style={{ color: "var(--text)" }}>
                    {check.name}
                  </span>
                  {check.latency_ms !== undefined && (
                    <span className="text-xs" style={{ color: "var(--text-quiet)" }}>
                      {check.latency_ms}ms
                    </span>
                  )}
                  {check.message && (
                    <span className="text-xs truncate max-w-[200px]" style={{ color: "var(--text-muted)" }}>
                      {check.message}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Deploy Card ───────────────────────────────────────────────────────────────

function DeployCard({ getToken }: { getToken: () => Promise<string | null> }) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<DeployResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      logSystemAction("deploy", "Render redeploy triggered");
      const token = await getToken();
      const res = await fetch("/api/v1/workflows/deploy", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ clear_cache: false, message: "" }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.detail ?? `HTTP ${res.status}`);
      }
      const data = (await res.json()) as DeployResult;
      setResult(data);
      logSystemAction(
        data.success ? "deploy" : "error",
        data.success ? "Render redeploy initiated" : "Render redeploy failed",
        data.deploy_id ?? data.error ?? data.message,
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setError(msg);
      logSystemAction("error", "Deploy workflow failed", msg);
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  return (
    <div
      className="rounded-xl border p-5 flex flex-col gap-4"
      style={{
        background: "var(--surface)",
        borderColor: "var(--border)",
        boxShadow: "var(--shadow-card)",
      }}
    >
      <div className="flex items-start gap-3">
        <div
          className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg"
          style={{ background: "rgba(139,92,246,0.15)" }}
        >
          <Play className="h-4 w-4" style={{ color: "#a78bfa" }} />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-sm" style={{ color: "var(--text)" }}>
            Deploy
          </h3>
          <p className="text-xs mt-0.5 leading-relaxed" style={{ color: "var(--text-muted)" }}>
            Trigger a Render redeploy of the backend service
          </p>
        </div>
        <button
          onClick={run}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50"
          style={{
            background: "rgba(139,92,246,0.15)",
            color: "#a78bfa",
            border: "1px solid rgba(139,92,246,0.3)",
          }}
        >
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
          {loading ? "Deploying…" : "Deploy"}
        </button>
      </div>

      {error && (
        <div
          className="rounded-lg px-3 py-2 text-xs flex items-start gap-2"
          style={{ background: "rgba(239,68,68,0.1)", color: "#f87171", border: "1px solid rgba(239,68,68,0.25)" }}
        >
          <AlertCircle className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" />
          {error}
        </div>
      )}

      {result && (
        <div
          className="rounded-lg px-3 py-2.5 flex flex-col gap-1"
          style={{
            background: result.success ? "rgba(34,197,94,0.08)" : "rgba(239,68,68,0.08)",
            border: `1px solid ${result.success ? "rgba(34,197,94,0.25)" : "rgba(239,68,68,0.25)"}`,
          }}
        >
          <div className="flex items-center gap-1.5">
            {result.success ? (
              <CheckCircle2 className="h-3.5 w-3.5 text-green-400" />
            ) : (
              <AlertCircle className="h-3.5 w-3.5 text-red-400" />
            )}
            <span className="text-xs font-medium" style={{ color: result.success ? "#4ade80" : "#f87171" }}>
              {result.success ? "Deploy triggered successfully" : "Deploy failed"}
            </span>
          </div>
          {result.deploy_id && (
            <p className="text-xs pl-5" style={{ color: "var(--text-muted)" }}>
              Deploy ID: <code className="font-mono">{result.deploy_id}</code>
            </p>
          )}
          {(result.error || result.message) && (
            <p className="text-xs pl-5" style={{ color: "var(--text-muted)" }}>
              {result.error ?? result.message}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Error Detect Card ─────────────────────────────────────────────────────────

function ErrorDetectCard({ getToken }: { getToken: () => Promise<string | null> }) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ErrorReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      logSystemAction("error", "Error detection scan triggered");
      const token = await getToken();
      const res = await fetch("/api/v1/workflows/error-detect", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.detail ?? `HTTP ${res.status}`);
      }
      const data = (await res.json()) as ErrorReport;
      setResult(data);
      logSystemAction(
        data.errors.length > 0 ? "error" : "deploy",
        "Error detection scan completed",
        `${data.errors.length} errors, ${data.warnings.length} warnings`,
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setError(msg);
      logSystemAction("error", "Error detect workflow failed", msg);
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  const totalIssues = result ? result.errors.length + result.warnings.length : 0;

  return (
    <div
      className="rounded-xl border p-5 flex flex-col gap-4"
      style={{
        background: "var(--surface)",
        borderColor: "var(--border)",
        boxShadow: "var(--shadow-card)",
      }}
    >
      <div className="flex items-start gap-3">
        <div
          className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg"
          style={{ background: "rgba(245,158,11,0.15)" }}
        >
          <Zap className="h-4 w-4" style={{ color: "#fbbf24" }} />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-sm" style={{ color: "var(--text)" }}>
            Error Detect
          </h3>
          <p className="text-xs mt-0.5 leading-relaxed" style={{ color: "var(--text-muted)" }}>
            Scan for system errors and get fix suggestions
          </p>
        </div>
        <button
          onClick={run}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50"
          style={{
            background: "rgba(245,158,11,0.15)",
            color: "#fbbf24",
            border: "1px solid rgba(245,158,11,0.3)",
          }}
        >
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Zap className="h-3 w-3" />}
          {loading ? "Scanning…" : "Scan"}
        </button>
      </div>

      {error && (
        <div
          className="rounded-lg px-3 py-2 text-xs flex items-start gap-2"
          style={{ background: "rgba(239,68,68,0.1)", color: "#f87171", border: "1px solid rgba(239,68,68,0.25)" }}
        >
          <AlertCircle className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" />
          {error}
        </div>
      )}

      {result && (
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {totalIssues === 0 ? (
                <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium bg-green-500/15 text-green-400 border border-green-500/30">
                  <CheckCircle2 className="h-3 w-3" /> Clean
                </span>
              ) : (
                <>
                  {result.errors.length > 0 && (
                    <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium bg-red-500/15 text-red-400 border border-red-500/30">
                      {result.errors.length} error{result.errors.length !== 1 ? "s" : ""}
                    </span>
                  )}
                  {result.warnings.length > 0 && (
                    <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium bg-amber-500/15 text-amber-400 border border-amber-500/30">
                      {result.warnings.length} warning{result.warnings.length !== 1 ? "s" : ""}
                    </span>
                  )}
                </>
              )}
            </div>
            {totalIssues > 0 && (
              <button
                onClick={() => setExpanded((v) => !v)}
                className="flex items-center gap-1 text-xs transition-colors"
                style={{ color: "var(--text-muted)" }}
              >
                {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                {expanded ? "Hide" : "Show"} details
              </button>
            )}
          </div>

          {expanded && (
            <div className="flex flex-col gap-2">
              {[...result.errors, ...result.warnings].map((item, i) => (
                <div
                  key={i}
                  className="rounded-lg px-3 py-2 flex flex-col gap-0.5"
                  style={{
                    background: item.level === "error" ? "rgba(239,68,68,0.08)" : "rgba(245,158,11,0.08)",
                    border: `1px solid ${item.level === "error" ? "rgba(239,68,68,0.2)" : "rgba(245,158,11,0.2)"}`,
                  }}
                >
                  <p className="text-xs font-medium" style={{ color: item.level === "error" ? "#f87171" : "#fbbf24" }}>
                    {item.message}
                  </p>
                  {item.suggestion && (
                    <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                      Fix: {item.suggestion}
                    </p>
                  )}
                </div>
              ))}
              {result.suggestions.length > 0 && (
                <div
                  className="rounded-lg px-3 py-2 flex flex-col gap-1"
                  style={{ background: "var(--surface-muted)", border: "1px solid var(--border)" }}
                >
                  <p className="text-xs font-medium" style={{ color: "var(--text)" }}>Suggestions</p>
                  <ul className="flex flex-col gap-0.5">
                    {result.suggestions.map((s, i) => (
                      <li key={i} className="text-xs" style={{ color: "var(--text-muted)" }}>
                        • {s}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── New Workflow Dialog ────────────────────────────────────────────────────────

interface NewWorkflowDialogProps {
  open: boolean;
  onClose: () => void;
  onCreate: (wf: Omit<SavedWorkflow, "id" | "createdAt" | "lastRunAt" | "lastRunStatus">) => void;
}

function NewWorkflowDialog({ open, onClose, onCreate }: NewWorkflowDialogProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [trigger, setTrigger] = useState<WorkflowTrigger>("manual");

  const reset = () => {
    setName("");
    setDescription("");
    setTrigger("manual");
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    onCreate({ name: name.trim(), description: description.trim(), trigger, enabled: true });
    reset();
    onClose();
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.6)", backdropFilter: "blur(4px)" }}>
      <div
        className="w-full max-w-md rounded-xl p-6 flex flex-col gap-5 shadow-2xl"
        style={{ background: "var(--surface)", border: "1px solid var(--border-strong)" }}
      >
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-base" style={{ color: "var(--text)" }}>New Workflow</h2>
          <button onClick={handleClose} className="rounded-md p-1 transition-colors" style={{ color: "var(--text-muted)" }}>
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium" style={{ color: "var(--text-muted)" }}>Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My workflow"
              required
              className="rounded-lg px-3 py-2 text-sm outline-none transition-colors"
              style={{
                background: "var(--surface-muted)",
                border: "1px solid var(--border)",
                color: "var(--text)",
              }}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium" style={{ color: "var(--text-muted)" }}>Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What does this workflow do?"
              rows={2}
              className="rounded-lg px-3 py-2 text-sm outline-none transition-colors resize-none"
              style={{
                background: "var(--surface-muted)",
                border: "1px solid var(--border)",
                color: "var(--text)",
              }}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium" style={{ color: "var(--text-muted)" }}>Trigger</label>
            <div className="flex gap-2">
              {(["manual", "scheduled"] as WorkflowTrigger[]).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setTrigger(t)}
                  className="flex-1 rounded-lg px-3 py-2 text-xs font-medium transition-colors"
                  style={{
                    background: trigger === t ? "var(--accent-soft)" : "var(--surface-muted)",
                    color: trigger === t ? "var(--accent-strong)" : "var(--text-muted)",
                    border: trigger === t ? "1px solid rgba(59,130,246,0.3)" : "1px solid var(--border)",
                  }}
                >
                  {t.charAt(0).toUpperCase() + t.slice(1)}
                </button>
              ))}
            </div>
          </div>

          <div className="flex gap-2 pt-1">
            <button
              type="button"
              onClick={handleClose}
              className="flex-1 rounded-lg px-3 py-2 text-xs font-medium transition-colors"
              style={{ background: "var(--surface-muted)", color: "var(--text-muted)", border: "1px solid var(--border)" }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!name.trim()}
              className="flex-1 rounded-lg px-3 py-2 text-xs font-medium transition-colors disabled:opacity-50"
              style={{ background: "var(--accent)", color: "#fff" }}
            >
              Create
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Saved Workflow Row ────────────────────────────────────────────────────────

interface WorkflowRowProps {
  workflow: SavedWorkflow;
  onToggle: (id: string) => void;
  onDelete: (id: string) => void;
}

function WorkflowRow({ workflow, onToggle, onDelete }: WorkflowRowProps) {
  const formattedDate = workflow.lastRunAt
    ? new Date(workflow.lastRunAt).toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;

  return (
    <div
      className="flex items-center gap-3 px-4 py-3"
      style={{ borderBottom: "1px solid var(--border)" }}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <p className="text-sm font-medium truncate" style={{ color: "var(--text)" }}>
            {workflow.name}
          </p>
          <span
            className="rounded px-1.5 py-0.5 text-xs"
            style={{ background: "var(--surface-strong)", color: "var(--text-muted)" }}
          >
            {workflow.trigger}
          </span>
        </div>
        {workflow.description && (
          <p className="text-xs truncate mt-0.5" style={{ color: "var(--text-muted)" }}>
            {workflow.description}
          </p>
        )}
      </div>

      <div className="flex items-center gap-2 flex-shrink-0">
        {formattedDate ? (
          <span className="hidden sm:flex items-center gap-1 text-xs" style={{ color: "var(--text-quiet)" }}>
            <Clock className="h-3 w-3" />
            {formattedDate}
          </span>
        ) : null}
        <RunStatusBadge status={workflow.lastRunStatus} />
        <button
          onClick={() => onToggle(workflow.id)}
          className="transition-colors"
          title={workflow.enabled ? "Disable" : "Enable"}
          style={{ color: workflow.enabled ? "var(--accent-strong)" : "var(--text-quiet)" }}
        >
          {workflow.enabled ? (
            <ToggleRight className="h-5 w-5" />
          ) : (
            <ToggleLeft className="h-5 w-5" />
          )}
        </button>
        <button
          onClick={() => onDelete(workflow.id)}
          className="transition-colors"
          title="Delete"
          style={{ color: "var(--text-quiet)" }}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function WorkflowsPage() {
  const { isSignedIn, getToken } = useAuth();
  const { isAdmin } = useOrganizationMembership(isSignedIn);

  const [workflows, setWorkflows] = useState<SavedWorkflow[]>([]);
  const [showNewDialog, setShowNewDialog] = useState(false);

  useEffect(() => {
    // Hydrate workflows from localStorage on mount.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setWorkflows(loadWorkflows());
  }, []);

  const handleCreate = useCallback(
    (data: Omit<SavedWorkflow, "id" | "createdAt" | "lastRunAt" | "lastRunStatus">) => {
      const newWf: SavedWorkflow = {
        ...data,
        id: crypto.randomUUID(),
        createdAt: new Date().toISOString(),
        lastRunAt: null,
        lastRunStatus: null,
      };
      const updated = [newWf, ...workflows];
      setWorkflows(updated);
      saveWorkflows(updated);
      logSystemAction("config", `Custom workflow created: ${data.name}`);
    },
    [workflows],
  );

  const handleToggle = useCallback(
    (id: string) => {
      const updated = workflows.map((wf) =>
        wf.id === id ? { ...wf, enabled: !wf.enabled } : wf,
      );
      setWorkflows(updated);
      saveWorkflows(updated);
    },
    [workflows],
  );

  const handleDelete = useCallback(
    (id: string) => {
      const wf = workflows.find((w) => w.id === id);
      const updated = workflows.filter((w) => w.id !== id);
      setWorkflows(updated);
      saveWorkflows(updated);
      if (wf) logSystemAction("config", `Custom workflow deleted: ${wf.name}`);
    },
    [workflows],
  );

  return (
    <>
      <DashboardPageLayout
        signedOut={{
          message: "Sign in to access Workflows.",
          forceRedirectUrl: "/workflows",
          signUpForceRedirectUrl: "/workflows",
        }}
        title="Workflows"
        description="System automation and saved operations."
        isAdmin={isAdmin}
        adminOnlyMessage="Only organization owners and admins can access workflows."
      >
        <div className="flex flex-col gap-8 max-w-3xl">
          {/* Explainer for first-time users */}
          <div
            className="rounded-xl p-4 text-xs leading-relaxed"
            style={{ background: "var(--surface)", border: "1px solid var(--border)", color: "var(--text-muted)" }}
          >
            <p>
              <strong style={{ color: "var(--text)" }}>Workflows</strong> are repeatable
              step-by-step automations. Example:{" "}
              <em>scrape leads → qualify → draft outreach → post to Discord → ping me</em>.
              System workflows below handle app-level tasks; custom workflows are ones
              you save yourself. See{" "}
              <a href="/guide#workflows" className="underline" style={{ color: "var(--accent-strong)" }}>
                Guide → Workflows
              </a>{" "}
              for examples.
            </p>
          </div>

          {/* Section 1: System Workflows */}
          <section className="flex flex-col gap-3">
            <div>
              <h2 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
                System Workflows
              </h2>
              <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
                Pre-built automation actions for system operations.
              </p>
            </div>
            <div className="flex flex-col gap-3">
              <HealthCheckCard getToken={getToken} />
              <DeployCard getToken={getToken} />
              <ErrorDetectCard getToken={getToken} />
            </div>
          </section>

          {/* Section 2: Custom Workflows */}
          <section className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
                  Custom Workflows
                </h2>
                <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
                  Saved operations and bookmarked tasks.
                </p>
              </div>
              <button
                onClick={() => setShowNewDialog(true)}
                className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors"
                style={{
                  background: "var(--surface)",
                  color: "var(--text)",
                  border: "1px solid var(--border)",
                }}
              >
                <Plus className="h-3.5 w-3.5" />
                New Workflow
              </button>
            </div>

            <div
              className="rounded-xl overflow-hidden"
              style={{ border: "1px solid var(--border)", background: "var(--surface)", boxShadow: "var(--shadow-card)" }}
            >
              {workflows.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 px-6 text-center">
                  <div
                    className="flex h-10 w-10 items-center justify-center rounded-full mb-3"
                    style={{ background: "var(--surface-muted)" }}
                  >
                    <Zap className="h-5 w-5" style={{ color: "var(--text-quiet)" }} />
                  </div>
                  <p className="text-sm font-medium" style={{ color: "var(--text-muted)" }}>
                    No custom workflows yet.
                  </p>
                  <p className="text-xs mt-1" style={{ color: "var(--text-quiet)" }}>
                    Create one to save frequently used operations.
                  </p>
                  <button
                    onClick={() => setShowNewDialog(true)}
                    className="mt-4 flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors"
                    style={{ background: "var(--accent-soft)", color: "var(--accent-strong)", border: "1px solid rgba(59,130,246,0.3)" }}
                  >
                    <Plus className="h-3.5 w-3.5" />
                    Create your first workflow
                  </button>
                </div>
              ) : (
                <div>
                  {workflows.map((wf) => (
                    <WorkflowRow
                      key={wf.id}
                      workflow={wf}
                      onToggle={handleToggle}
                      onDelete={handleDelete}
                    />
                  ))}
                </div>
              )}
            </div>
          </section>
        </div>
      </DashboardPageLayout>

      <NewWorkflowDialog
        open={showNewDialog}
        onClose={() => setShowNewDialog(false)}
        onCreate={handleCreate}
      />
    </>
  );
}

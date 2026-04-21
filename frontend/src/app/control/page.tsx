"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Bot, Cpu, ListChecks, Play, Plus, RefreshCw, Trash2 } from "lucide-react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import { getApiBaseUrl } from "@/lib/api-base";

// ── Types ─────────────────────────────────────────────────────────────────────

type Agent = {
  id: string;
  name: string;
  purpose: string;
  system_prompt: string;
  model: string;
  provider: "auto" | "anthropic" | "openai" | string;
  active: boolean;
  tags: string[];
};

type Device = {
  device_id: string;
  name: string;
  capabilities: string[];
  current_task: string | null;
  last_seen: number;
  age_s: number;
  online: boolean;
  meta: Record<string, unknown>;
};

type Task = {
  id: string;
  kind: string;
  payload: Record<string, unknown>;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  agent_id: string | null;
  device_id: string | null;
  result: unknown;
  error: string | null;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
  tags: string[];
};

type FetchFn = typeof fetch;

// ── Helpers ───────────────────────────────────────────────────────────────────

const relTime = (ts: number | null): string => {
  if (!ts) return "—";
  const delta = Math.max(0, Date.now() / 1000 - ts);
  if (delta < 60)   return `${Math.round(delta)}s ago`;
  if (delta < 3600) return `${Math.round(delta / 60)}m ago`;
  return `${Math.round(delta / 3600)}h ago`;
};

const statusBadge = (status: Task["status"]): string => {
  switch (status) {
    case "done":      return "bg-emerald-50 text-emerald-700 border-emerald-200";
    case "running":   return "bg-blue-50 text-blue-700 border-blue-200";
    case "queued":    return "bg-amber-50 text-amber-700 border-amber-200";
    case "failed":    return "bg-rose-50 text-rose-700 border-rose-200";
    case "cancelled": return "bg-slate-100 text-slate-500 border-slate-200";
    default:          return "bg-slate-100 text-slate-600 border-slate-200";
  }
};

// ── API calls ─────────────────────────────────────────────────────────────────

async function api<T>(path: string, fetchFn: FetchFn, init?: RequestInit): Promise<T> {
  const res = await fetchFn(`${getApiBaseUrl()}${path}`, init);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  if (res.status === 204) return undefined as unknown as T;
  return (await res.json()) as T;
}

// ── Agents panel ──────────────────────────────────────────────────────────────

function AgentsPanel({ fetchFn }: { fetchFn: FetchFn }) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [invokeFor, setInvokeFor] = useState<Agent | null>(null);
  const [showNew, setShowNew] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    api<Agent[]>("/api/v1/control/agents", fetchFn)
      .then((data) => { setAgents(data); setErr(null); })
      .catch((e) => setErr(e instanceof Error ? e.message : "load failed"))
      .finally(() => setLoading(false));
  }, [fetchFn]);

  useEffect(() => { load(); }, [load]);

  const toggleActive = useCallback(async (a: Agent) => {
    try {
      const updated = await api<Agent>(`/api/v1/control/agents/${a.id}`, fetchFn, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active: !a.active }),
      });
      setAgents((prev) => prev.map((x) => (x.id === updated.id ? updated : x)));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "toggle failed");
    }
  }, [fetchFn]);

  const remove = useCallback(async (a: Agent) => {
    if (!confirm(`Delete agent "${a.name}"?`)) return;
    try {
      await api(`/api/v1/control/agents/${a.id}`, fetchFn, { method: "DELETE" });
      setAgents((prev) => prev.filter((x) => x.id !== a.id));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "delete failed");
    }
  }, [fetchFn]);

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 md:p-6 shadow-sm">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Bot className="h-4 w-4 text-slate-500" />
          <h3 className="text-lg font-semibold text-slate-900">Agents</h3>
          <span className="text-xs text-slate-400">{agents.length}</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowNew((v) => !v)}
            className="flex items-center gap-1 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:opacity-80"
          >
            <Plus className="h-3.5 w-3.5" /> New
          </button>
          <button
            type="button"
            onClick={load}
            className="text-slate-400 hover:text-slate-600"
            title="Refresh"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>
      {err && <p className="mb-2 text-xs text-rose-600">{err}</p>}
      {showNew && <NewAgentForm fetchFn={fetchFn} onCreated={(a) => { setAgents((p) => [...p, a]); setShowNew(false); }} />}
      <div className="divide-y divide-slate-100 rounded-lg border border-slate-200">
        {agents.length === 0 && !loading && (
          <div className="px-3 py-4 text-sm text-slate-500">No agents yet.</div>
        )}
        {agents.map((a) => (
          <div key={a.id} className="flex items-start justify-between gap-3 px-3 py-2.5">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className={`inline-block h-2 w-2 rounded-full ${a.active ? "bg-emerald-500" : "bg-slate-300"}`} />
                <span className="truncate text-sm font-medium text-slate-900">{a.name}</span>
                <span className="shrink-0 text-[10px] uppercase tracking-wider text-slate-400">{a.provider}</span>
                {a.tags.map((t) => (
                  <span key={t} className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-600">{t}</span>
                ))}
              </div>
              <p className="mt-0.5 truncate text-xs text-slate-500">{a.purpose}</p>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <button
                type="button"
                onClick={() => setInvokeFor(a)}
                className="rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
              >
                <Play className="inline h-3 w-3" /> Invoke
              </button>
              <button
                type="button"
                onClick={() => void toggleActive(a)}
                className="rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
              >
                {a.active ? "Pause" : "Activate"}
              </button>
              <button
                type="button"
                onClick={() => void remove(a)}
                className="rounded-md border border-slate-200 px-2 py-1 text-xs text-rose-500 hover:bg-rose-50"
                title="Delete"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          </div>
        ))}
      </div>
      {invokeFor && (
        <InvokeModal agent={invokeFor} fetchFn={fetchFn} onClose={() => setInvokeFor(null)} />
      )}
    </section>
  );
}

function NewAgentForm({ fetchFn, onCreated }: { fetchFn: FetchFn; onCreated: (a: Agent) => void }) {
  const [name, setName] = useState("");
  const [purpose, setPurpose] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const save = async () => {
    setSaving(true); setErr(null);
    try {
      const created = await api<Agent>("/api/v1/control/agents", fetchFn, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, purpose, system_prompt: systemPrompt }),
      });
      onCreated(created);
      setName(""); setPurpose(""); setSystemPrompt("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "create failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mb-3 space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3">
      <input
        placeholder="Agent name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-sm"
      />
      <input
        placeholder="Purpose (one line)"
        value={purpose}
        onChange={(e) => setPurpose(e.target.value)}
        className="w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-sm"
      />
      <textarea
        placeholder="System prompt / behavior"
        value={systemPrompt}
        onChange={(e) => setSystemPrompt(e.target.value)}
        rows={3}
        className="w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-sm"
      />
      {err && <p className="text-xs text-rose-600">{err}</p>}
      <button
        type="button"
        onClick={() => void save()}
        disabled={saving || !name.trim() || !systemPrompt.trim()}
        className="rounded-md bg-slate-900 px-3 py-1.5 text-xs text-white disabled:opacity-40"
      >
        {saving ? "Saving…" : "Create agent"}
      </button>
    </div>
  );
}

function InvokeModal({ agent, fetchFn, onClose }: { agent: Agent; fetchFn: FetchFn; onClose: () => void }) {
  const [prompt, setPrompt] = useState("");
  const [reply, setReply] = useState<string | null>(null);
  const [stats, setStats] = useState<{ provider: string; response_ms: number } | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = async () => {
    setLoading(true); setErr(null); setReply(null); setStats(null);
    try {
      const res = await api<{ reply: string; provider: string; response_ms: number }>(
        `/api/v1/control/agents/${agent.id}/invoke`,
        fetchFn,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt }),
        },
      );
      setReply(res.reply);
      setStats({ provider: res.provider, response_ms: res.response_ms });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "invoke failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/30 p-4" onClick={onClose}>
      <div
        className="w-full max-w-lg rounded-xl border border-slate-200 bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h4 className="font-semibold text-slate-900">Invoke: {agent.name}</h4>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-600">✕</button>
        </div>
        <textarea
          placeholder="Prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={4}
          className="w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-sm"
        />
        <div className="mt-2 flex justify-end">
          <button
            type="button"
            onClick={() => void run()}
            disabled={loading || !prompt.trim()}
            className="rounded-md bg-slate-900 px-3 py-1.5 text-xs text-white disabled:opacity-40"
          >
            {loading ? "Running…" : "Run"}
          </button>
        </div>
        {err && <p className="mt-2 text-xs text-rose-600">{err}</p>}
        {reply && (
          <div className="mt-3 space-y-2">
            <div className="text-[11px] text-slate-500">
              {stats && <>provider: <span className="font-mono">{stats.provider}</span> · {stats.response_ms.toFixed(0)} ms</>}
            </div>
            <div className="max-h-60 overflow-auto whitespace-pre-wrap rounded-md border border-slate-200 bg-slate-50 p-3 text-sm text-slate-800">
              {reply}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Devices panel ─────────────────────────────────────────────────────────────

function DevicesPanel({ fetchFn }: { fetchFn: FetchFn }) {
  const [devices, setDevices] = useState<Device[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    api<Device[]>("/api/v1/control/devices", fetchFn)
      .then(setDevices)
      .catch(() => setDevices([]))
      .finally(() => setLoading(false));
  }, [fetchFn]);

  useEffect(() => {
    load();
    const id = window.setInterval(load, 15_000);
    return () => window.clearInterval(id);
  }, [load]);

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 md:p-6 shadow-sm">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Cpu className="h-4 w-4 text-slate-500" />
          <h3 className="text-lg font-semibold text-slate-900">Devices / Nodes</h3>
          <span className="text-xs text-slate-400">{devices.length}</span>
        </div>
        <button type="button" onClick={load} className="text-slate-400 hover:text-slate-600">
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>
      <div className="divide-y divide-slate-100 rounded-lg border border-slate-200">
        {devices.length === 0 && !loading && (
          <div className="px-3 py-4 text-sm text-slate-500">
            No devices have checked in yet. CLAW nodes heartbeat to
            <code className="ml-1 text-xs">/api/v1/control/devices/heartbeat</code>.
          </div>
        )}
        {devices.map((d) => (
          <div key={d.device_id} className="flex items-start justify-between gap-3 px-3 py-2.5">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className={`inline-block h-2 w-2 rounded-full ${d.online ? "bg-emerald-500" : "bg-slate-300"}`} />
                <span className="truncate text-sm font-medium text-slate-900">{d.name}</span>
                <span className="text-[10px] font-mono text-slate-400">{d.device_id}</span>
              </div>
              <p className="mt-0.5 truncate text-xs text-slate-500">
                {d.capabilities.length ? d.capabilities.join(" · ") : "no capabilities reported"}
                {d.current_task && <> · running <span className="font-mono">{d.current_task}</span></>}
              </p>
            </div>
            <span className="shrink-0 text-[11px] text-slate-500">last seen {relTime(d.last_seen)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

// ── Tasks panel ───────────────────────────────────────────────────────────────

function TasksPanel({ fetchFn }: { fetchFn: FetchFn }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    api<Task[]>("/api/v1/control/tasks?limit=25", fetchFn)
      .then(setTasks)
      .catch(() => setTasks([]))
      .finally(() => setLoading(false));
  }, [fetchFn]);

  useEffect(() => {
    load();
    const id = window.setInterval(load, 10_000);
    return () => window.clearInterval(id);
  }, [load]);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    tasks.forEach((t) => { c[t.status] = (c[t.status] ?? 0) + 1; });
    return c;
  }, [tasks]);

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 md:p-6 shadow-sm">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <ListChecks className="h-4 w-4 text-slate-500" />
          <h3 className="text-lg font-semibold text-slate-900">Tasks</h3>
          <span className="text-xs text-slate-400">
            {tasks.length} — {Object.entries(counts).map(([k, v]) => `${v} ${k}`).join(", ")}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowNew((v) => !v)}
            className="flex items-center gap-1 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:opacity-80"
          >
            <Plus className="h-3.5 w-3.5" /> Enqueue
          </button>
          <button type="button" onClick={load} className="text-slate-400 hover:text-slate-600">
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>
      {showNew && (
        <EnqueueTaskForm fetchFn={fetchFn} onCreated={(t) => { setTasks((p) => [t, ...p]); setShowNew(false); }} />
      )}
      <div className="divide-y divide-slate-100 rounded-lg border border-slate-200">
        {tasks.length === 0 && !loading && (
          <div className="px-3 py-4 text-sm text-slate-500">No tasks yet.</div>
        )}
        {tasks.map((t) => (
          <div key={t.id} className="flex items-start justify-between gap-3 px-3 py-2.5">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className={`rounded-full border px-2 py-0.5 text-[10px] ${statusBadge(t.status)}`}>
                  {t.status}
                </span>
                <span className="truncate text-sm font-medium text-slate-900">{t.kind}</span>
                <span className="text-[10px] font-mono text-slate-400">{t.id}</span>
              </div>
              <p className="mt-0.5 truncate text-xs text-slate-500">
                {t.device_id ? <>node <span className="font-mono">{t.device_id}</span> · </> : null}
                {t.agent_id ? <>agent <span className="font-mono">{t.agent_id}</span> · </> : null}
                {relTime(t.created_at)}
                {t.error ? <> · <span className="text-rose-600">{t.error}</span></> : null}
              </p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function EnqueueTaskForm({ fetchFn, onCreated }: { fetchFn: FetchFn; onCreated: (t: Task) => void }) {
  const [kind, setKind] = useState("");
  const [payload, setPayload] = useState("{}");
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true); setErr(null);
    try {
      let parsed: Record<string, unknown> = {};
      try { parsed = JSON.parse(payload || "{}"); }
      catch { throw new Error("Payload is not valid JSON"); }
      const t = await api<Task>("/api/v1/control/tasks", fetchFn, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, payload: parsed }),
      });
      onCreated(t);
      setKind(""); setPayload("{}");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "enqueue failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mb-3 space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3">
      <input
        placeholder="Task kind (e.g. scrape, respond, monitor)"
        value={kind}
        onChange={(e) => setKind(e.target.value)}
        className="w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-sm"
      />
      <textarea
        placeholder='Payload JSON (e.g. {"url":"https://…"})'
        value={payload}
        onChange={(e) => setPayload(e.target.value)}
        rows={2}
        className="w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 font-mono text-xs"
      />
      {err && <p className="text-xs text-rose-600">{err}</p>}
      <button
        type="button"
        onClick={() => void save()}
        disabled={saving || !kind.trim()}
        className="rounded-md bg-slate-900 px-3 py-1.5 text-xs text-white disabled:opacity-40"
      >
        {saving ? "Enqueuing…" : "Enqueue"}
      </button>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

function ControlBody() {
  const { fetchWithAuth } = useAuthFetch();
  return (
    <div className="max-w-5xl mx-auto px-6 py-6 space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Control</h1>
        <p className="text-sm text-slate-500">Agents, device nodes, and background tasks.</p>
      </div>
      <AgentsPanel fetchFn={fetchWithAuth} />
      <DevicesPanel fetchFn={fetchWithAuth} />
      <TasksPanel fetchFn={fetchWithAuth} />
    </div>
  );
}

export default function ControlPage() {
  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel message="Sign in to access Control." forceRedirectUrl="/control" />
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <main className="flex-1 overflow-y-auto bg-slate-50">
          <ControlBody />
        </main>
      </SignedIn>
    </DashboardShell>
  );
}

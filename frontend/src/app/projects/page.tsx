"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Circle,
  Clock,
  FolderOpen,
  Loader2,
  Trash2,
  Zap,
} from "lucide-react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import {
  entryArea,
  entryProject,
  inferProject,
  loadMemory,
  saveMemory,
  type MemoryEntry,
} from "@/lib/memory-store";
import {
  loadOperatorSessions,
  saveOperatorSessions,
  type OperatorSession,
} from "@/lib/operator-store";

// ── Projects config ───────────────────────────────────────────────────────────

const ALL_PROJECTS = [
  "Digidle",
  "Modern Sales Agency",
  "Modern Athlete",
  "Grover Art Projects",
  "General",
] as const;

const PROJECT_COLOR: Record<string, string> = {
  "Digidle":              "text-emerald-400",
  "Modern Sales Agency":  "text-blue-400",
  "Modern Athlete":       "text-orange-400",
  "Grover Art Projects":  "text-purple-400",
  "General":              "text-slate-400",
};

const PROJECT_ACCENT: Record<string, string> = {
  "Digidle":              "rgb(52 211 153 / 0.12)",
  "Modern Sales Agency":  "rgb(96 165 250 / 0.12)",
  "Modern Athlete":       "rgb(251 146 60 / 0.12)",
  "Grover Art Projects":  "rgb(167 139 250 / 0.12)",
  "General":              "rgb(148 163 184 / 0.10)",
};

const AREA_ORDER = ["Strategy", "Operations", "Marketing", "Sales", "Product", "Admin", "Analysis", "Content", "Decision", "Other", "Unsorted"];

const TYPE_BADGE: Record<string, string> = {
  context:  "text-blue-400 bg-blue-500/10",
  decision: "text-amber-400 bg-amber-500/10",
  note:     "text-slate-400 bg-slate-500/10",
  insight:  "text-violet-400 bg-violet-500/10",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function groupMemoryByArea(entries: MemoryEntry[]): Map<string, MemoryEntry[]> {
  const map = new Map<string, MemoryEntry[]>();
  for (const e of entries) {
    const area = entryArea(e);
    if (!map.has(area)) map.set(area, []);
    map.get(area)!.push(e);
  }
  // Sort by AREA_ORDER
  return new Map(
    [...map.entries()].sort(([a], [b]) => {
      const ai = AREA_ORDER.indexOf(a);
      const bi = AREA_ORDER.indexOf(b);
      if (ai === -1 && bi === -1) return a.localeCompare(b);
      if (ai === -1) return 1;
      if (bi === -1) return -1;
      return ai - bi;
    }),
  );
}

function sessionProject(session: OperatorSession): string {
  return inferProject(session.objective + " " + session.goal);
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  } catch { return ""; }
}

// ── Phase icon ────────────────────────────────────────────────────────────────

function PhaseIcon({ phase }: { phase: OperatorSession["phase"] }) {
  if (phase === "planning" || phase === "executing")
    return <Loader2 className="h-3.5 w-3.5 animate-spin" style={{ color: "var(--accent)" }} />;
  if (phase === "done") return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />;
  if (phase === "error") return <AlertCircle className="h-3.5 w-3.5 text-red-400" />;
  return <Circle className="h-3.5 w-3.5" style={{ color: "var(--text-quiet)" }} />;
}

// ── Memory area card ──────────────────────────────────────────────────────────

function AreaCard({
  area,
  entries,
  onDelete,
}: {
  area: string;
  entries: MemoryEntry[];
  onDelete: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="space-y-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 py-1 text-left group"
      >
        <span className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>
          {area}
        </span>
        <span className="text-[10px] tabular-nums px-1.5 py-0.5 rounded" style={{ background: "var(--surface-muted)", color: "var(--text-quiet)" }}>
          {entries.length}
        </span>
        <span className="ml-auto opacity-50 group-hover:opacity-100 transition-opacity" style={{ color: "var(--text-quiet)" }}>
          {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        </span>
      </button>

      {open && (
        <div className="space-y-1.5 pl-3 border-l" style={{ borderColor: "var(--border)" }}>
          {entries.map((e) => (
            <div
              key={e.id}
              className="flex items-start gap-2 rounded-lg px-3 py-2.5"
              style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}
            >
              <span className={`text-[9px] font-bold uppercase tracking-wide rounded px-1.5 py-0.5 shrink-0 mt-0.5 ${TYPE_BADGE[e.type] ?? ""}`}>
                {e.type}
              </span>
              <p className="flex-1 text-sm leading-relaxed" style={{ color: "var(--text)" }}>
                {e.content}
              </p>
              <button
                type="button"
                onClick={() => onDelete(e.id)}
                className="shrink-0 rounded p-1 transition-opacity hover:opacity-70 mt-0.5"
                style={{ color: "var(--text-quiet)" }}
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Operator session row ──────────────────────────────────────────────────────

function SessionRow({ session }: { session: OperatorSession }) {
  const [open, setOpen] = useState(false);
  const doneSteps = session.steps.filter((s) => s.status === "done").length;

  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-start gap-3 px-3 py-2.5 text-left"
      >
        <div className="mt-0.5"><PhaseIcon phase={session.phase} /></div>
        <div className="flex-1 min-w-0">
          <p className="text-sm leading-snug" style={{ color: "var(--text)" }}>{session.objective}</p>
          {session.goal && session.goal !== session.objective && (
            <p className="text-xs mt-0.5 truncate" style={{ color: "var(--text-quiet)" }}>→ {session.goal}</p>
          )}
        </div>
        <div className="shrink-0 flex items-center gap-2">
          {session.steps.length > 0 && (
            <span className="text-[10px] tabular-nums" style={{ color: "var(--text-quiet)" }}>
              {doneSteps}/{session.steps.length}
            </span>
          )}
          <span className="text-[10px]" style={{ color: "var(--text-quiet)" }}>
            {formatDate(session.createdAt)}
          </span>
          {open ? <ChevronUp className="h-3 w-3" style={{ color: "var(--text-quiet)" }} /> : <ChevronDown className="h-3 w-3" style={{ color: "var(--text-quiet)" }} />}
        </div>
      </button>

      {open && session.insights.length > 0 && (
        <div className="px-3 pb-3 pt-0 border-t space-y-1.5" style={{ borderColor: "var(--border)" }}>
          <p className="text-[10px] font-semibold uppercase tracking-widest mt-2" style={{ color: "var(--text-quiet)" }}>
            Insights
          </p>
          {session.insights.map((ins, i) => (
            <div key={i} className="flex items-start gap-2">
              <span className={`text-[9px] font-bold uppercase tracking-wide rounded px-1.5 py-0.5 shrink-0 mt-0.5 ${
                ins.type === "decision" ? "text-amber-400 bg-amber-500/10"
                : ins.type === "context" ? "text-blue-400 bg-blue-500/10"
                : "text-violet-400 bg-violet-500/10"
              }`}>{ins.type}</span>
              <p className="text-xs leading-snug" style={{ color: "var(--text-muted)" }}>{ins.content}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Project card ──────────────────────────────────────────────────────────────

function ProjectCard({
  project,
  memEntries,
  sessions,
  onDeleteMemory,
}: {
  project: string;
  memEntries: MemoryEntry[];
  sessions: OperatorSession[];
  onDeleteMemory: (id: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const areaMap = groupMemoryByArea(memEntries);
  const color = PROJECT_COLOR[project] ?? "text-slate-400";
  const bg = PROJECT_ACCENT[project] ?? "rgb(148 163 184 / 0.08)";

  const totalItems = memEntries.length + sessions.length;

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ border: "1px solid var(--border-strong)" }}
    >
      {/* Header */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-3 px-5 py-4 text-left"
        style={{ background: bg }}
      >
        <FolderOpen className={`h-4 w-4 shrink-0 ${color}`} />
        <span className={`text-sm font-semibold ${color}`}>{project}</span>
        <div className="flex items-center gap-2 ml-1">
          {memEntries.length > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: "var(--surface-muted)", color: "var(--text-quiet)" }}>
              {memEntries.length} {memEntries.length === 1 ? "memory" : "memories"}
            </span>
          )}
          {sessions.length > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded flex items-center gap-1" style={{ background: "var(--surface-muted)", color: "var(--text-quiet)" }}>
              <Zap className="h-2.5 w-2.5" />
              {sessions.length} {sessions.length === 1 ? "run" : "runs"}
            </span>
          )}
        </div>
        <span className="ml-auto" style={{ color: "var(--text-quiet)" }}>
          {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </span>
      </button>

      {/* Body */}
      {open && totalItems > 0 && (
        <div className="px-5 py-4 space-y-5" style={{ background: "var(--surface)" }}>

          {/* Memory by area */}
          {areaMap.size > 0 && (
            <div className="space-y-3">
              {[...areaMap.entries()].map(([area, entries]) => (
                <AreaCard key={area} area={area} entries={entries} onDelete={onDeleteMemory} />
              ))}
            </div>
          )}

          {/* Operator sessions */}
          {sessions.length > 0 && (
            <div className="space-y-2">
              <p className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>
                Operator Runs
              </p>
              {sessions.map((s) => (
                <SessionRow key={s.id} session={s} />
              ))}
            </div>
          )}

        </div>
      )}

      {/* Empty state */}
      {open && totalItems === 0 && (
        <div className="px-5 py-6 text-center" style={{ background: "var(--surface)" }}>
          <p className="text-sm" style={{ color: "var(--text-quiet)" }}>
            No entries yet. Use Operator Mode or add memories tagged to {project}.
          </p>
        </div>
      )}
    </div>
  );
}

// ── Projects content ──────────────────────────────────────────────────────────

function ProjectsContent() {
  const [memEntries, setMemEntries] = useState<MemoryEntry[]>([]);
  const [sessions, setSessions] = useState<OperatorSession[]>([]);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    try { setMemEntries(loadMemory()); } catch { /* ignore */ }
    try { setSessions(loadOperatorSessions()); } catch { /* ignore */ }
  }, []);

  const handleDeleteMemory = useCallback((id: string) => {
    const next = memEntries.filter((e) => e.id !== id);
    setMemEntries(next);
    saveMemory(next);
  }, [memEntries]);

  // Collect projects that have data, plus always show the defined ones
  const activeProjects = mounted
    ? ALL_PROJECTS.filter((p) => {
        const hasMemory   = memEntries.some((e) => entryProject(e) === p);
        const hasSessions = sessions.some((s) => sessionProject(s) === p);
        return hasMemory || hasSessions;
      })
    : [];

  // Projects with no data — shown collapsed with empty state
  const emptyProjects = mounted ? ALL_PROJECTS.filter((p) => !activeProjects.includes(p)) : [];

  return (
    <main className="flex-1 overflow-y-auto" style={{ background: "var(--bg)" }}>
      <div className="max-w-2xl mx-auto px-6 py-8 space-y-6">

        {/* Header */}
        <div>
          <h1 className="text-xl font-semibold" style={{ color: "var(--text)" }}>Projects</h1>
          <p className="mt-1 text-sm" style={{ color: "var(--text-muted)" }}>
            Long-term knowledge base organized by business and area. Populated automatically by Operator runs and tagged memory entries.
          </p>
        </div>

        {!mounted && <div className="h-40" />}

        {mounted && (
          <>
            {/* Active projects */}
            {activeProjects.length > 0 && (
              <div className="space-y-3">
                {activeProjects.map((project) => (
                  <ProjectCard
                    key={project}
                    project={project}
                    memEntries={memEntries.filter((e) => entryProject(e) === project && e.type !== "journal")}
                    sessions={sessions.filter((s) => sessionProject(s) === project)}
                    onDeleteMemory={handleDeleteMemory}
                  />
                ))}
              </div>
            )}

            {/* All projects empty state */}
            {activeProjects.length === 0 && (
              <div
                className="rounded-xl px-6 py-14 text-center space-y-3"
                style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}
              >
                <FolderOpen className="h-8 w-8 mx-auto" style={{ color: "var(--text-quiet)" }} />
                <p className="text-sm font-medium" style={{ color: "var(--text)" }}>No project data yet</p>
                <p className="text-sm max-w-sm mx-auto leading-relaxed" style={{ color: "var(--text-quiet)" }}>
                  Use <strong>Operator Mode</strong> in Master Chat to run objectives — insights will automatically appear here, organized by project and area.
                </p>
              </div>
            )}

            {/* Inactive projects (collapsed, minimal) */}
            {emptyProjects.length > 0 && activeProjects.length > 0 && (
              <div className="space-y-2 pt-2">
                <p className="text-[10px] font-semibold uppercase tracking-widest px-1" style={{ color: "var(--text-quiet)" }}>
                  Other Projects
                </p>
                {emptyProjects.map((project) => (
                  <ProjectCard
                    key={project}
                    project={project}
                    memEntries={[]}
                    sessions={[]}
                    onDeleteMemory={handleDeleteMemory}
                  />
                ))}
              </div>
            )}

            {/* Stats footer */}
            {(memEntries.length > 0 || sessions.length > 0) && (
              <div
                className="flex items-center gap-4 rounded-xl px-5 py-3 text-xs"
                style={{ background: "var(--surface-strong)", border: "1px solid var(--border)", color: "var(--text-quiet)" }}
              >
                <span className="flex items-center gap-1.5">
                  <Clock className="h-3 w-3" />
                  Last updated: {formatDate(
                    [...memEntries, ...sessions.map((s) => ({ createdAt: s.completedAt ?? s.createdAt }))]
                      .sort((a, b) => (b.createdAt > a.createdAt ? 1 : -1))[0]?.createdAt ?? ""
                  )}
                </span>
                <span>{memEntries.filter((e) => e.type !== "journal").length} memory entries</span>
                <span>{sessions.length} operator runs</span>
              </div>
            )}
          </>
        )}
      </div>
    </main>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ProjectsPage() {
  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel message="Sign in to access Digidle OS" forceRedirectUrl="/projects" />
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <ErrorBoundary>
          <ProjectsContent />
        </ErrorBoundary>
      </SignedIn>
    </DashboardShell>
  );
}

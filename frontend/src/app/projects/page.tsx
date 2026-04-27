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
  Pencil,
  Plus,
  Trash2,
  Zap,
} from "lucide-react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
  type OperatorSession,
} from "@/lib/operator-store";
import {
  createProject,
  deleteProject,
  loadProjects,
  saveProjects,
  updateProject,
  type ProjectDef,
} from "@/lib/project-store";
import { logSystemAction } from "@/lib/action-logger";

// ── Color config ──────────────────────────────────────────────────────────────

const PRESET_COLORS = [
  { value: "emerald", label: "Emerald" },
  { value: "blue",    label: "Blue" },
  { value: "orange",  label: "Orange" },
  { value: "purple",  label: "Purple" },
  { value: "slate",   label: "Slate" },
  { value: "rose",    label: "Rose" },
  { value: "cyan",    label: "Cyan" },
] as const;

type ColorName = (typeof PRESET_COLORS)[number]["value"];

const COLOR_TEXT: Record<ColorName, string> = {
  emerald: "text-emerald-400",
  blue:    "text-blue-400",
  orange:  "text-orange-400",
  purple:  "text-purple-400",
  slate:   "text-slate-400",
  rose:    "text-rose-400",
  cyan:    "text-cyan-400",
};

const COLOR_ACCENT: Record<ColorName, string> = {
  emerald: "rgb(52 211 153 / 0.12)",
  blue:    "rgb(96 165 250 / 0.12)",
  orange:  "rgb(251 146 60 / 0.12)",
  purple:  "rgb(167 139 250 / 0.12)",
  slate:   "rgb(148 163 184 / 0.10)",
  rose:    "rgb(251 113 133 / 0.12)",
  cyan:    "rgb(34 211 238 / 0.12)",
};

const COLOR_DOT: Record<ColorName, string> = {
  emerald: "bg-emerald-400",
  blue:    "bg-blue-400",
  orange:  "bg-orange-400",
  purple:  "bg-purple-400",
  slate:   "bg-slate-400",
  rose:    "bg-rose-400",
  cyan:    "bg-cyan-400",
};

function colorText(color: string): string {
  return COLOR_TEXT[color as ColorName] ?? "text-slate-400";
}
function colorAccent(color: string): string {
  return COLOR_ACCENT[color as ColorName] ?? "rgb(148 163 184 / 0.10)";
}
function colorDot(color: string): string {
  return COLOR_DOT[color as ColorName] ?? "bg-slate-400";
}

// ── Other constants ───────────────────────────────────────────────────────────

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

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: ProjectDef["status"] }) {
  if (status === "active") {
    return <span className="h-2 w-2 rounded-full bg-emerald-400 shrink-0" title="Active" />;
  }
  if (status === "paused") {
    return <span className="h-2 w-2 rounded-full bg-amber-400 shrink-0" title="Paused" />;
  }
  return <span className="h-2 w-2 rounded-full bg-slate-500 shrink-0" title="Archived" />;
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
  onEdit,
  onDelete,
}: {
  project: ProjectDef;
  memEntries: MemoryEntry[];
  sessions: OperatorSession[];
  onDeleteMemory: (id: string) => void;
  onEdit: (project: ProjectDef) => void;
  onDelete: (project: ProjectDef) => void;
}) {
  const [open, setOpen] = useState(true);
  const areaMap = groupMemoryByArea(memEntries);
  const textColor = colorText(project.color);
  const bg = colorAccent(project.color);

  const totalItems = memEntries.length + sessions.length;

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ border: "1px solid var(--border-strong)" }}
    >
      {/* Header */}
      <div
        className="flex items-center gap-3 px-5 py-4"
        style={{ background: bg }}
      >
        {/* Expand/collapse — clicking the left portion */}
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-3 flex-1 min-w-0 text-left"
        >
          <FolderOpen className={`h-4 w-4 shrink-0 ${textColor}`} />
          <StatusBadge status={project.status} />
          <span className={`text-sm font-semibold truncate ${textColor}`}>{project.name}</span>
          <div className="flex items-center gap-2 ml-1 shrink-0">
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

        {/* Action buttons */}
        <div className="flex items-center gap-1 shrink-0">
          <button
            type="button"
            onClick={() => onEdit(project)}
            className="rounded p-1.5 transition-opacity hover:opacity-70"
            style={{ color: "var(--text-quiet)" }}
            title="Edit project"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={() => onDelete(project)}
            className="rounded p-1.5 transition-opacity hover:opacity-70"
            style={{ color: "var(--text-quiet)" }}
            title="Delete project"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

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
            No entries yet. Use Operator Mode or add memories tagged to {project.name}.
          </p>
        </div>
      )}
    </div>
  );
}

// ── Project form modal ────────────────────────────────────────────────────────

interface ProjectFormState {
  name: string;
  description: string;
  area: string;
  status: ProjectDef["status"];
  color: string;
}

const EMPTY_FORM: ProjectFormState = {
  name: "",
  description: "",
  area: "General",
  status: "active",
  color: "slate",
};

function ProjectFormDialog({
  open,
  onOpenChange,
  initialValues,
  onSave,
  isEdit,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  initialValues?: ProjectFormState;
  onSave: (values: ProjectFormState) => void;
  isEdit: boolean;
}) {
  const [form, setForm] = useState<ProjectFormState>(initialValues ?? EMPTY_FORM);

  // Reset when dialog opens with new values
  useEffect(() => {
    if (open) setForm(initialValues ?? EMPTY_FORM);
  }, [open, initialValues]);

  const field = (key: keyof ProjectFormState) => (
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
      setForm((prev) => ({ ...prev, [key]: e.target.value }))
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) return;
    onSave(form);
  };

  const inputStyle: React.CSSProperties = {
    background: "var(--surface-strong)",
    border: "1px solid var(--border)",
    color: "var(--text)",
    borderRadius: "0.5rem",
    padding: "0.5rem 0.75rem",
    fontSize: "0.875rem",
    width: "100%",
    outline: "none",
  };

  const labelStyle: React.CSSProperties = {
    fontSize: "0.75rem",
    fontWeight: 600,
    color: "var(--text-quiet)",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    display: "block",
    marginBottom: "0.375rem",
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit Project" : "New Project"}</DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4 mt-2">
          {/* Name */}
          <div>
            <label style={labelStyle}>Name *</label>
            <input
              style={inputStyle}
              value={form.name}
              onChange={field("name")}
              placeholder="Project name"
              required
              autoFocus
            />
          </div>

          {/* Description */}
          <div>
            <label style={labelStyle}>Description</label>
            <textarea
              style={{ ...inputStyle, resize: "vertical", minHeight: "5rem" }}
              value={form.description}
              onChange={field("description")}
              placeholder="Short description"
            />
          </div>

          {/* Area */}
          <div>
            <label style={labelStyle}>Area</label>
            <input
              style={inputStyle}
              value={form.area}
              onChange={field("area")}
              placeholder="e.g. Product & Tech, Sales, Creative"
            />
          </div>

          {/* Status + Color in one row */}
          <div className="flex gap-3">
            <div className="flex-1">
              <label style={labelStyle}>Status</label>
              <select style={inputStyle} value={form.status} onChange={field("status")}>
                <option value="active">Active</option>
                <option value="paused">Paused</option>
                <option value="archived">Archived</option>
              </select>
            </div>
            <div className="flex-1">
              <label style={labelStyle}>Color</label>
              <select style={inputStyle} value={form.color} onChange={field("color")}>
                {PRESET_COLORS.map((c) => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Color preview */}
          <div className="flex items-center gap-2">
            <span
              className={`h-3 w-3 rounded-full ${colorDot(form.color)}`}
            />
            <span className={`text-sm font-medium ${colorText(form.color)}`}>
              {form.name || "Preview"}
            </span>
          </div>

          <DialogFooter className="mt-6">
            <Button type="button" variant="outline" size="sm" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" size="sm" disabled={!form.name.trim()}>
              {isEdit ? "Save Changes" : "Create Project"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ── Delete confirm dialog ─────────────────────────────────────────────────────

function DeleteProjectDialog({
  project,
  onOpenChange,
  onConfirm,
}: {
  project: ProjectDef | null;
  onOpenChange: (v: boolean) => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog open={!!project} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Delete project?</DialogTitle>
        </DialogHeader>
        <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
          <strong style={{ color: "var(--text)" }}>{project?.name}</strong> will be removed from
          the projects list. Memory entries and operator runs tagged to it will not be deleted —
          they will fall back to General.
        </p>
        <DialogFooter className="mt-4">
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            size="sm"
            className="bg-red-600 hover:bg-red-700 text-white"
            onClick={onConfirm}
          >
            Delete
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Projects content ──────────────────────────────────────────────────────────

function ProjectsContent() {
  const [memEntries, setMemEntries] = useState<MemoryEntry[]>([]);
  const [sessions, setSessions] = useState<OperatorSession[]>([]);
  const [projects, setProjects] = useState<ProjectDef[]>([]);
  const [mounted, setMounted] = useState(false);

  // Form modal state
  const [formOpen, setFormOpen] = useState(false);
  const [editingProject, setEditingProject] = useState<ProjectDef | null>(null);

  // Delete confirm state
  const [deletingProject, setDeletingProject] = useState<ProjectDef | null>(null);

  useEffect(() => {
    setMounted(true);
    try { setMemEntries(loadMemory()); } catch { /* ignore */ }
    try { setSessions(loadOperatorSessions()); } catch { /* ignore */ }
    try { setProjects(loadProjects()); } catch { /* ignore */ }
  }, []);

  const handleDeleteMemory = useCallback((id: string) => {
    const next = memEntries.filter((e) => e.id !== id);
    setMemEntries(next);
    saveMemory(next);
  }, [memEntries]);

  // ── Project CRUD handlers ───────────────────────────────────────────────────

  const handleOpenNew = () => {
    setEditingProject(null);
    setFormOpen(true);
  };

  const handleOpenEdit = (project: ProjectDef) => {
    setEditingProject(project);
    setFormOpen(true);
  };

  const handleSave = (values: ProjectFormState) => {
    if (editingProject) {
      const updated = updateProject(editingProject.id, {
        name: values.name.trim(),
        description: values.description.trim(),
        area: values.area.trim() || "General",
        status: values.status,
        color: values.color,
      });
      if (updated) {
        setProjects(loadProjects());
        logSystemAction("config", `project_updated: ${values.name.trim()}`);
      }
    } else {
      createProject(values.name.trim(), values.description, values.area, values.status, values.color);
      setProjects(loadProjects());
      logSystemAction("config", `project_created: ${values.name.trim()}`);
    }
    setFormOpen(false);
    setEditingProject(null);
  };

  const handleDeleteConfirm = () => {
    if (!deletingProject) return;
    const name = deletingProject.name;
    deleteProject(deletingProject.id);
    setProjects(loadProjects());
    logSystemAction("config", `project_deleted: ${name}`);
    setDeletingProject(null);
  };

  // ── Classify projects by data presence ─────────────────────────────────────

  const activeProjects = mounted
    ? projects.filter((p) => {
        const hasMemory   = memEntries.some((e) => entryProject(e) === p.name);
        const hasSessions = sessions.some((s) => sessionProject(s) === p.name);
        return hasMemory || hasSessions;
      })
    : [];

  const emptyProjects = mounted
    ? projects.filter((p) => !activeProjects.some((a) => a.id === p.id))
    : [];

  const editingInitialValues: ProjectFormState | undefined = editingProject
    ? {
        name:        editingProject.name,
        description: editingProject.description,
        area:        editingProject.area,
        status:      editingProject.status,
        color:       editingProject.color,
      }
    : undefined;

  return (
    <main className="flex-1 overflow-y-auto" style={{ background: "var(--bg)" }}>
      <div className="max-w-2xl mx-auto px-6 py-8 space-y-6">

        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold" style={{ color: "var(--text)" }}>Projects</h1>
            <p className="mt-1 text-sm" style={{ color: "var(--text-muted)" }}>
              Long-term knowledge base organized by business and area. Populated automatically by Operator runs and tagged memory entries.
            </p>
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={handleOpenNew}
            className="shrink-0 flex items-center gap-1.5"
          >
            <Plus className="h-3.5 w-3.5" />
            New Project
          </Button>
        </div>

        {!mounted && <div className="h-40" />}

        {mounted && (
          <>
            {/* Active projects */}
            {activeProjects.length > 0 && (
              <div className="space-y-3">
                {activeProjects.map((project) => (
                  <ProjectCard
                    key={project.id}
                    project={project}
                    memEntries={memEntries.filter((e) => entryProject(e) === project.name && e.type !== "journal")}
                    sessions={sessions.filter((s) => sessionProject(s) === project.name)}
                    onDeleteMemory={handleDeleteMemory}
                    onEdit={handleOpenEdit}
                    onDelete={setDeletingProject}
                  />
                ))}
              </div>
            )}

            {/* All projects empty state */}
            {activeProjects.length === 0 && projects.length === 0 && (
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
                    key={project.id}
                    project={project}
                    memEntries={[]}
                    sessions={[]}
                    onDeleteMemory={handleDeleteMemory}
                    onEdit={handleOpenEdit}
                    onDelete={setDeletingProject}
                  />
                ))}
              </div>
            )}

            {/* When no active projects but there are defined projects (all empty) */}
            {activeProjects.length === 0 && projects.length > 0 && (
              <div className="space-y-2">
                {emptyProjects.map((project) => (
                  <ProjectCard
                    key={project.id}
                    project={project}
                    memEntries={[]}
                    sessions={[]}
                    onDeleteMemory={handleDeleteMemory}
                    onEdit={handleOpenEdit}
                    onDelete={setDeletingProject}
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

      {/* Form dialog */}
      <ProjectFormDialog
        open={formOpen}
        onOpenChange={(v) => { setFormOpen(v); if (!v) setEditingProject(null); }}
        initialValues={editingInitialValues}
        onSave={handleSave}
        isEdit={!!editingProject}
      />

      {/* Delete confirm dialog */}
      <DeleteProjectDialog
        project={deletingProject}
        onOpenChange={(v) => { if (!v) setDeletingProject(null); }}
        onConfirm={handleDeleteConfirm}
      />
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

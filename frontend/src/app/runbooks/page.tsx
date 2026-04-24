"use client";

export const dynamic = "force-dynamic";

import { useEffect, useMemo, useState } from "react";
import {
  Check,
  ClipboardList,
  Copy,
  Pencil,
  Plus,
  Search,
  Star,
  Trash2,
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
  compareRunbooks,
  createRunbook,
  DANGER_LEVELS,
  deleteRunbook,
  isPlaceholder,
  loadRunbooks,
  RUNBOOK_CATEGORIES,
  saveRunbooks,
  updateRunbook,
  type DangerLevel,
  type RunbookCategory,
  type RunbookDef,
} from "@/lib/runbook-store";

// ── Category filter ──────────────────────────────────────────────────────────

type CategoryFilter = "All" | RunbookCategory;

const CATEGORY_FILTERS: readonly CategoryFilter[] = ["All", ...RUNBOOK_CATEGORIES];

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return "";
  }
}

function matchesQuery(r: RunbookDef, q: string): boolean {
  if (!q) return true;
  const needle = q.toLowerCase();
  return (
    r.title.toLowerCase().includes(needle) ||
    r.category.toLowerCase().includes(needle) ||
    r.description.toLowerCase().includes(needle)
  );
}

// ── Danger badge ─────────────────────────────────────────────────────────────

function DangerBadge({ level, size = "sm" }: { level: DangerLevel; size?: "sm" | "md" }) {
  const color =
    level === "Safe"   ? { bg: "rgb(16 185 129 / 0.12)", fg: "rgb(52 211 153)" }
    : level === "Medium" ? { bg: "rgb(234 179 8 / 0.12)",   fg: "rgb(250 204 21)" }
    :                      { bg: "rgb(239 68 68 / 0.14)",   fg: "rgb(248 113 113)" };
  const text = size === "md" ? "text-[11px] px-2 py-0.5" : "text-[10px] px-1.5 py-0.5";
  return (
    <span
      className={`${text} font-medium uppercase tracking-wider rounded`}
      style={{ background: color.bg, color: color.fg }}
      title={`Danger level: ${level}`}
    >
      {level}
    </span>
  );
}

// ── Copy button ──────────────────────────────────────────────────────────────

function CopyPromptButton({
  prompt,
  disabled,
  variant = "ghost",
  size = "sm",
  compact = false,
}: {
  prompt: string;
  disabled?: boolean;
  variant?: "ghost" | "primary" | "outline" | "secondary";
  size?: "sm" | "md" | "lg";
  compact?: boolean;
}) {
  const [copied, setCopied] = useState(false);

  const onCopy = async () => {
    if (disabled || !prompt) return;
    try {
      await navigator.clipboard.writeText(prompt);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      // Fallback: select-all + execCommand is no longer reliable; silent fail.
    }
  };

  return (
    <Button
      type="button"
      variant={variant}
      size={size}
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation();
        void onCopy();
      }}
      title={disabled ? "No prompt to copy" : "Copy prompt to clipboard"}
    >
      {copied ? (
        <Check className="h-3.5 w-3.5" />
      ) : (
        <Copy className="h-3.5 w-3.5" />
      )}
      {!compact && <span className="ml-1.5">{copied ? "Copied" : "Copy Prompt"}</span>}
    </Button>
  );
}

// ── Runbook card ─────────────────────────────────────────────────────────────

function RunbookCard({
  runbook,
  onOpen,
  onEdit,
  onToggleFavorite,
}: {
  runbook: RunbookDef;
  onOpen: () => void;
  onEdit: () => void;
  onToggleFavorite: () => void;
}) {
  const placeholder = isPlaceholder(runbook);

  return (
    <div
      className="rounded-lg border p-4 flex flex-col gap-3 transition-colors cursor-pointer"
      style={{
        background: "var(--surface)",
        borderColor: "var(--border)",
        opacity: placeholder ? 0.75 : 1,
      }}
      onClick={onOpen}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLElement).style.borderColor = "var(--border-strong, var(--border))";
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLElement).style.borderColor = "var(--border)";
      }}
    >
      {/* Top row: title + favorite */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2 min-w-0">
          <ClipboardList
            className="h-4 w-4 shrink-0 mt-0.5"
            style={{ color: "var(--text-quiet)" }}
          />
          <h3
            className="text-sm font-medium leading-snug truncate"
            style={{ color: "var(--text)" }}
            title={runbook.title}
          >
            {runbook.title}
          </h3>
        </div>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onToggleFavorite();
          }}
          className="shrink-0 rounded p-1 transition-colors"
          title={runbook.favorite ? "Unfavorite" : "Favorite"}
          style={{ color: runbook.favorite ? "rgb(250 204 21)" : "var(--text-quiet)" }}
        >
          <Star
            className="h-3.5 w-3.5"
            fill={runbook.favorite ? "rgb(250 204 21)" : "none"}
          />
        </button>
      </div>

      {/* Category + danger + placeholder badges */}
      <div className="flex items-center gap-2 flex-wrap">
        <span
          className="text-[10px] font-medium uppercase tracking-wider px-1.5 py-0.5 rounded"
          style={{ background: "var(--accent-soft)", color: "var(--accent-strong)" }}
        >
          {runbook.category}
        </span>
        <DangerBadge level={runbook.dangerLevel} />
        {placeholder && (
          <span
            className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded"
            style={{ background: "rgba(148, 163, 184, 0.15)", color: "var(--text-quiet)" }}
          >
            Placeholder
          </span>
        )}
      </div>

      {/* Description */}
      <p
        className="text-xs leading-relaxed line-clamp-2"
        style={{ color: "var(--text-muted)" }}
      >
        {runbook.description || (placeholder ? "Prompt not added yet." : "")}
      </p>

      {/* Approval hint (compact) */}
      {runbook.approvalNote && (
        <p
          className="text-[11px] leading-snug line-clamp-1"
          style={{ color: "var(--text-quiet)" }}
          title={runbook.approvalNote}
        >
          {runbook.approvalNote}
        </p>
      )}

      {/* Footer: last updated + actions */}
      <div className="flex items-center justify-between mt-auto pt-2 gap-2" style={{ borderTop: "1px solid var(--border)" }}>
        <span className="text-[11px]" style={{ color: "var(--text-quiet)" }}>
          Updated {formatDate(runbook.updatedAt)}
        </span>
        <div className="flex items-center gap-1">
          <CopyPromptButton prompt={runbook.prompt} disabled={placeholder} compact />
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={(e) => {
              e.stopPropagation();
              onOpen();
            }}
            title="Open"
          >
            Open
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={(e) => {
              e.stopPropagation();
              onEdit();
            }}
            title="Edit"
          >
            <Pencil className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  );
}

// ── Editor form (shared create/edit) ─────────────────────────────────────────

interface RunbookFormState {
  title: string;
  category: RunbookCategory;
  description: string;
  whenToUse: string;
  warnings: string;
  prompt: string;
  dangerLevel: DangerLevel;
  approvalNote: string;
}

function makeEmptyForm(): RunbookFormState {
  return {
    title: "",
    category: "Diagnostics",
    description: "",
    whenToUse: "",
    warnings: "",
    prompt: "",
    dangerLevel: "Safe",
    approvalNote: "",
  };
}

function runbookToForm(r: RunbookDef): RunbookFormState {
  return {
    title: r.title,
    category: r.category,
    description: r.description,
    whenToUse: r.whenToUse,
    warnings: r.warnings,
    prompt: r.prompt,
    dangerLevel: r.dangerLevel,
    approvalNote: r.approvalNote,
  };
}

function RunbookEditor({
  form,
  setForm,
}: {
  form: RunbookFormState;
  setForm: (f: RunbookFormState) => void;
}) {
  const inputClass =
    "w-full rounded-md px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-[var(--accent)]";
  const inputStyle = {
    background: "var(--surface-2, var(--surface))",
    border: "1px solid var(--border)",
    color: "var(--text)",
  } as const;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <label className="text-xs font-medium block mb-1" style={{ color: "var(--text-muted)" }}>
          Title
        </label>
        <input
          className={inputClass}
          style={inputStyle}
          value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
          placeholder="e.g. Safe Restart"
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-xs font-medium block mb-1" style={{ color: "var(--text-muted)" }}>
            Category
          </label>
          <select
            className={inputClass}
            style={inputStyle}
            value={form.category}
            onChange={(e) => setForm({ ...form, category: e.target.value as RunbookCategory })}
          >
            {RUNBOOK_CATEGORIES.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs font-medium block mb-1" style={{ color: "var(--text-muted)" }}>
            Danger level
          </label>
          <select
            className={inputClass}
            style={inputStyle}
            value={form.dangerLevel}
            onChange={(e) => setForm({ ...form, dangerLevel: e.target.value as DangerLevel })}
          >
            {DANGER_LEVELS.map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label className="text-xs font-medium block mb-1" style={{ color: "var(--text-muted)" }}>
          Approval note
        </label>
        <input
          className={inputClass}
          style={inputStyle}
          value={form.approvalNote}
          onChange={(e) => setForm({ ...form, approvalNote: e.target.value })}
          placeholder="e.g. Ask before running. No deletes, no rebuilds."
        />
      </div>

      <div>
        <label className="text-xs font-medium block mb-1" style={{ color: "var(--text-muted)" }}>
          Short description
        </label>
        <input
          className={inputClass}
          style={inputStyle}
          value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
          placeholder="One-line summary"
        />
      </div>

      <div>
        <label className="text-xs font-medium block mb-1" style={{ color: "var(--text-muted)" }}>
          When to use it
        </label>
        <textarea
          className={inputClass}
          style={{ ...inputStyle, minHeight: 60, fontFamily: "inherit" }}
          value={form.whenToUse}
          onChange={(e) => setForm({ ...form, whenToUse: e.target.value })}
          rows={3}
        />
      </div>

      <div>
        <label className="text-xs font-medium block mb-1" style={{ color: "var(--text-muted)" }}>
          Warnings
        </label>
        <textarea
          className={inputClass}
          style={{ ...inputStyle, minHeight: 60, fontFamily: "inherit" }}
          value={form.warnings}
          onChange={(e) => setForm({ ...form, warnings: e.target.value })}
          rows={3}
        />
      </div>

      <div>
        <label className="text-xs font-medium block mb-1" style={{ color: "var(--text-muted)" }}>
          Full prompt
        </label>
        <textarea
          className={inputClass}
          style={{ ...inputStyle, minHeight: 260, fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 12 }}
          value={form.prompt}
          onChange={(e) => setForm({ ...form, prompt: e.target.value })}
          rows={16}
          placeholder="Paste the full operational prompt here."
        />
      </div>
    </div>
  );
}

// ── View modal ───────────────────────────────────────────────────────────────

function RunbookViewBody({ runbook }: { runbook: RunbookDef }) {
  const placeholder = isPlaceholder(runbook);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2 flex-wrap">
        <span
          className="text-[10px] font-medium uppercase tracking-wider px-1.5 py-0.5 rounded"
          style={{ background: "var(--accent-soft)", color: "var(--accent-strong)" }}
        >
          {runbook.category}
        </span>
        <DangerBadge level={runbook.dangerLevel} size="md" />
        {placeholder && (
          <span
            className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded"
            style={{ background: "rgba(148, 163, 184, 0.15)", color: "var(--text-quiet)" }}
          >
            Placeholder
          </span>
        )}
        <span className="text-[11px]" style={{ color: "var(--text-quiet)" }}>
          Updated {formatDate(runbook.updatedAt)}
        </span>
      </div>

      {runbook.approvalNote && (
        <div>
          <p className="text-xs font-medium uppercase tracking-wider mb-1" style={{ color: "var(--text-quiet)" }}>
            Approval
          </p>
          <p className="text-sm" style={{ color: "var(--text)" }}>{runbook.approvalNote}</p>
        </div>
      )}

      {runbook.description && (
        <div>
          <p className="text-xs font-medium uppercase tracking-wider mb-1" style={{ color: "var(--text-quiet)" }}>
            Description
          </p>
          <p className="text-sm" style={{ color: "var(--text)" }}>{runbook.description}</p>
        </div>
      )}

      {runbook.whenToUse && (
        <div>
          <p className="text-xs font-medium uppercase tracking-wider mb-1" style={{ color: "var(--text-quiet)" }}>
            When to use it
          </p>
          <p className="text-sm whitespace-pre-wrap" style={{ color: "var(--text)" }}>{runbook.whenToUse}</p>
        </div>
      )}

      {runbook.warnings && (
        <div>
          <p className="text-xs font-medium uppercase tracking-wider mb-1" style={{ color: "var(--text-quiet)" }}>
            Warnings
          </p>
          <p className="text-sm whitespace-pre-wrap" style={{ color: "rgb(251 146 60)" }}>{runbook.warnings}</p>
        </div>
      )}

      <div>
        <p className="text-xs font-medium uppercase tracking-wider mb-1" style={{ color: "var(--text-quiet)" }}>
          Full prompt
        </p>
        {placeholder ? (
          <div
            className="rounded-md border p-4 text-sm italic"
            style={{ background: "var(--surface-2, var(--surface))", borderColor: "var(--border)", color: "var(--text-quiet)" }}
          >
            Prompt not added yet.
          </div>
        ) : (
          <pre
            className="rounded-md border p-4 text-xs whitespace-pre-wrap max-h-[50vh] overflow-auto"
            style={{
              background: "var(--surface-2, var(--surface))",
              borderColor: "var(--border)",
              color: "var(--text)",
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
            }}
          >
            {runbook.prompt}
          </pre>
        )}
      </div>
    </div>
  );
}

// ── Main page content ────────────────────────────────────────────────────────

function RunbooksContent() {
  const [runbooks, setRunbooks] = useState<RunbookDef[]>([]);
  const [loaded, setLoaded] = useState(false);

  const [query, setQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>("All");

  const [viewingId, setViewingId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null); // null = not editing; "new" = creating
  const [form, setForm] = useState<RunbookFormState>(makeEmptyForm);

  // Load on mount
  useEffect(() => {
    setRunbooks(loadRunbooks());
    setLoaded(true);
  }, []);

  // Persist whenever runbooks change (after initial load)
  useEffect(() => {
    if (!loaded) return;
    saveRunbooks(runbooks);
  }, [runbooks, loaded]);

  const viewing = useMemo(
    () => runbooks.find((r) => r.id === viewingId) ?? null,
    [runbooks, viewingId],
  );

  const filtered = useMemo(() => {
    const list = runbooks.filter(
      (r) =>
        (categoryFilter === "All" || r.category === categoryFilter) &&
        matchesQuery(r, query),
    );
    return [...list].sort(compareRunbooks);
  }, [runbooks, query, categoryFilter]);

  const handleToggleFavorite = (id: string) => {
    const r = runbooks.find((x) => x.id === id);
    if (!r) return;
    const updated = updateRunbook(id, { favorite: !r.favorite });
    if (updated) {
      setRunbooks((prev) => prev.map((x) => (x.id === id ? updated : x)));
    }
  };

  const handleOpenEdit = (r: RunbookDef) => {
    setForm(runbookToForm(r));
    setEditingId(r.id);
  };

  const handleOpenCreate = () => {
    setForm(makeEmptyForm());
    setEditingId("new");
  };

  const handleSave = () => {
    const title = form.title.trim();
    if (!title) return;
    if (editingId === "new") {
      const created = createRunbook(
        title,
        form.category,
        form.description,
        form.prompt,
        form.whenToUse,
        form.warnings,
        form.dangerLevel,
        form.approvalNote,
      );
      setRunbooks((prev) => [...prev, created]);
    } else if (editingId) {
      const updated = updateRunbook(editingId, {
        title,
        category: form.category,
        description: form.description.trim(),
        whenToUse: form.whenToUse.trim(),
        warnings: form.warnings.trim(),
        prompt: form.prompt,
        dangerLevel: form.dangerLevel,
        approvalNote: form.approvalNote.trim(),
      });
      if (updated) {
        setRunbooks((prev) => prev.map((x) => (x.id === editingId ? updated : x)));
      }
    }
    setEditingId(null);
  };

  const handleDelete = (id: string) => {
    if (!confirm("Delete this runbook?")) return;
    if (deleteRunbook(id)) {
      setRunbooks((prev) => prev.filter((r) => r.id !== id));
      if (viewingId === id) setViewingId(null);
      if (editingId === id) setEditingId(null);
    }
  };

  return (
    <div className="px-6 py-6 max-w-6xl mx-auto w-full">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight" style={{ color: "var(--text)" }}>
            Runbooks
          </h1>
          <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
            Saved prompts and operating procedures for checking, restarting, repairing, and managing OpenClaw.
          </p>
        </div>
        <Button onClick={handleOpenCreate} size="sm">
          <Plus className="h-4 w-4 mr-1" />
          New Runbook
        </Button>
      </div>

      {/* ── Search ─────────────────────────────────────────────────────── */}
      <div className="mb-4 relative">
        <Search
          className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 pointer-events-none"
          style={{ color: "var(--text-quiet)" }}
        />
        <input
          type="text"
          placeholder="Search by title, category, or description..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full rounded-md pl-9 pr-3 py-2 text-sm outline-none focus:ring-1 focus:ring-[var(--accent)]"
          style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            color: "var(--text)",
          }}
        />
      </div>

      {/* ── Category filter tabs ──────────────────────────────────────── */}
      <div className="mb-6 flex items-center gap-1.5 flex-wrap">
        {CATEGORY_FILTERS.map((c) => {
          const active = c === categoryFilter;
          return (
            <button
              key={c}
              type="button"
              onClick={() => setCategoryFilter(c)}
              className="text-xs px-2.5 py-1 rounded-md transition-colors"
              style={
                active
                  ? { background: "var(--accent-soft)", color: "var(--accent-strong)", border: "1px solid var(--accent-soft)" }
                  : { background: "transparent", color: "var(--text-muted)", border: "1px solid var(--border)" }
              }
            >
              {c}
            </button>
          );
        })}
      </div>

      {/* ── Cards grid ─────────────────────────────────────────────────── */}
      {filtered.length === 0 ? (
        <div
          className="rounded-lg border p-10 text-center"
          style={{ background: "var(--surface)", borderColor: "var(--border)" }}
        >
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            No runbooks match your filters.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {filtered.map((r) => (
            <RunbookCard
              key={r.id}
              runbook={r}
              onOpen={() => setViewingId(r.id)}
              onEdit={() => handleOpenEdit(r)}
              onToggleFavorite={() => handleToggleFavorite(r.id)}
            />
          ))}
        </div>
      )}

      {/* ── View modal ─────────────────────────────────────────────────── */}
      <Dialog open={!!viewing} onOpenChange={(open) => !open && setViewingId(null)}>
        {viewing && (
          <DialogContent className="max-w-3xl">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <ClipboardList className="h-4 w-4" />
                {viewing.title}
              </DialogTitle>
            </DialogHeader>
            <RunbookViewBody runbook={viewing} />
            <DialogFooter className="flex items-center justify-between w-full gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => handleDelete(viewing.id)}
                title="Delete"
              >
                <Trash2 className="h-3.5 w-3.5 mr-1" />
                Delete
              </Button>
              <div className="flex items-center gap-2">
                <CopyPromptButton prompt={viewing.prompt} disabled={isPlaceholder(viewing)} />
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    handleOpenEdit(viewing);
                    setViewingId(null);
                  }}
                >
                  <Pencil className="h-3.5 w-3.5 mr-1" />
                  Edit
                </Button>
              </div>
            </DialogFooter>
          </DialogContent>
        )}
      </Dialog>

      {/* ── Editor modal (create or edit) ──────────────────────────────── */}
      <Dialog open={!!editingId} onOpenChange={(open) => !open && setEditingId(null)}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>
              {editingId === "new" ? "New Runbook" : "Edit Runbook"}
            </DialogTitle>
          </DialogHeader>
          <RunbookEditor form={form} setForm={setForm} />
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setEditingId(null)}>
              Cancel
            </Button>
            <Button size="sm" onClick={handleSave} disabled={!form.title.trim()}>
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ── Page export ──────────────────────────────────────────────────────────────

export default function RunbooksPage() {
  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel message="Sign in to access Runbooks" forceRedirectUrl="/runbooks" />
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <ErrorBoundary>
          <RunbooksContent />
        </ErrorBoundary>
      </SignedIn>
    </DashboardShell>
  );
}

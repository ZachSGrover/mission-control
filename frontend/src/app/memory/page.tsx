"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";
import { Trash2, Plus, RefreshCw, Sparkles, MessageSquare, ChevronDown, ChevronUp, FolderOpen } from "lucide-react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import {
  type GeneratedJournalEntry,
  type MemoryEntry,
  type MemoryType,
  entryArea,
  entryProject,
  formatJournalDate,
  loadGeneratedJournal,
  loadMemory,
  saveGeneratedJournal,
  saveMemory,
  todayDateString,
  upsertGeneratedJournalEntry,
} from "@/lib/memory-store";
import {
  collectActivityForDate,
  generateJournalEntry,
} from "@/lib/journal-generator";

// ── Memory constants ──────────────────────────────────────────────────────────

const MEMORY_TYPES: MemoryType[] = ["context", "decision", "note"];

const MEMORY_TYPE_LABELS: Record<MemoryType, string> = {
  context:  "Context",
  decision: "Decision",
  note:     "Note",
  journal:  "Journal",
};

const MEMORY_TYPE_DOT: Record<MemoryType, string> = {
  context:  "bg-blue-500",
  decision: "bg-amber-500",
  note:     "bg-slate-400",
  journal:  "bg-emerald-500",
};

const MEMORY_TYPE_BADGE: Record<MemoryType, string> = {
  context:  "text-blue-400 bg-blue-500/10",
  decision: "text-amber-400 bg-amber-500/10",
  note:     "text-slate-400 bg-slate-500/10",
  journal:  "text-emerald-400 bg-emerald-500/10",
};

// ── Grouping helper ───────────────────────────────────────────────────────────

function groupEntries(entries: MemoryEntry[]): Map<string, Map<string, MemoryEntry[]>> {
  const result = new Map<string, Map<string, MemoryEntry[]>>();
  for (const entry of entries) {
    if (entry.type === "journal") continue;
    const project = entryProject(entry);
    const area = entryArea(entry);
    if (!result.has(project)) result.set(project, new Map());
    const projectMap = result.get(project)!;
    if (!projectMap.has(area)) projectMap.set(area, []);
    projectMap.get(area)!.push(entry);
  }
  // Sort: "General" last, others alphabetical
  const sorted = new Map(
    [...result.entries()].sort(([a], [b]) => {
      if (a === "General" && b !== "General") return 1;
      if (b === "General" && a !== "General") return -1;
      return a.localeCompare(b);
    }),
  );
  return sorted;
}

// ── Area section ──────────────────────────────────────────────────────────────

function AreaSection({
  area,
  entries,
  onDelete,
}: {
  area: string;
  entries: MemoryEntry[];
  onDelete: (id: string) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className="space-y-1.5">
      <button
        type="button"
        onClick={() => setCollapsed((v) => !v)}
        className="flex items-center gap-2 w-full text-left group"
      >
        <span className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>
          {area}
        </span>
        <span className="text-[10px] tabular-nums px-1.5 py-0.5 rounded" style={{ background: "var(--surface-muted)", color: "var(--text-quiet)" }}>
          {entries.length}
        </span>
        <span className="ml-auto opacity-0 group-hover:opacity-100 transition-opacity" style={{ color: "var(--text-quiet)" }}>
          {collapsed ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" />}
        </span>
      </button>

      {!collapsed && (
        <div className="space-y-1.5 pl-3 border-l" style={{ borderColor: "var(--border)" }}>
          {entries.map((entry) => (
            <div
              key={entry.id}
              className="flex items-start gap-3 rounded-xl px-4 py-3"
              style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}
            >
              {/* Type badge */}
              <span
                className={`text-[9px] font-bold uppercase tracking-wide rounded px-1.5 py-0.5 shrink-0 mt-0.5 ${MEMORY_TYPE_BADGE[entry.type] ?? ""}`}
              >
                {MEMORY_TYPE_LABELS[entry.type]}
              </span>
              <p className="flex-1 text-sm leading-relaxed" style={{ color: "var(--text)" }}>
                {entry.content}
              </p>
              <button
                type="button"
                onClick={() => onDelete(entry.id)}
                className="shrink-0 rounded-md p-1 transition-opacity hover:opacity-70 mt-0.5"
                style={{ color: "var(--text-quiet)" }}
                title="Delete"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Project section ───────────────────────────────────────────────────────────

function ProjectSection({
  project,
  areaMap,
  onDelete,
}: {
  project: string;
  areaMap: Map<string, MemoryEntry[]>;
  onDelete: (id: string) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const totalCount = [...areaMap.values()].reduce((acc, arr) => acc + arr.length, 0);

  // Sort areas: "Unsorted" last
  const sortedAreas = [...areaMap.entries()].sort(([a], [b]) => {
    if (a === "Unsorted" && b !== "Unsorted") return 1;
    if (b === "Unsorted" && a !== "Unsorted") return -1;
    return a.localeCompare(b);
  });

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ background: "var(--surface)", border: "1px solid var(--border-strong)" }}
    >
      {/* Project header */}
      <button
        type="button"
        onClick={() => setCollapsed((v) => !v)}
        className="w-full flex items-center gap-3 px-5 py-3.5 text-left"
        style={{ background: "var(--surface-strong)" }}
      >
        <FolderOpen className="h-4 w-4 shrink-0" style={{ color: "var(--accent)" }} />
        <span className="text-sm font-semibold" style={{ color: "var(--text)" }}>{project}</span>
        <span
          className="text-[10px] tabular-nums px-1.5 py-0.5 rounded"
          style={{ background: "color-mix(in srgb, var(--accent) 15%, transparent)", color: "var(--accent)" }}
        >
          {totalCount}
        </span>
        <span className="ml-auto" style={{ color: "var(--text-quiet)" }}>
          {collapsed ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronUp className="h-3.5 w-3.5" />}
        </span>
      </button>

      {/* Areas */}
      {!collapsed && (
        <div className="px-5 py-4 space-y-4">
          {sortedAreas.map(([area, entries]) => (
            <AreaSection key={area} area={area} entries={entries} onDelete={onDelete} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Memory tab ────────────────────────────────────────────────────────────────

const KNOWN_PROJECTS = ["General", "Digidle", "Modern Sales Agency", "Modern Athlete"];
const KNOWN_AREAS    = ["General", "Strategy", "Content", "Analysis", "Decision", "Product", "Unsorted"];

function MemoryTab() {
  const [entries, setEntries] = useState<MemoryEntry[]>([]);
  const [mounted, setMounted] = useState(false);

  // Add form
  const [adding, setAdding] = useState(false);
  const [newType, setNewType] = useState<MemoryType>("context");
  const [newContent, setNewContent] = useState("");
  const [newProject, setNewProject] = useState("General");
  const [newArea, setNewArea] = useState("General");

  // Filters
  const [filterProject, setFilterProject] = useState("all");
  const [filterArea, setFilterArea]       = useState("all");

  useEffect(() => {
    setMounted(true);
    setEntries(loadMemory());
  }, []);

  const persist = useCallback((next: MemoryEntry[]) => {
    setEntries(next);
    saveMemory(next);
  }, []);

  const handleAdd = () => {
    const trimmed = newContent.trim();
    if (!trimmed) return;
    const entry: MemoryEntry = {
      id: crypto.randomUUID(),
      type: newType,
      content: trimmed,
      createdAt: new Date().toISOString(),
      project: newProject,
      area: newArea,
      embedding: null,
    };
    persist([entry, ...entries]);
    setNewContent("");
    setAdding(false);
  };

  const handleDelete = useCallback((id: string) => {
    persist(entries.filter((e) => e.id !== id));
  }, [entries, persist]);

  if (!mounted) {
    return <div className="h-40" />;
  }

  // Build filter options from actual data
  const allProjects = ["all", ...new Set(entries.filter((e) => e.type !== "journal").map(entryProject)).values()].sort((a, b) => a === "all" ? -1 : b === "all" ? 1 : a.localeCompare(b));
  const allAreas    = ["all", ...new Set(entries.filter((e) => e.type !== "journal" && (filterProject === "all" || entryProject(e) === filterProject)).map(entryArea)).values()].sort((a, b) => a === "all" ? -1 : b === "all" ? 1 : a.localeCompare(b));

  // Apply filters
  const filtered = entries.filter((e) => {
    if (e.type === "journal") return false;
    if (filterProject !== "all" && entryProject(e) !== filterProject) return false;
    if (filterArea !== "all" && entryArea(e) !== filterArea) return false;
    return true;
  });

  const grouped = groupEntries(filtered);
  const totalCount = filtered.length;

  return (
    <div className="space-y-5">
      {/* Toolbar */}
      <div className="flex items-center gap-2 flex-wrap">
        {/* Project filter */}
        <select
          value={filterProject}
          onChange={(e) => { setFilterProject(e.target.value); setFilterArea("all"); }}
          className="rounded-lg px-3 py-1.5 text-xs focus:outline-none"
          style={{ background: "var(--surface-strong)", border: "1px solid var(--border)", color: "var(--text)" }}
        >
          {allProjects.map((p) => <option key={p} value={p}>{p === "all" ? "All Projects" : p}</option>)}
        </select>

        {/* Area filter */}
        <select
          value={filterArea}
          onChange={(e) => setFilterArea(e.target.value)}
          className="rounded-lg px-3 py-1.5 text-xs focus:outline-none"
          style={{ background: "var(--surface-strong)", border: "1px solid var(--border)", color: "var(--text)" }}
        >
          {allAreas.map((a) => <option key={a} value={a}>{a === "all" ? "All Areas" : a}</option>)}
        </select>

        <span className="text-[10px] tabular-nums" style={{ color: "var(--text-quiet)" }}>
          {totalCount} {totalCount === 1 ? "entry" : "entries"}
        </span>

        <button
          type="button"
          onClick={() => setAdding((v) => !v)}
          className="ml-auto flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium text-white transition-opacity hover:opacity-80"
          style={{ background: "var(--accent)" }}
        >
          <Plus className="h-3.5 w-3.5" />Add
        </button>
      </div>

      {/* Add form */}
      {adding && (
        <div className="rounded-xl p-4 space-y-3" style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}>
          {/* Type */}
          <div className="flex gap-2 flex-wrap">
            {MEMORY_TYPES.map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setNewType(t)}
                className="rounded-md px-3 py-1.5 text-xs font-medium transition-colors"
                style={newType === t
                  ? { background: "var(--accent)", color: "#fff" }
                  : { background: "var(--surface-muted)", color: "var(--text-muted)", border: "1px solid var(--border-strong)" }
                }
              >
                {MEMORY_TYPE_LABELS[t]}
              </button>
            ))}
          </div>

          {/* Project + Area */}
          <div className="flex gap-2">
            <div className="flex-1">
              <label className="block text-[10px] font-semibold uppercase tracking-wide mb-1" style={{ color: "var(--text-quiet)" }}>Project</label>
              <select
                value={newProject}
                onChange={(e) => setNewProject(e.target.value)}
                className="w-full rounded-lg px-3 py-1.5 text-xs focus:outline-none"
                style={{ background: "var(--surface-muted)", border: "1px solid var(--border-strong)", color: "var(--text)" }}
              >
                {KNOWN_PROJECTS.map((p) => <option key={p}>{p}</option>)}
              </select>
            </div>
            <div className="flex-1">
              <label className="block text-[10px] font-semibold uppercase tracking-wide mb-1" style={{ color: "var(--text-quiet)" }}>Area</label>
              <select
                value={newArea}
                onChange={(e) => setNewArea(e.target.value)}
                className="w-full rounded-lg px-3 py-1.5 text-xs focus:outline-none"
                style={{ background: "var(--surface-muted)", border: "1px solid var(--border-strong)", color: "var(--text)" }}
              >
                {KNOWN_AREAS.map((a) => <option key={a}>{a}</option>)}
              </select>
            </div>
          </div>

          {/* Content */}
          <textarea
            rows={3}
            value={newContent}
            onChange={(e) => setNewContent(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                handleAdd();
              }
            }}
            placeholder={`Add a ${MEMORY_TYPE_LABELS[newType].toLowerCase()}…`}
            className="w-full resize-none rounded-lg px-3 py-2 text-sm focus:outline-none"
            style={{ background: "var(--surface-muted)", border: "1px solid var(--border-strong)", color: "var(--text)" }}
            autoFocus
          />

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => { setAdding(false); setNewContent(""); }}
              className="rounded-lg px-3 py-1.5 text-sm"
              style={{ color: "var(--text-muted)" }}
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleAdd}
              disabled={!newContent.trim()}
              className="rounded-lg px-4 py-1.5 text-sm font-medium text-white disabled:opacity-40"
              style={{ background: "var(--accent)" }}
            >
              Save
            </button>
          </div>
        </div>
      )}

      {/* Empty state */}
      {totalCount === 0 && !adding && (
        <div
          className="rounded-xl px-6 py-12 text-center"
          style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}
        >
          <p className="text-sm" style={{ color: "var(--text-quiet)" }}>
            {entries.filter((e) => e.type !== "journal").length === 0
              ? "No memory entries yet. Add context, decisions, or notes to inject them into all AI conversations."
              : "No entries match the current filters."}
          </p>
        </div>
      )}

      {/* Grouped by project → area */}
      {grouped.size > 0 && (
        <div className="space-y-3">
          {[...grouped.entries()].map(([project, areaMap]) => (
            <ProjectSection key={project} project={project} areaMap={areaMap} onDelete={handleDelete} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Journal category pill ─────────────────────────────────────────────────────

const CAT_COLORS: Record<string, string> = {
  actions:   "text-blue-400 bg-blue-500/10",
  decisions: "text-amber-400 bg-amber-500/10",
  insights:  "text-violet-400 bg-violet-500/10",
  themes:    "text-emerald-400 bg-emerald-500/10",
};

const CAT_LABELS: Record<string, string> = {
  actions:   "Actions",
  decisions: "Decisions",
  insights:  "Insights",
  themes:    "Themes",
};

// ── Journal entry card ────────────────────────────────────────────────────────

function JournalEntryCard({
  entry,
  onDelete,
  onRegenerate,
  isRegenerating,
}: {
  entry: GeneratedJournalEntry;
  onDelete: () => void;
  onRegenerate?: () => void;
  isRegenerating?: boolean;
}) {
  const isToday = entry.date === todayDateString();
  const { categories } = entry;
  const hasItems =
    categories.actions.length > 0 ||
    categories.decisions.length > 0 ||
    categories.insights.length > 0 ||
    categories.themes.length > 0;

  return (
    <div className="rounded-xl p-5 space-y-4" style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}>
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1 flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>
              {formatJournalDate(entry.date)}
            </span>
            <span className="text-xs tabular-nums" style={{ color: "var(--text-quiet)" }}>{entry.date}</span>
            <span className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded" style={{ background: "var(--surface-muted)", color: "var(--text-quiet)" }}>
              <MessageSquare className="h-2.5 w-2.5" />
              {entry.messageCount} messages
            </span>
          </div>
          <p className="text-sm font-medium leading-snug" style={{ color: "var(--text)" }}>{entry.headline}</p>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {isToday && onRegenerate && (
            <button type="button" onClick={onRegenerate} disabled={isRegenerating} title="Regenerate" className="rounded-md p-1.5 transition-opacity hover:opacity-70 disabled:opacity-40" style={{ color: "var(--text-quiet)" }}>
              <RefreshCw className={`h-3.5 w-3.5 ${isRegenerating ? "animate-spin" : ""}`} />
            </button>
          )}
          <button type="button" onClick={onDelete} title="Delete" className="rounded-md p-1.5 transition-opacity hover:opacity-70" style={{ color: "var(--text-quiet)" }}>
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {entry.summary && (
        <p className="text-sm leading-relaxed" style={{ color: "var(--text-muted)" }}>{entry.summary}</p>
      )}

      {hasItems && (
        <div className="space-y-3 pt-1">
          {(["actions", "decisions", "insights", "themes"] as const).map((cat) => {
            const items = categories[cat];
            if (!items.length) return null;
            return (
              <div key={cat} className="space-y-1.5">
                <p className={`text-[10px] font-semibold uppercase tracking-widest ${CAT_COLORS[cat].split(" ")[0]}`}>
                  {CAT_LABELS[cat]}
                </p>
                <ul className="space-y-1">
                  {items.map((item, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm" style={{ color: "var(--text)" }}>
                      <span className="mt-1.5 h-1 w-1 rounded-full shrink-0" style={{ background: "var(--text-quiet)" }} />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      )}

      <p className="text-[10px] tabular-nums" style={{ color: "var(--text-quiet)" }}>
        Generated {new Date(entry.generatedAt).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}
      </p>
    </div>
  );
}

// ── Journal tab ───────────────────────────────────────────────────────────────

function JournalTab() {
  const [entries, setEntries] = useState<GeneratedJournalEntry[]>([]);
  const [mounted, setMounted] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [regeneratingId, setRegeneratingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [todayCount, setTodayCount] = useState(0);

  useEffect(() => {
    setMounted(true);
    setEntries(loadGeneratedJournal());
    setTodayCount(collectActivityForDate().length);
  }, []);

  const persist = useCallback((next: GeneratedJournalEntry[]) => {
    setEntries(next);
    saveGeneratedJournal(next);
  }, []);

  const handleGenerate = useCallback(async (isRegen = false, existingId?: string) => {
    const today = todayDateString();
    const messages = collectActivityForDate(today);
    if (messages.length === 0) {
      setError("No AI conversations found for today. Have a chat with Claude, ChatGPT, or Gemini first.");
      return;
    }
    setError(null);
    if (isRegen && existingId) setRegeneratingId(existingId);
    else setIsGenerating(true);
    try {
      const memory = loadMemory();
      const entry = await generateJournalEntry(today, messages, memory);
      setEntries((prev) => upsertGeneratedJournalEntry(prev, entry));
      setTodayCount(messages.length);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate journal.");
    } finally {
      setIsGenerating(false);
      setRegeneratingId(null);
    }
  }, []);

  const handleDelete = useCallback((date: string) => {
    persist(entries.filter((e) => e.date !== date));
  }, [entries, persist]);

  if (!mounted) return <div className="h-40" />;

  const today = todayDateString();
  const todayEntry = entries.find((e) => e.date === today);
  const pastEntries = entries.filter((e) => e.date !== today).sort((a, b) => b.date.localeCompare(a.date));
  const isBusy = isGenerating || regeneratingId !== null;

  return (
    <div className="space-y-6">
      {/* Generate today banner */}
      <div className="rounded-xl p-4 space-y-3" style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}>
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1">
            <p className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>Today — {today}</p>
            <p className="text-sm" style={{ color: "var(--text-muted)" }}>
              {todayCount > 0
                ? `${todayCount} message${todayCount !== 1 ? "s" : ""} available from today's conversations.`
                : "No AI conversations yet today. Start a chat to generate your journal."}
            </p>
          </div>
          <button
            type="button"
            onClick={() => void handleGenerate(false)}
            disabled={isBusy || todayCount === 0}
            className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium text-white transition-opacity hover:opacity-80 disabled:opacity-40 shrink-0"
            style={{ background: "var(--accent)" }}
          >
            {isGenerating ? <><RefreshCw className="h-3.5 w-3.5 animate-spin" />Generating…</> : <><Sparkles className="h-3.5 w-3.5" />{todayEntry ? "Regenerate Today" : "Generate Today"}</>}
          </button>
        </div>
        {error && (
          <p className="text-sm rounded-lg px-3 py-2" style={{ background: "var(--surface-muted)", color: "var(--error, #f87171)" }}>
            {error}
          </p>
        )}
      </div>

      {todayEntry && (
        <JournalEntryCard
          entry={todayEntry}
          onDelete={() => handleDelete(todayEntry.date)}
          onRegenerate={() => void handleGenerate(true, todayEntry.id)}
          isRegenerating={regeneratingId === todayEntry.id}
        />
      )}

      {pastEntries.length > 0 && (
        <section className="space-y-3">
          <div className="flex items-center gap-3">
            <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>Archive</span>
            <div className="flex-1 h-px" style={{ background: "var(--border)" }} />
          </div>
          <div className="space-y-3">
            {pastEntries.map((entry) => (
              <JournalEntryCard key={entry.id} entry={entry} onDelete={() => handleDelete(entry.date)} />
            ))}
          </div>
        </section>
      )}

      {entries.length === 0 && (
        <div className="rounded-xl px-6 py-12 text-center space-y-2" style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}>
          <Sparkles className="h-6 w-6 mx-auto" style={{ color: "var(--text-quiet)" }} />
          <p className="text-sm font-medium" style={{ color: "var(--text)" }}>No journal entries yet</p>
          <p className="text-sm" style={{ color: "var(--text-quiet)" }}>Have some AI conversations, then click &ldquo;Generate Today&rdquo; to create your first entry.</p>
        </div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

type Tab = "memory" | "journal";

export default function MemoryPage() {
  const [tab, setTab] = useState<Tab>("memory");

  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel message="Sign in to access Digital OS" forceRedirectUrl="/memory" />
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <main className="flex-1 overflow-y-auto" style={{ background: "var(--bg)" }}>
          <div className="max-w-2xl mx-auto px-6 py-8 space-y-6">
            {/* Header */}
            <div>
              <h1 className="text-xl font-semibold" style={{ color: "var(--text)" }}>Memory</h1>
              <p className="mt-1 text-sm" style={{ color: "var(--text-muted)" }}>
                {tab === "memory"
                  ? "Persistent context organized by project and area, injected into every AI conversation."
                  : "AI-generated daily journal of your conversations and decisions."}
              </p>
            </div>

            {/* Tab switcher */}
            <div className="flex gap-1 p-1 rounded-lg w-fit" style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}>
              {(["memory", "journal"] as Tab[]).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setTab(t)}
                  className="rounded-md px-4 py-1.5 text-sm font-medium capitalize transition-colors"
                  style={tab === t ? { background: "var(--accent)", color: "#fff" } : { color: "var(--text-muted)" }}
                >
                  {t === "memory" ? "Memory" : "Journal"}
                </button>
              ))}
            </div>

            {tab === "memory" ? <MemoryTab /> : <JournalTab />}

            {/* ── Obsidian Vault (planned) ─────────────────────────────── */}
            <section
              className="rounded-xl p-5 space-y-3"
              style={{ background: "var(--surface-strong)", border: "1px dashed var(--border-strong)" }}
            >
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
                  Obsidian Vault
                </h2>
                <span
                  className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider"
                  style={{ background: "rgba(234,179,8,0.15)", color: "#eab308" }}
                  title="Obsidian integration is not wired yet. See Guide → Obsidian Setup."
                >
                  Not connected yet
                </span>
              </div>
              <p className="text-xs leading-relaxed" style={{ color: "var(--text-muted)" }}>
                Your real long-term memory will live in your Obsidian vault. Once connected,
                Digital OS will read markdown files locally (never uploaded), show the folder tree
                here, let you search, and inject selected notes into Claw&apos;s context.
              </p>
              <ul
                className="text-xs space-y-1 pl-5 list-disc"
                style={{ color: "var(--text-quiet)" }}
              >
                <li>Add vault path (coming soon)</li>
                <li>Sync notes</li>
                <li>Search vault</li>
                <li>Inject selected notes into Claw</li>
              </ul>
              <a
                href="/guide#obsidian"
                className="inline-block text-xs font-medium"
                style={{ color: "var(--accent-strong)" }}
              >
                See the Obsidian setup plan →
              </a>
            </section>
          </div>
        </main>
      </SignedIn>
    </DashboardShell>
  );
}

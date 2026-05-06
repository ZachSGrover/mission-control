"use client";

export const dynamic = "force-dynamic";

import { useEffect, useMemo, useState } from "react";
import {
  CalendarDays,
  CheckCircle2,
  Clock,
  FolderOpen,
  Zap,
} from "lucide-react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { entryProject, inferProject, loadMemory, type MemoryEntry } from "@/lib/memory-store";
import { loadOperatorSessions, type OperatorSession } from "@/lib/operator-store";

// ── Project color ─────────────────────────────────────────────────────────────

const PROJECT_COLOR: Record<string, string> = {
  "Digidle":              "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  "Modern Sales Agency":  "bg-blue-500/20 text-blue-400 border-blue-500/30",
  "Modern Athlete":       "bg-orange-500/20 text-orange-400 border-orange-500/30",
  "Grover Art Projects":  "bg-purple-500/20 text-purple-400 border-purple-500/30",
  "General":              "bg-slate-500/15 text-slate-400 border-slate-500/20",
};

const PROJECT_DOT: Record<string, string> = {
  "Digidle":              "bg-emerald-400",
  "Modern Sales Agency":  "bg-blue-400",
  "Modern Athlete":       "bg-orange-400",
  "Grover Art Projects":  "bg-purple-400",
  "General":              "bg-slate-400",
};

// ── Timeline event ────────────────────────────────────────────────────────────

interface TimelineEvent {
  id: string;
  date: string;        // ISO
  dateLabel: string;   // "Apr 10"
  type: "operator" | "memory";
  project: string;
  title: string;
  subtitle?: string;
  meta?: string;
}

function buildEvents(entries: MemoryEntry[], sessions: OperatorSession[]): TimelineEvent[] {
  const events: TimelineEvent[] = [];

  // Operator sessions
  for (const s of sessions) {
    const project = inferProject(s.objective + " " + (s.goal ?? ""));
    const date = s.completedAt ?? s.createdAt;
    events.push({
      id: `sess-${s.id}`,
      date,
      dateLabel: formatDateLabel(date),
      type: "operator",
      project,
      title: s.objective,
      subtitle: s.goal && s.goal !== s.objective ? s.goal : undefined,
      meta: `${s.steps.filter((st) => st.status === "done").length}/${s.steps.length} steps · ${s.phase}`,
    });
  }

  // Memory entries (group by day, show most recent per day per project)
  const dayProjectSeen = new Set<string>();
  const sortedEntries = [...entries]
    .filter((e) => e.type !== "journal")
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt));

  for (const e of sortedEntries) {
    const project = entryProject(e);
    const day = e.createdAt.slice(0, 10);
    const key = `${day}-${project}`;
    if (dayProjectSeen.has(key)) continue;
    dayProjectSeen.add(key);
    events.push({
      id: `mem-${e.id}`,
      date: e.createdAt,
      dateLabel: formatDateLabel(e.createdAt),
      type: "memory",
      project,
      title: `${project} — memory updated`,
      subtitle: e.content.slice(0, 80) + (e.content.length > 80 ? "…" : ""),
      meta: e.type,
    });
  }

  return events.sort((a, b) => b.date.localeCompare(a.date));
}

function formatDateLabel(iso: string): string {
  try {
    const d = new Date(iso);
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);
    if (d.toDateString() === today.toDateString()) return "Today";
    if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  } catch { return ""; }
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  } catch { return ""; }
}

// ── Calendar grid ─────────────────────────────────────────────────────────────

function MiniCalendar({
  events,
  selectedMonth,
}: {
  events: TimelineEvent[];
  selectedMonth: Date;
}) {
  const year = selectedMonth.getFullYear();
  const month = selectedMonth.getMonth();

  const firstDay = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const today = new Date();

  // Days that have events
  const activeDays = new Set(
    events
      .filter((e) => {
        const d = new Date(e.date);
        return d.getFullYear() === year && d.getMonth() === month;
      })
      .map((e) => new Date(e.date).getDate()),
  );

  const cells: (number | null)[] = [
    ...Array(firstDay).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];

  return (
    <div className="rounded-xl p-4 space-y-3" style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}>
      <p className="text-xs font-semibold text-center" style={{ color: "var(--text)" }}>
        {selectedMonth.toLocaleDateString("en-US", { month: "long", year: "numeric" })}
      </p>

      {/* Day labels */}
      <div className="grid grid-cols-7 gap-0.5">
        {["S", "M", "T", "W", "T", "F", "S"].map((d, i) => (
          <div key={i} className="text-center text-[10px] font-semibold py-0.5" style={{ color: "var(--text-quiet)" }}>
            {d}
          </div>
        ))}
        {cells.map((day, i) => {
          if (!day) return <div key={`empty-${i}`} />;
          const isToday = today.getDate() === day && today.getMonth() === month && today.getFullYear() === year;
          const hasEvent = activeDays.has(day);
          return (
            <div
              key={day}
              className="relative flex items-center justify-center rounded-md py-1 text-[11px] tabular-nums"
              style={{
                background: isToday ? "var(--accent)" : "transparent",
                color: isToday ? "#fff" : hasEvent ? "var(--text)" : "var(--text-quiet)",
                fontWeight: hasEvent || isToday ? 600 : 400,
              }}
            >
              {day}
              {hasEvent && !isToday && (
                <span className="absolute bottom-0.5 left-1/2 -translate-x-1/2 h-1 w-1 rounded-full" style={{ background: "var(--accent)" }} />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Event row ─────────────────────────────────────────────────────────────────

function EventRow({ event }: { event: TimelineEvent }) {
  const colors = PROJECT_COLOR[event.project] ?? PROJECT_COLOR["General"]!;
  const dot    = PROJECT_DOT[event.project]  ?? PROJECT_DOT["General"]!;

  return (
    <div
      className="flex items-start gap-3 rounded-xl px-4 py-3"
      style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}
    >
      {/* Icon */}
      <div className="shrink-0 mt-0.5">
        {event.type === "operator"
          ? <Zap className="h-4 w-4" style={{ color: "var(--accent)" }} />
          : <FolderOpen className="h-4 w-4" style={{ color: "var(--text-quiet)" }} />
        }
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <p className="text-sm leading-snug font-medium" style={{ color: "var(--text)" }}>
          {event.title}
        </p>
        {event.subtitle && (
          <p className="text-xs mt-0.5 leading-snug" style={{ color: "var(--text-quiet)" }}>
            {event.subtitle}
          </p>
        )}
        <div className="flex items-center gap-2 mt-1.5 flex-wrap">
          <span className={`text-[9px] font-bold uppercase tracking-wide rounded border px-1.5 py-0.5 ${colors}`}>
            {event.project}
          </span>
          {event.meta && (
            <span className="text-[10px]" style={{ color: "var(--text-quiet)" }}>{event.meta}</span>
          )}
        </div>
      </div>

      {/* Time */}
      <div className="shrink-0 text-right">
        <p className="text-[10px] tabular-nums" style={{ color: "var(--text-quiet)" }}>
          {formatTime(event.date)}
        </p>
      </div>
    </div>
  );
}

// ── Calendar content ──────────────────────────────────────────────────────────

function CalendarContent() {
  const [memEntries, setMemEntries] = useState<MemoryEntry[]>([]);
  const [sessions, setSessions] = useState<OperatorSession[]>([]);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    // Hydration + load from localStorage on mount — the documented pattern.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMounted(true);
    try { setMemEntries(loadMemory()); } catch { /* ignore */ }
    try { setSessions(loadOperatorSessions()); } catch { /* ignore */ }
  }, []);

  const events = useMemo(
    () => (mounted ? buildEvents(memEntries, sessions) : []),
    [memEntries, sessions, mounted],
  );

  // Group events by dateLabel
  const groupedEvents = useMemo(() => {
    const map = new Map<string, TimelineEvent[]>();
    for (const e of events) {
      if (!map.has(e.dateLabel)) map.set(e.dateLabel, []);
      map.get(e.dateLabel)!.push(e);
    }
    return map;
  }, [events]);

  const now = new Date();

  // Summary stats
  const uniqueProjects = new Set(events.map((e) => e.project)).size;
  const operatorCount  = events.filter((e) => e.type === "operator").length;

  return (
    <main className="flex-1 overflow-y-auto" style={{ background: "var(--bg)" }}>
      <div className="max-w-2xl mx-auto px-6 py-8 space-y-6">

        {/* Header */}
        <div>
          <h1 className="text-xl font-semibold" style={{ color: "var(--text)" }}>Calendar</h1>
          <p className="mt-1 text-sm" style={{ color: "var(--text-muted)" }}>
            Timeline of all operator runs and memory activity across projects.
          </p>
        </div>

        {!mounted && <div className="h-40" />}

        {mounted && (
          <div className="space-y-6">
            {/* Mini calendar + stats side by side */}
            <div className="grid grid-cols-2 gap-4">
              <MiniCalendar events={events} selectedMonth={now} />

              {/* Stats */}
              <div className="space-y-2">
                <div className="rounded-xl p-4 space-y-3" style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}>
                  <p className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>
                    Overview
                  </p>
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs flex items-center gap-1.5" style={{ color: "var(--text-muted)" }}>
                        <Zap className="h-3 w-3" />Operator runs
                      </span>
                      <span className="text-xs font-semibold tabular-nums" style={{ color: "var(--text)" }}>{operatorCount}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-xs flex items-center gap-1.5" style={{ color: "var(--text-muted)" }}>
                        <FolderOpen className="h-3 w-3" />Projects active
                      </span>
                      <span className="text-xs font-semibold tabular-nums" style={{ color: "var(--text)" }}>{uniqueProjects}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-xs flex items-center gap-1.5" style={{ color: "var(--text-muted)" }}>
                        <CheckCircle2 className="h-3 w-3" />Total events
                      </span>
                      <span className="text-xs font-semibold tabular-nums" style={{ color: "var(--text)" }}>{events.length}</span>
                    </div>
                  </div>
                </div>

                {/* Project legend */}
                <div className="rounded-xl p-4 space-y-2" style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}>
                  <p className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>
                    Projects
                  </p>
                  {Object.entries(PROJECT_DOT).map(([name, dot]) => (
                    <div key={name} className="flex items-center gap-2">
                      <span className={`h-2 w-2 rounded-full shrink-0 ${dot}`} />
                      <span className="text-xs" style={{ color: "var(--text-muted)" }}>{name}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Timeline */}
            {events.length === 0 ? (
              <div
                className="rounded-xl px-6 py-14 text-center space-y-3"
                style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}
              >
                <CalendarDays className="h-8 w-8 mx-auto" style={{ color: "var(--text-quiet)" }} />
                <p className="text-sm font-medium" style={{ color: "var(--text)" }}>No events yet</p>
                <p className="text-sm" style={{ color: "var(--text-quiet)" }}>
                  Run objectives in Operator Mode or add memories — they&apos;ll appear here as timeline events.
                </p>
              </div>
            ) : (
              <div className="space-y-6">
                <div className="flex items-center gap-3">
                  <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>
                    Timeline
                  </span>
                  <div className="flex-1 h-px" style={{ background: "var(--border)" }} />
                  <span className="text-[10px] flex items-center gap-1" style={{ color: "var(--text-quiet)" }}>
                    <Clock className="h-3 w-3" /> Most recent first
                  </span>
                </div>

                {[...groupedEvents.entries()].map(([dateLabel, dayEvents]) => (
                  <div key={dateLabel} className="space-y-2">
                    {/* Day header */}
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold" style={{ color: "var(--text)" }}>{dateLabel}</span>
                      <div className="flex-1 h-px" style={{ background: "var(--border)" }} />
                      <span className="text-[10px] tabular-nums" style={{ color: "var(--text-quiet)" }}>
                        {dayEvents.length} {dayEvents.length === 1 ? "event" : "events"}
                      </span>
                    </div>
                    {/* Events */}
                    <div className="space-y-2">
                      {dayEvents.map((e) => <EventRow key={e.id} event={e} />)}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </main>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CalendarPage() {
  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel message="Sign in to access Digidle OS" forceRedirectUrl="/calendar" />
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <ErrorBoundary>
          <CalendarContent />
        </ErrorBoundary>
      </SignedIn>
    </DashboardShell>
  );
}

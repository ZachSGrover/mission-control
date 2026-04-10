export type MemoryType = "context" | "decision" | "note" | "journal";

export interface MemoryEntry {
  id: string;
  type: MemoryType;
  content: string;
  createdAt: string;
  source?: string;
  tags?: string[];
  embedding?: null;
  // Project-aware fields (v2 — optional, defaults handled at read time)
  project?: string; // e.g. "Digidle", "General"
  area?: string;    // e.g. "Strategy", "Content", "Analysis"
}

// ── Project / area inference ──────────────────────────────────────────────────

const PROJECT_RULES: [RegExp, string][] = [
  [/digidle/i, "Digidle"],
  [/agency|sales|client|chatting|prospect|lead|crm/i, "Modern Sales Agency"],
  [/fitness|athlete|bodybuilding|workout|gym|supplement|macro/i, "Modern Athlete"],
  [/youtube|instagram|tiktok|podcast|reel|video/i, "Modern Athlete"],
];

/** Infer project name from free-form text (objective, goal, or source). */
export function inferProject(text: string): string {
  for (const [pattern, project] of PROJECT_RULES) {
    if (pattern.test(text)) return project;
  }
  return "General";
}

const AREA_BY_STEP_TYPE: Record<string, string> = {
  research: "Strategy",
  write:    "Content",
  analyze:  "Analysis",
  decide:   "Decision",
};

/** Infer area from Operator step type. */
export function inferArea(stepType: string): string {
  return AREA_BY_STEP_TYPE[stepType] ?? "General";
}

/** Get display project (falls back to "General" for old entries). */
export function entryProject(e: MemoryEntry): string {
  return e.project ?? "General";
}

/** Get display area (falls back to "Unsorted" for old entries). */
export function entryArea(e: MemoryEntry): string {
  return e.area ?? "Unsorted";
}

// v1 key — bump version if MemoryEntry schema changes incompatibly
const KEY = "mc_memory_v1";
const OLD_KEY = "mc_memory";

function isValidMemoryEntry(m: unknown): m is MemoryEntry {
  if (typeof m !== "object" || m === null) return false;
  const e = m as Record<string, unknown>;
  return (
    typeof e.id === "string" &&
    typeof e.content === "string" &&
    typeof e.type === "string"
  );
}

export function loadMemory(): MemoryEntry[] {
  if (typeof window === "undefined") return [];

  // Try versioned key
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const parsed: unknown = JSON.parse(raw);
      if (Array.isArray(parsed)) return parsed.filter(isValidMemoryEntry);
    }
  } catch {
    try { localStorage.removeItem(KEY); } catch { /* ignore */ }
  }

  // Migrate from old key
  try {
    const oldRaw = localStorage.getItem(OLD_KEY);
    if (oldRaw) {
      const oldParsed: unknown = JSON.parse(oldRaw);
      if (Array.isArray(oldParsed)) {
        const migrated = oldParsed.filter(isValidMemoryEntry);
        try {
          localStorage.setItem(KEY, JSON.stringify(migrated));
          localStorage.removeItem(OLD_KEY);
        } catch { /* quota */ }
        return migrated;
      }
      try { localStorage.removeItem(OLD_KEY); } catch { /* ignore */ }
    }
  } catch { /* ignore */ }

  return [];
}

export function saveMemory(entries: MemoryEntry[]): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(KEY, JSON.stringify(entries.filter(isValidMemoryEntry)));
  } catch { /* quota */ }
}

export function buildMemoryContext(entries: MemoryEntry[]): string {
  if (!entries.length) return "";
  const relevant = entries.filter((e) => e.type !== "journal");
  if (!relevant.length) return "";
  const byType: Record<string, string[]> = { context: [], decision: [], note: [] };
  for (const e of relevant) {
    if (e.type in byType) byType[e.type].push(e.content);
  }

  const lines: string[] = ["[Persistent Memory — injected automatically]"];
  if (byType.context.length) lines.push("Context:", ...byType.context.map((c) => `• ${c}`));
  if (byType.decision.length) lines.push("Decisions:", ...byType.decision.map((d) => `• ${d}`));
  if (byType.note.length) lines.push("Notes:", ...byType.note.map((n) => `• ${n}`));
  return lines.join("\n");
}

// ── Generated Journal store ───────────────────────────────────────────────────

export interface GeneratedJournalCategories {
  actions: string[];
  decisions: string[];
  insights: string[];
  themes: string[];
}

export interface GeneratedJournalEntry {
  id: string;
  date: string;
  generatedAt: string;
  headline: string;
  summary: string;
  categories: GeneratedJournalCategories;
  messageCount: number;
}

// v1 key — fresh key (manual journal under mc_journal is abandoned)
const GENERATED_JOURNAL_KEY = "mc_journal_v1";

function isValidGeneratedEntry(e: unknown): e is GeneratedJournalEntry {
  if (typeof e !== "object" || e === null) return false;
  const entry = e as Record<string, unknown>;
  return (
    typeof entry.id === "string" &&
    typeof entry.date === "string" &&
    typeof entry.headline === "string"
  );
}

function safeCategories(cats: unknown): GeneratedJournalCategories {
  if (typeof cats !== "object" || cats === null) {
    return { actions: [], decisions: [], insights: [], themes: [] };
  }
  const c = cats as Record<string, unknown>;
  const toArr = (v: unknown): string[] =>
    Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
  return {
    actions: toArr(c.actions),
    decisions: toArr(c.decisions),
    insights: toArr(c.insights),
    themes: toArr(c.themes),
  };
}

export function loadGeneratedJournal(): GeneratedJournalEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(GENERATED_JOURNAL_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(isValidGeneratedEntry)
      .map((e) => ({ ...e, categories: safeCategories(e.categories) }));
  } catch {
    try { localStorage.removeItem(GENERATED_JOURNAL_KEY); } catch { /* ignore */ }
    return [];
  }
}

export function saveGeneratedJournal(entries: GeneratedJournalEntry[]): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(
      GENERATED_JOURNAL_KEY,
      JSON.stringify(entries.filter(isValidGeneratedEntry)),
    );
  } catch { /* quota */ }
}

export function upsertGeneratedJournalEntry(
  entries: GeneratedJournalEntry[],
  next: GeneratedJournalEntry,
): GeneratedJournalEntry[] {
  if (!isValidGeneratedEntry(next)) return entries;
  const exists = entries.some((e) => e.date === next.date);
  if (exists) return entries.map((e) => (e.date === next.date ? next : e));
  return [next, ...entries];
}

export function todayDateString(): string {
  return new Date().toISOString().slice(0, 10);
}

export function formatJournalDate(date: string): string {
  if (typeof date !== "string" || date.length < 10) return date;
  const today = todayDateString();
  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  if (date === today) return "Today";
  if (date === yesterday) return "Yesterday";
  try {
    return new Date(date + "T12:00:00").toLocaleDateString("en-US", {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
  } catch {
    return date;
  }
}

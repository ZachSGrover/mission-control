/**
 * action-logger — writes important system actions into the memory store.
 *
 * Call logSystemAction() whenever a significant event happens that should
 * be remembered: deployments, config changes, integrations, bugs fixed, etc.
 *
 * Entries are written as "note" type with source="system" so they appear
 * in the Memory page and get included in journal generation.
 *
 * Usage:
 *   logSystemAction("deploy", "Deployed commit b0f13fa to app.digidle.com")
 *   logSystemAction("config", "Set OPENAI_API_KEY in Render")
 *   logSystemAction("integration", "Connected ElevenLabs voice API")
 *   logSystemAction("bug_fix", "Fixed CORS preflight 405 error")
 */

import { type MemoryEntry, loadMemory, saveMemory } from "@/lib/memory-store";

export type ActionCategory =
  | "deploy"
  | "config"
  | "integration"
  | "bug_fix"
  | "auth"
  | "subscription"
  | "code_change"
  | "env_var"
  | "permission"
  | "account"
  | "spending"
  | "error";

const CATEGORY_EMOJI: Record<ActionCategory, string> = {
  deploy:       "🚀",
  config:       "⚙️",
  integration:  "🔌",
  bug_fix:      "🐛",
  auth:         "🔐",
  subscription: "💳",
  code_change:  "📝",
  env_var:      "🔑",
  permission:   "🛡️",
  account:      "👤",
  spending:     "💰",
  error:        "🚨",
};

// ── Journal rate-limit and threshold ─────────────────────────────────────────

/** Minimum time between auto-journal entries. */
const JOURNAL_MIN_INTERVAL_MS = 15 * 60 * 1000; // 15 minutes

/** Minimum meaningful logs required since last journal before writing one. */
const JOURNAL_MIN_MEANINGFUL = 5;

/**
 * Routine status events that on their own don't warrant a journal entry.
 * A session that only contains these patterns will not auto-journal.
 */
const ROUTINE_PATTERNS = [
  "Switched to ChatGPT provider",
  "Switched to Gemini provider",
  "OpenAI API key active",
  "Gemini API key active",
  "User signed in",
];

// ── Session-level provider switch tracking ───────────────────────────────────
// Module-scope: survives React remounts, reset per page-load session.

let _sessionSwitchCount = 0;

// ── Core helpers ─────────────────────────────────────────────────────────────

/** Returns true if this log content is considered meaningful (not routine). */
function isMeaningfulContent(content: string): boolean {
  return !ROUTINE_PATTERNS.some((p) => content.includes(p));
}

/**
 * Count meaningful system logs written since `since` ISO string.
 * Used to determine whether a journal entry is warranted.
 */
function countMeaningfulSince(entries: MemoryEntry[], since: string): number {
  return entries.filter(
    (e) =>
      e.source === "system" &&
      e.type === "note" &&
      e.createdAt > since &&
      isMeaningfulContent(e.content),
  ).length;
}

/** Find the ISO timestamp of the most recent auto-journal, or a 24h fallback. */
function lastJournalTimestamp(entries: MemoryEntry[]): string {
  const last = entries.find((e) => e.type === "journal" && e.source === "system");
  return last?.createdAt ?? new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Write a system action to the memory store (localStorage).
 * De-duplicates: won't write the same content twice within 10 minutes.
 */
export function logSystemAction(
  category: ActionCategory,
  description: string,
  detail?: string,
): void {
  if (typeof window === "undefined") return;

  try {
    const emoji = CATEGORY_EMOJI[category] ?? "📌";
    const content = detail
      ? `${emoji} [${category.toUpperCase()}] ${description}\n↳ ${detail}`
      : `${emoji} [${category.toUpperCase()}] ${description}`;

    const existing = loadMemory();
    // Deduplicate within 10 minutes — prevents spam while still capturing genuine repeats
    const tenMinAgo = new Date(Date.now() - 10 * 60 * 1000).toISOString();

    const isDuplicate = existing.some(
      (e) => e.content === content && e.createdAt > tenMinAgo,
    );
    if (isDuplicate) return;

    const entry: MemoryEntry = {
      id:        crypto.randomUUID(),
      type:      "note",
      content,
      source:    "system",
      createdAt: new Date().toISOString(),
      project:   "Mission Control",
      area:      "Operations",
    };

    saveMemory([entry, ...existing]);
  } catch {
    // Non-fatal — logging must never throw
  }
}

/**
 * Compile system logs since the last journal into a structured journal entry.
 *
 * Guards:
 *   - Max once every 15 minutes
 *   - Requires at least 5 meaningful logs since the last journal
 *
 * Call this after any high-signal event: deploys, errors, recoveries,
 * provider bursts, all-fail events. The guards ensure it only writes
 * when there is actually something worth recording.
 */
export function writeAutoJournal(): void {
  if (typeof window === "undefined") return;
  try {
    const entries = loadMemory();

    // ── Guard 1: rate-limit to once per 15 minutes ──
    const intervalCutoff = new Date(Date.now() - JOURNAL_MIN_INTERVAL_MS).toISOString();
    const hasRecentJournal = entries.some(
      (e) => e.type === "journal" && e.source === "system" && e.createdAt > intervalCutoff,
    );
    if (hasRecentJournal) return;

    // ── Guard 2: require minimum meaningful activity since last journal ──
    const lastJournal = lastJournalTimestamp(entries);
    const meaningfulCount = countMeaningfulSince(entries, lastJournal);
    if (meaningfulCount < JOURNAL_MIN_MEANINGFUL) return;

    // ── Gather logs since last journal (max 20, newest first) ──
    const sinceLastJournal = entries
      .filter((e) => e.source === "system" && e.type === "note" && e.createdAt > lastJournal)
      .slice(0, 20);
    if (!sinceLastJournal.length) return;

    // ── Build a structured summary by category group ──
    const dateLabel = new Date().toLocaleString("en-US", {
      month: "short", day: "numeric", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });

    const errors       = sinceLastJournal.filter((e) => e.content.includes("[ERROR]"));
    const fixes        = sinceLastJournal.filter((e) => e.content.includes("[BUG_FIX]") || e.content.includes("[DEPLOY]"));
    const configChange = sinceLastJournal.filter((e) => e.content.includes("[ENV_VAR]") || e.content.includes("[CONFIG] Orchestrator") || e.content.includes("[INTEGRATION]"));
    const routine      = sinceLastJournal.filter(
      (e) => !errors.includes(e) && !fixes.includes(e) && !configChange.includes(e),
    );

    const section = (label: string, items: MemoryEntry[]) =>
      items.length
        ? `${label}\n${items.map((e) => `  • ${e.content.split("\n")[0]}`).join("\n")}`
        : null;

    const sections = [
      section("🚨 Errors", errors),
      section("🐛 Fixes & Deploys", fixes),
      section("🔑 Config changes", configChange),
      section("⚙️ Activity", routine),
    ].filter(Boolean).join("\n\n");

    const content = `📓 Auto Journal — ${dateLabel}\n\n${sections}`;

    const journalEntry: MemoryEntry = {
      id:        crypto.randomUUID(),
      type:      "journal",
      content,
      source:    "system",
      createdAt: new Date().toISOString(),
      project:   "Mission Control",
      area:      "Operations",
    };
    saveMemory([journalEntry, ...entries]);
  } catch {
    // Non-fatal
  }
}

/**
 * Log a provider switch and trigger journal if 3+ switches happened in
 * the current session (indicates active comparison/debugging activity).
 */
export function logProviderSwitch(provider: string, path: string): void {
  logSystemAction("config", `Switched to ${provider} provider`, path);
  _sessionSwitchCount++;
  // A burst of 3+ switches in one session = noteworthy system activity
  if (_sessionSwitchCount >= 3) {
    writeAutoJournal();
  }
}

/**
 * Generate a one-line summary of recent system actions for the journal.
 * Returns null if no recent actions exist.
 */
export function getRecentActionsSummary(withinHours = 24): string | null {
  if (typeof window === "undefined") return null;
  try {
    const cutoff = new Date(Date.now() - withinHours * 60 * 60 * 1000).toISOString();
    const recent = loadMemory().filter(
      (e) => e.source === "system" && e.createdAt > cutoff,
    );
    if (!recent.length) return null;
    return recent
      .slice(0, 5)
      .map((e) => e.content.split("\n")[0])
      .join("; ");
  } catch {
    return null;
  }
}

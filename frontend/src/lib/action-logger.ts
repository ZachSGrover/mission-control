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

/**
 * Write a system action to the memory store (localStorage).
 * De-duplicates: won't write the same content twice within 1 hour.
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

    // Skip if identical content was logged in the last 10 minutes
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
 * Compile the last 20 system actions into a journal entry and store it.
 * Safe to call after deploys, major config changes, or bug fixes.
 * Won't write more than one auto-journal per hour.
 */
export function writeAutoJournal(): void {
  if (typeof window === "undefined") return;
  try {
    const entries = loadMemory();
    const systemEntries = entries
      .filter((e) => e.source === "system" && e.type === "note")
      .slice(0, 20);
    if (systemEntries.length === 0) return;

    // Don't write more than one auto-journal per hour
    const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000).toISOString();
    const hasRecentJournal = entries.some(
      (e) => e.type === "journal" && e.source === "system" && e.createdAt > oneHourAgo,
    );
    if (hasRecentJournal) return;

    const dateLabel = new Date().toLocaleDateString("en-US", {
      month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit",
    });
    const lines = systemEntries
      .map((e) => `• ${e.content.split("\n")[0]}`)
      .join("\n");
    const content = `📓 Auto Journal — ${dateLabel}\n\nRecent system actions:\n${lines}`;

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

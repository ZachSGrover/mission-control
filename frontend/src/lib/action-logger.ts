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
 *
 * Priority events (bypass log threshold, 2-min cooldown instead of 15-min):
 *   writeAutoJournal({ priority: true })
 *
 * Convenience helpers for common priority events:
 *   logDeployCompleted(commit?)
 *   logSystemPaused(reason?)
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
  | "error"
  | "alert";

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
  alert:        "🔔",
};

// ── Journal rate-limit constants ──────────────────────────────────────────────

/**
 * Normal auto-journal rate limit.
 * Won't write more than once per 15 minutes under normal conditions.
 */
const JOURNAL_NORMAL_INTERVAL_MS = 15 * 60 * 1000;

/**
 * Priority auto-journal rate limit.
 * Priority events bypass the log-count threshold but still respect a 2-minute
 * cooldown — prevents repeated crash loops from flooding the journal.
 */
const JOURNAL_PRIORITY_COOLDOWN_MS = 2 * 60 * 1000;

/** Minimum meaningful logs required since last journal (normal path only). */
const JOURNAL_MIN_MEANINGFUL = 5;

/**
 * Routine status patterns that don't count toward the meaningful-log threshold.
 * A session consisting only of these will never trigger a normal auto-journal.
 */
const ROUTINE_PATTERNS = [
  "Switched to ChatGPT provider",
  "Switched to Gemini provider",
  "OpenAI API key active",
  "Gemini API key active",
  "User signed in",
];

/**
 * Substring patterns that mark an entry as noise regardless of category.
 * Entries matching any of these are excluded from journal sections and
 * do not count toward the meaningful-log threshold.
 */
const NOISE_DESCRIPTIONS = [
  "Provider status check",
  "Tab activated",
  "Monitor tick",
  "User signed in",
];

/** Minimum description length (characters) to be considered meaningful. */
const MIN_DESCRIPTION_LENGTH = 10;

// ── Session-level provider switch tracking ────────────────────────────────────
// Module-scope so it survives React remounts within a page-load session.

let _sessionSwitchCount = 0;

// ── Internal helpers ──────────────────────────────────────────────────────────

/**
 * Returns true if a MemoryEntry is meaningful enough to count toward the
 * journal threshold and to appear in journal sections.
 *
 * Filters out:
 *  - Entries matching ROUTINE_PATTERNS (provider switches, etc.)
 *  - Entries matching NOISE_DESCRIPTIONS (status checks, tab events, etc.)
 *  - Entries whose first-line description is under MIN_DESCRIPTION_LENGTH chars
 */
export function isMeaningfulLog(entry: MemoryEntry): boolean {
  const firstLine = entry.content.split("\n")[0];

  // Too short to be meaningful
  if (firstLine.length < MIN_DESCRIPTION_LENGTH) return false;

  // Legacy routine patterns
  if (ROUTINE_PATTERNS.some((p) => firstLine.includes(p))) return false;

  // Extended noise patterns
  if (NOISE_DESCRIPTIONS.some((p) => firstLine.includes(p))) return false;

  return true;
}

function isMeaningfulContent(content: string): boolean {
  return !ROUTINE_PATTERNS.some((p) => content.includes(p));
}

function countMeaningfulSince(entries: MemoryEntry[], since: string): number {
  return entries.filter(
    (e) =>
      e.source === "system" &&
      e.type === "note" &&
      e.createdAt > since &&
      isMeaningfulLog(e),
  ).length;
}

function lastJournalTimestamp(entries: MemoryEntry[]): string {
  const last = entries.find((e) => e.type === "journal" && e.source === "system");
  return last?.createdAt ?? new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
}

// ── Core write ────────────────────────────────────────────────────────────────

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
    // Non-fatal
  }
}

// ── Auto-journal ──────────────────────────────────────────────────────────────

/**
 * Result returned by an auto-fix handler.
 * Attached to a priority journal so the journal captures what was tried
 * and whether it worked.
 */
export interface FixResult {
  /** Human-readable label for what was attempted. */
  attempted: string;
  /** True if the fix fully resolved the problem. */
  success: boolean;
  /** True if the fix helped but did not fully resolve. */
  partial: boolean;
  /** Extra context: what changed, why it failed, next step. */
  detail: string;
}

export interface AutoJournalOptions {
  /**
   * When true, this event bypasses the meaningful-log threshold and uses a
   * 2-minute cooldown instead of 15 minutes.
   *
   * Use for: all-providers-failed, app crash, provider recovery, deploy
   * completed, system paused / manual-intervention required.
   */
  priority?: boolean;

  /**
   * Result from runAutoFix(). When present, a "🔧 Auto-fix" section is
   * prepended to the journal entry so the journal reflects what was tried
   * and whether it worked.
   */
  fixResult?: FixResult;
}

/**
 * Compile system logs since the last journal into a structured journal entry.
 *
 * Normal path guards (both must pass):
 *   1. No journal written in the last 15 minutes
 *   2. At least 5 meaningful logs since the last journal
 *
 * Priority path guards (only one must pass):
 *   1. No journal written in the last 2 minutes (spam protection only)
 *   — threshold is skipped entirely —
 *
 * Structured output sections:
 *   🚨 Errors / 🐛 Fixes & Deploys / 🔑 Config changes / ⚙️ Activity
 */
export function writeAutoJournal(opts?: AutoJournalOptions): void {
  if (typeof window === "undefined") return;
  try {
    const isPriority = opts?.priority === true;
    const fixResult  = opts?.fixResult;
    const entries = loadMemory();

    // ── Rate limit ──────────────────────────────────────────────────────────
    // Priority events use a 2-min cooldown; normal events use 15 min.
    const intervalMs = isPriority ? JOURNAL_PRIORITY_COOLDOWN_MS : JOURNAL_NORMAL_INTERVAL_MS;
    const intervalCutoff = new Date(Date.now() - intervalMs).toISOString();
    const hasRecentJournal = entries.some(
      (e) => e.type === "journal" && e.source === "system" && e.createdAt > intervalCutoff,
    );
    if (hasRecentJournal) return;

    // ── Meaningful-log threshold (normal path only) ────────────────────────
    const lastJournal = lastJournalTimestamp(entries);
    if (!isPriority) {
      const meaningfulCount = countMeaningfulSince(entries, lastJournal);
      if (meaningfulCount < JOURNAL_MIN_MEANINGFUL) return;
    }

    // ── Gather logs since last journal (max 20, newest first) ─────────────
    const sinceLastJournal = entries
      .filter((e) => e.source === "system" && e.type === "note" && e.createdAt > lastJournal)
      .slice(0, 20);
    if (!sinceLastJournal.length) return;

    // ── Build structured sections ──────────────────────────────────────────
    const dateLabel = new Date().toLocaleString("en-US", {
      month: "short", day: "numeric", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
    const priorityBadge = isPriority ? " ⚡ PRIORITY" : "";

    const errors         = sinceLastJournal.filter((e) => e.content.includes("[ERROR]"));
    const fixes          = sinceLastJournal.filter((e) => e.content.includes("[BUG_FIX]") || e.content.includes("[DEPLOY]"));
    const configChange   = sinceLastJournal.filter((e) => e.content.includes("[ENV_VAR]") || e.content.includes("[CONFIG] Orchestrator") || e.content.includes("[INTEGRATION]"));
    const projectChanges = sinceLastJournal.filter((e) => e.content.includes("project_created") || e.content.includes("project_updated"));
    const workflowEvents = sinceLastJournal.filter((e) => e.content.includes("workflow_"));
    const agentEvents    = sinceLastJournal.filter((e) => e.content.includes("agent_created") || e.content.includes("agent_updated"));
    const remoteCommands = sinceLastJournal.filter((e) => e.content.includes("telegram") || e.content.includes("remote_command"));

    // Collect already-categorised entries so routine doesn't repeat them
    const categorised = new Set([
      ...errors, ...fixes, ...configChange,
      ...projectChanges, ...workflowEvents, ...agentEvents, ...remoteCommands,
    ]);
    const routine = sinceLastJournal.filter((e) => !categorised.has(e));

    const section = (label: string, items: MemoryEntry[]) =>
      items.length
        ? `${label}\n${items.map((e) => `  • ${e.content.split("\n")[0]}`).join("\n")}`
        : null;

    // ── Auto-fix result block (priority journals only) ────────────────────
    let fixBlock: string | null = null;
    if (fixResult) {
      const icon = fixResult.success ? "✅" : fixResult.partial ? "⚠️" : "❌";
      const status = fixResult.success ? "Success" : fixResult.partial ? "Partial" : "Failed";
      fixBlock = `🔧 Auto-fix: ${fixResult.attempted}\n  ${icon} ${status} — ${fixResult.detail}`;
    }

    const sections = [
      fixBlock,
      section("🚨 Errors", errors),
      section("🐛 Fixes & Deploys", fixes),
      section("🔑 Config changes", configChange),
      section("🗂️ Project Changes", projectChanges),
      section("⚡ Workflow Events", workflowEvents),
      section("🤖 Agent Events", agentEvents),
      section("📡 Remote Commands", remoteCommands),
      section("⚙️ Activity", routine),
    ].filter(Boolean).join("\n\n");

    const content = `📓 Auto Journal${priorityBadge} — ${dateLabel}\n\n${sections}`;

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

// ── Priority event helpers ────────────────────────────────────────────────────
// Convenience wrappers for events that should always produce a journal entry.

/**
 * Log a successful deploy, run the deploy fix handler (health check), then
 * write a priority journal with the result.
 * Call after Vercel / Render deploy confirmation, or after git push resolves.
 */
export async function logDeployCompleted(commit?: string, token?: string | null): Promise<void> {
  logSystemAction(
    "deploy",
    "Deploy completed successfully",
    commit ? `commit ${commit}` : "app.digidle.com",
  );
  // Lazy import to avoid circular dep — auto-fix imports logSystemAction from here
  const { runAutoFix } = await import("@/lib/auto-fix");
  const fix = await runAutoFix("deploy_completed", { token });
  writeAutoJournal({ priority: true, fixResult: fix });
}

/**
 * Log that the system has entered a paused or manual-intervention state,
 * run the system-paused fix handler (marks intervention required), then
 * write a priority journal with the result.
 */
export async function logSystemPaused(reason?: string): Promise<void> {
  logSystemAction(
    "error",
    "System entered paused / manual intervention state",
    reason ?? "master controller flagged manual_intervention_required",
  );
  const { runAutoFix } = await import("@/lib/auto-fix");
  const fix = await runAutoFix("system_paused", { reason });
  writeAutoJournal({ priority: true, fixResult: fix });
}

// ── Provider switch tracking ──────────────────────────────────────────────────

/**
 * Log a provider switch and trigger a normal journal if 3+ switches happened
 * in the current session (indicates active comparison/debugging activity).
 */
export function logProviderSwitch(provider: string, path: string): void {
  logSystemAction("config", `Switched to ${provider} provider`, path);
  _sessionSwitchCount++;
  if (_sessionSwitchCount >= 3) {
    writeAutoJournal(); // burst — normal path, threshold still applies
  }
}

// ── Remote command logging ────────────────────────────────────────────────────

/**
 * Log a command received or tested via a remote integration (e.g. Telegram bot).
 *
 * @param source  - The remote source ("telegram" | "webhook")
 * @param command - The command string that was invoked (e.g. "/status")
 * @param result  - Whether the command succeeded or produced an error
 */
export function logRemoteCommand(
  source: "telegram" | "webhook",
  command: string,
  result: "ok" | "error",
): void {
  const category: ActionCategory = result === "error" ? "error" : "integration";
  const label = source === "telegram" ? "Telegram" : "Webhook";
  logSystemAction(
    category,
    `Remote command via ${label}: ${command}`,
    result === "ok" ? "Executed successfully" : "Execution failed",
  );
}

// ── Project / workflow / agent helpers ───────────────────────────────────────

/**
 * Log that a new project was created.
 * Appears in the 🗂️ Project Changes journal section.
 */
export function logProjectCreated(name: string): void {
  logSystemAction("config", `project_created: ${name}`);
}

/**
 * Log that an existing project was updated.
 * Appears in the 🗂️ Project Changes journal section.
 */
export function logProjectUpdated(name: string, changes?: string): void {
  logSystemAction("config", `project_updated: ${name}`, changes);
}

/**
 * Log a workflow execution result.
 * Appears in the ⚡ Workflow Events journal section.
 */
export function logWorkflowRun(name: string, status: "success" | "error"): void {
  const category: ActionCategory = status === "error" ? "error" : "deploy";
  logSystemAction(category, `workflow_run: ${name}`, status);
}

/**
 * Log that a new agent was created.
 * Appears in the 🤖 Agent Events journal section.
 */
export function logAgentCreated(name: string): void {
  logSystemAction("config", `agent_created: ${name}`);
}

/**
 * Log that an existing agent was updated.
 * Appears in the 🤖 Agent Events journal section.
 */
export function logAgentUpdated(name: string): void {
  logSystemAction("config", `agent_updated: ${name}`);
}

// ── Summary ───────────────────────────────────────────────────────────────────

/**
 * Return a one-line summary of recent system actions.
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

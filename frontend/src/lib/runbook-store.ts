// Runbook definitions store — mc_runbooks_v1 (schema V2)
//
// Runbooks are saved operational prompts (diagnostics, restart, repair, etc.)
// that can be copied verbatim into Claude Code or Discord. Empty `prompt`
// means the card is a placeholder — not yet filled in.
//
// V2 adds `dangerLevel` and `approvalNote`. The localStorage key is unchanged;
// on load we backfill missing fields on existing records and upgrade seed
// placeholders to their V2 content (but never overwrite user-edited prompts).

const KEY = "mc_runbooks_v1";

export const RUNBOOK_CATEGORIES = [
  "Diagnostics",
  "Restart",
  "Repair",
  "Bots",
  "Mission Control",
  "Discord",
  "Telegram",
  "Memory",
  "Deployments",
  "API Spend",
  "Notion",
  "Obsidian",
] as const;

export type RunbookCategory = (typeof RUNBOOK_CATEGORIES)[number];

export const DANGER_LEVELS = ["Safe", "Medium", "High"] as const;
export type DangerLevel = (typeof DANGER_LEVELS)[number];

export interface RunbookDef {
  id: string;
  title: string;
  category: RunbookCategory;
  description: string;
  whenToUse: string;
  warnings: string;
  prompt: string;
  dangerLevel: DangerLevel;
  approvalNote: string;
  favorite: boolean;
  createdAt: string;
  updatedAt: string;
}

// ── Seed prompt bodies ───────────────────────────────────────────────────────

const SYSTEM_HEALTH_CHECK_PROMPT = `Run a full OpenClaw system health check after a computer crash.

Do not rebuild anything yet. Do not delete anything. Do not rotate keys. Do not change configs unless there is an obvious broken local process that can be safely restarted.

Check the entire current setup and report back in a clean status summary.

Health check scope:

1. Confirm the project folder is intact
   Check the current OpenClaw/Mission Control project directory.
   Confirm important folders, package files, env files, bot files, logs, and startup scripts still exist.
   Do not print secrets or API keys.

2. Check Mission Control
   Confirm the Mission Control app can start.
   Confirm the dashboard loads locally.
   Confirm the main sections are still present:
   Users
   Chat
   Projects
   Memory
   Boards
   Agents
   Gateway
   Control
   Workflows
   Skills
   Logs
   Guide
   Settings
   Runbooks

3. Check Discord connection
   Confirm the Discord bot process exists or can start.
   Confirm DISCORD_TOKEN is present in environment without revealing it.
   Confirm the bot can connect to Discord.
   Confirm the bot can see the correct server and channels.
   Confirm the existing bots/channels still exist, especially:
   claw-general
   social-radar
   ai-radar
   rt-bot
   SOP bot channel if present

4. Check Telegram connection if configured
   Confirm Telegram bot token is present if used.
   Confirm Telegram process exists or can start.
   Confirm webhook or polling status.
   Do not expose the token.

5. Check OpenAI and Anthropic keys
   Confirm environment variables exist for OpenAI and Anthropic.
   Do not print the keys.
   Run the smallest possible safe test request if the codebase already has a test script.
   If no safe test exists, only confirm the variables are present.

6. Check Notion connection
   Confirm Notion key/database variables exist if configured.
   Do not print secrets.
   Confirm any SOP database or connected Notion database is reachable if a safe test already exists.
   Do not create pages unless specifically needed for a test and clearly labeled as a test.

7. Check Obsidian/memory setup
   Confirm the Obsidian vault path or memory path exists.
   Confirm files are readable.
   Confirm Mission Control memory section points to the correct vault/path if implemented.
   Do not modify notes.

8. Check running processes
   Identify any OpenClaw, Mission Control, Discord, Telegram, bot, worker, watcher, or scheduler processes.
   Identify crashed/stale processes.
   Restart only obvious local processes that are supposed to be running and can be safely restarted.

9. Check logs
   Review recent logs from the last 24 hours.
   Look for crash errors, missing env vars, Discord connection errors, Telegram errors, Notion errors, OpenAI/Anthropic errors, port conflicts, or runaway loops.
   Summarize the top issues.

10. Check startup behavior
    Confirm what is supposed to auto-start on reboot.
    Identify what did not auto-start.
    If launch agents, pm2, Docker, npm scripts, or system services are used, check their status.
    Do not create new startup services yet unless there is already an existing broken one that only needs restart.

11. Check ports
    Confirm Mission Control local port is available or running.
    Detect port conflicts.

12. Check Git status if this is a git repo
    Show current branch.
    Show uncommitted changes summary.
    Do not commit, reset, pull, push, stash, or delete anything.

13. Final report
    Give me a simple report with:
    Overall status: Healthy / Partially broken / Broken
    What is working
    What is stopped
    What restarted successfully
    What needs my approval before changing
    Exact next prompt I should run after this

Important rules:
Do not expose secrets.
Do not delete files.
Do not rebuild.
Do not ask me for Discord keys unless the env file is truly missing the token.
Do not ask me for OpenAI/Anthropic keys unless the env variables are missing.
Do not make major architecture changes.
This is a diagnostic and safe restart pass only.`;

const SAFE_RESTART_PROMPT = `Run a safe OpenClaw restart pass.

Do not delete files.
Do not rebuild the app.
Do not rotate API keys.
Do not change environment variables.
Do not modify launchd ownership.
Do not change ports.
Do not change architecture.
Do not touch unrelated services.

Goal:
Restart only obvious stuck or stale OpenClaw services that are supposed to be running.

Before restarting anything:
1. Check current port ownership for 3000, 8000, and 18789.
2. Check Mission Control GUI status.
3. Check backend /health.
4. Check gateway health.
5. Check Discord heartbeat.
6. Check launchctl status for OpenClaw related services.
7. Identify exactly what is stopped, stale, duplicated, or crash-looping.

Restart rules:
Only restart a process if:
1. It is clearly stopped but supposed to be running.
2. It is stale and has no healthy heartbeat.
3. It is crash-looping and the restart target is clearly identified.
4. Restarting it does not create duplicate listeners.

Do not restart:
1. Mission Control.app unless I explicitly approve.
2. Backend if /health is already 200.
3. Gateway if port 18789 is healthy.
4. next-server if frontend 3000 is healthy.
5. Discord bot if heartbeat is healthy.

After any restart:
1. Confirm the process came back.
2. Confirm no duplicate listeners were created.
3. Confirm frontend 3000 works.
4. Confirm backend /health returns 200.
5. Confirm gateway 18789 works.
6. Confirm Discord heartbeat is ok.
7. Report exactly what changed.

Final report:
Overall status
What was restarted
What was left alone
Current port ownership
Any remaining warnings
Exact next prompt to run if repair is needed`;

const FULL_REPAIR_PROMPT = `Run a controlled OpenClaw repair pass.

Important:
Do not start by changing files.
Do not delete anything.
Do not rotate keys.
Do not reset git.
Do not pull, push, commit, stash, or discard changes.
Do not rebuild unless the confirmed issue requires it.
Do not modify launchd services unless the confirmed issue requires it.
Do not change architecture unless explicitly approved.

Step 1:
Read the latest health check output or reproduce the failing check.

Step 2:
Identify the single most likely root cause.
Do not fix multiple unrelated things at once.

Step 3:
Propose the repair plan before executing.
The plan must include:
1. What is broken
2. Why it is broken
3. Files or services that would be touched
4. Risk level
5. Rollback plan
6. Exact commands or file edits planned

Step 4:
Wait for approval if the repair involves:
1. Deleting files
2. Changing env vars
3. Rotating keys
4. Killing Mission Control.app
5. Changing launchd services
6. Rebuilding frontend or backend
7. Modifying database or migrations
8. Changing authentication
9. Changing port ownership
10. Changing Discord, Telegram, Notion, OpenAI, Anthropic, or Gemini connection logic

Step 5:
If the repair is approved, make the smallest possible fix.

Step 6:
Verify:
1. Mission Control GUI works
2. Frontend 3000 works
3. Backend /health returns 200
4. Gateway 18789 works
5. Discord heartbeat is ok
6. No duplicate listeners exist
7. No crash loops exist
8. Git status shows only expected changes

Final report:
What was broken
What was changed
What was not touched
Verification result
Remaining risks
Rollback instructions
Exact next prompt to run`;

const DISCORD_BOT_DIAG_PROMPT = `Run Discord bot diagnostics for OpenClaw.

Do not rotate tokens.
Do not print tokens.
Do not create or delete channels.
Do not change permissions.
Do not rebuild anything.
Do not restart anything unless I approve.

Check:
1. DISCORD_TOKEN exists without revealing it.
2. Discord bot process is running or expected heartbeat process is running.
3. Latest Discord heartbeat status.
4. Bot identity currently connected.
5. Guild/server visibility.
6. Channel visibility for:
claw-general
ai-radar
social-radar
rt-bot
SOP bot channel if present
7. Recent Discord errors in logs from the last 24 hours.
8. Whether messages are being received.
9. Whether replies are being sent.
10. Whether rate limits, permission errors, or gateway disconnects are happening.

Final report:
Discord status: Healthy / Partial / Broken
Connected bot name
Visible channels
Working channels
Broken channels
Recent errors
What needs approval before fixing
Exact next prompt to run`;

// ── Seed data ────────────────────────────────────────────────────────────────

const SEED_DATE = "2026-04-24T00:00:00.000Z";

function placeholder(
  id: string,
  title: string,
  category: RunbookCategory,
): RunbookDef {
  return {
    id,
    title,
    category,
    description: "Prompt not added yet.",
    whenToUse: "",
    warnings: "",
    prompt: "",
    dangerLevel: "Safe",
    approvalNote: "",
    favorite: false,
    createdAt: SEED_DATE,
    updatedAt: SEED_DATE,
  };
}

const DEFAULT_RUNBOOKS: RunbookDef[] = [
  {
    id: "seed-system-health-check",
    title: "System Health Check",
    category: "Diagnostics",
    description:
      "Safe diagnostic prompt to run after a computer crash, bot failure, Mission Control issue, or strange system behavior.",
    whenToUse:
      "Use this after the computer crashes, Discord bots stop responding, Mission Control looks broken, Claude Code errors, Telegram stops working, or anything feels unstable.",
    warnings:
      "This prompt should not delete files, rebuild the app, rotate keys, expose secrets, or make major changes. It is only for checking status and safely restarting obvious local processes.",
    prompt: SYSTEM_HEALTH_CHECK_PROMPT,
    dangerLevel: "Safe",
    approvalNote: "No approval needed. Diagnostic only.",
    favorite: true,
    createdAt: SEED_DATE,
    updatedAt: SEED_DATE,
  },
  {
    id: "seed-safe-restart",
    title: "Safe Restart",
    category: "Restart",
    description:
      "Safely restarts obvious stuck local OpenClaw services without changing architecture, deleting files, or rebuilding the app.",
    whenToUse:
      "Use this after a health check shows a service is stopped, stale, or frozen but the files and configuration appear intact.",
    warnings:
      "This may restart local processes, but it must not delete files, rotate keys, rebuild the app, change environment variables, or modify launchd service ownership.",
    prompt: SAFE_RESTART_PROMPT,
    dangerLevel: "Medium",
    approvalNote:
      "Ask before running. Safe restart only. No deletes, no rebuilds, no key changes.",
    favorite: false,
    createdAt: SEED_DATE,
    updatedAt: SEED_DATE,
  },
  {
    id: "seed-full-repair",
    title: "Full Repair",
    category: "Repair",
    description:
      "Controlled repair prompt for fixing a confirmed OpenClaw issue after diagnosis.",
    whenToUse:
      "Use only after System Health Check or Safe Restart identifies a specific broken component and I approve fixing it.",
    warnings:
      "This can modify files, configs, services, or build artifacts depending on the diagnosed issue. It must always explain the plan first and get approval before making risky changes.",
    prompt: FULL_REPAIR_PROMPT,
    dangerLevel: "High",
    approvalNote:
      "Requires explicit approval. Only run after System Health Check identifies a specific issue.",
    favorite: false,
    createdAt: SEED_DATE,
    updatedAt: SEED_DATE,
  },
  {
    id: "seed-discord-bot-diag",
    title: "Discord Bot Diagnostics",
    category: "Discord",
    description:
      "Checks whether Discord bots and channels are connected, responding, and healthy.",
    whenToUse:
      "Use when claw-general, ai-radar, social-radar, rt-bot, SOP bot, or any Discord workflow stops responding.",
    warnings:
      "This should not rotate Discord tokens, create bots, delete channels, change permissions, or rebuild anything.",
    prompt: DISCORD_BOT_DIAG_PROMPT,
    dangerLevel: "Safe",
    approvalNote: "No approval needed. Diagnostic only.",
    favorite: false,
    createdAt: SEED_DATE,
    updatedAt: SEED_DATE,
  },
  placeholder("seed-telegram-bot-diag", "Telegram Bot Diagnostics", "Telegram"),
  placeholder("seed-mc-ui-repair", "Mission Control UI Repair", "Mission Control"),
  placeholder("seed-api-spend-check", "API Spend Check", "API Spend"),
  placeholder("seed-obsidian-memory-check", "Obsidian Memory Check", "Obsidian"),
  placeholder("seed-notion-connection-check", "Notion Connection Check", "Notion"),
  placeholder("seed-deployment-safety-check", "Deployment Safety Check", "Deployments"),
];

// ── Validation + migration ───────────────────────────────────────────────────

function isCategory(v: unknown): v is RunbookCategory {
  return typeof v === "string" && (RUNBOOK_CATEGORIES as readonly string[]).includes(v);
}

function isDangerLevel(v: unknown): v is DangerLevel {
  return typeof v === "string" && (DANGER_LEVELS as readonly string[]).includes(v);
}

// Migrate a possibly-V1 (pre-dangerLevel) record into a fully-valid V2 RunbookDef.
// Returns null if the record lacks the V1 core fields.
function migrateRunbook(raw: unknown): RunbookDef | null {
  if (typeof raw !== "object" || raw === null) return null;
  const obj = raw as Record<string, unknown>;

  if (
    typeof obj.id !== "string" ||
    typeof obj.title !== "string" ||
    !isCategory(obj.category) ||
    typeof obj.description !== "string" ||
    typeof obj.whenToUse !== "string" ||
    typeof obj.warnings !== "string" ||
    typeof obj.prompt !== "string" ||
    typeof obj.favorite !== "boolean" ||
    typeof obj.createdAt !== "string" ||
    typeof obj.updatedAt !== "string"
  ) {
    return null;
  }

  return {
    id: obj.id,
    title: obj.title,
    category: obj.category,
    description: obj.description,
    whenToUse: obj.whenToUse,
    warnings: obj.warnings,
    prompt: obj.prompt,
    dangerLevel: isDangerLevel(obj.dangerLevel) ? obj.dangerLevel : "Safe",
    approvalNote: typeof obj.approvalNote === "string" ? obj.approvalNote : "",
    favorite: obj.favorite,
    createdAt: obj.createdAt,
    updatedAt: obj.updatedAt,
  };
}

function isValidRunbookDef(r: unknown): r is RunbookDef {
  if (typeof r !== "object" || r === null) return false;
  const obj = r as Record<string, unknown>;
  return (
    typeof obj.id === "string" &&
    typeof obj.title === "string" &&
    isCategory(obj.category) &&
    typeof obj.description === "string" &&
    typeof obj.whenToUse === "string" &&
    typeof obj.warnings === "string" &&
    typeof obj.prompt === "string" &&
    isDangerLevel(obj.dangerLevel) &&
    typeof obj.approvalNote === "string" &&
    typeof obj.favorite === "boolean" &&
    typeof obj.createdAt === "string" &&
    typeof obj.updatedAt === "string"
  );
}

// Merge stored data with V2 seeds:
// - Existing record with a seed ID and an empty prompt → replace with fresh seed.
// - Existing record with a seed ID and non-empty prompt → KEEP user version,
//   only backfill missing dangerLevel/approvalNote (handled in migrateRunbook).
// - Non-seed records → migrated as-is.
// - Seed IDs not present in storage → appended from DEFAULT_RUNBOOKS.
function mergeWithSeeds(existing: RunbookDef[]): RunbookDef[] {
  const byId = new Map<string, RunbookDef>();
  for (const e of existing) byId.set(e.id, e);

  for (const seed of DEFAULT_RUNBOOKS) {
    const prior = byId.get(seed.id);
    if (!prior) {
      byId.set(seed.id, seed);
    } else if (prior.prompt.trim() === "" && seed.prompt.trim() !== "") {
      // Upgrade placeholder → V2 seed content (user hadn't customized it).
      byId.set(seed.id, { ...seed, favorite: prior.favorite });
    }
    // Else keep prior; migrateRunbook has already backfilled V2 fields.
  }

  // Preserve insertion order roughly: existing first, then any new seeds.
  const result: RunbookDef[] = [];
  const seen = new Set<string>();
  for (const e of existing) {
    const merged = byId.get(e.id);
    if (merged && !seen.has(merged.id)) {
      result.push(merged);
      seen.add(merged.id);
    }
  }
  for (const seed of DEFAULT_RUNBOOKS) {
    if (!seen.has(seed.id)) {
      const merged = byId.get(seed.id)!;
      result.push(merged);
      seen.add(merged.id);
    }
  }
  return result;
}

// ── CRUD ─────────────────────────────────────────────────────────────────────

export function loadRunbooks(): RunbookDef[] {
  if (typeof window === "undefined") return DEFAULT_RUNBOOKS;
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const parsed: unknown = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        const migrated = parsed
          .map(migrateRunbook)
          .filter((r): r is RunbookDef => r !== null);
        if (migrated.length > 0) {
          const merged = mergeWithSeeds(migrated);
          // Persist migration/merge so future loads are stable.
          try { localStorage.setItem(KEY, JSON.stringify(merged)); } catch { /* quota */ }
          return merged;
        }
      }
    }
  } catch {
    try { localStorage.removeItem(KEY); } catch { /* ignore */ }
  }
  // Empty / unreadable: seed fresh.
  try {
    localStorage.setItem(KEY, JSON.stringify(DEFAULT_RUNBOOKS));
  } catch { /* quota */ }
  return DEFAULT_RUNBOOKS;
}

export function saveRunbooks(runbooks: RunbookDef[]): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(KEY, JSON.stringify(runbooks.filter(isValidRunbookDef)));
  } catch { /* quota */ }
}

export function createRunbook(
  title: string,
  category: RunbookCategory,
  description: string = "",
  prompt: string = "",
  whenToUse: string = "",
  warnings: string = "",
  dangerLevel: DangerLevel = "Safe",
  approvalNote: string = "",
): RunbookDef {
  const now = new Date().toISOString();
  const runbook: RunbookDef = {
    id: crypto.randomUUID(),
    title: title.trim() || "Untitled Runbook",
    category,
    description: description.trim(),
    whenToUse: whenToUse.trim(),
    warnings: warnings.trim(),
    prompt,
    dangerLevel,
    approvalNote: approvalNote.trim(),
    favorite: false,
    createdAt: now,
    updatedAt: now,
  };
  const existing = loadRunbooks();
  saveRunbooks([...existing, runbook]);
  return runbook;
}

export function updateRunbook(
  id: string,
  patch: Partial<Omit<RunbookDef, "id" | "createdAt">>,
): RunbookDef | null {
  const runbooks = loadRunbooks();
  const idx = runbooks.findIndex((r) => r.id === id);
  if (idx === -1) return null;
  const updated: RunbookDef = {
    ...runbooks[idx],
    ...patch,
    id: runbooks[idx].id,
    createdAt: runbooks[idx].createdAt,
    updatedAt: new Date().toISOString(),
  };
  const next = [...runbooks];
  next[idx] = updated;
  saveRunbooks(next);
  return updated;
}

export function deleteRunbook(id: string): boolean {
  const runbooks = loadRunbooks();
  const next = runbooks.filter((r) => r.id !== id);
  if (next.length === runbooks.length) return false;
  saveRunbooks(next);
  return true;
}

export function isPlaceholder(r: RunbookDef): boolean {
  return r.prompt.trim().length === 0;
}

// Favorited-real → real → placeholder; alphabetical within each group.
export function compareRunbooks(a: RunbookDef, b: RunbookDef): number {
  const aPh = isPlaceholder(a);
  const bPh = isPlaceholder(b);
  if (aPh !== bPh) return aPh ? 1 : -1;
  if (!aPh) {
    if (a.favorite !== b.favorite) return a.favorite ? -1 : 1;
  }
  return a.title.localeCompare(b.title);
}

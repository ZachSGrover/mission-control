/**
 * journal-generator.ts
 *
 * Collects today's AI chat activity from localStorage, calls the backend
 * journal generation endpoint, and persists the result.
 */

import { getLocalAuthToken } from "@/auth/localAuth";
import { getApiBaseUrl } from "@/lib/api-base";
import {
  type GeneratedJournalEntry,
  type MemoryEntry,
  todayDateString,
  upsertGeneratedJournalEntry,
  loadGeneratedJournal,
  saveGeneratedJournal,
} from "@/lib/memory-store";

// ── Activity collection ───────────────────────────────────────────────────────

// Always use the versioned key prefix (mc_chat_v1_*) to match chat-store.ts
const VERSIONED_PROVIDER_KEYS: Record<string, string> = {
  claude:   "mc_chat_v1_claude",
  chatgpt:  "mc_chat_v1_chatgpt",
  gemini:   "mc_chat_v1_gemini",
};

export interface ActivityMessage {
  role: string;
  text: string;
  provider: string;
  createdAt: string;
}

/**
 * Scan all known chat providers in localStorage and return messages
 * whose `createdAt` date matches `date` (default: today).
 * Only runs on the client — returns [] on server.
 */
export function collectActivityForDate(date?: string): ActivityMessage[] {
  if (typeof window === "undefined") return [];

  const targetDate = date ?? todayDateString();
  const results: ActivityMessage[] = [];

  for (const [provider, key] of Object.entries(VERSIONED_PROVIDER_KEYS)) {
    try {
      const raw = localStorage.getItem(key);
      if (!raw) continue;
      const parsed: unknown = JSON.parse(raw);
      if (!Array.isArray(parsed)) continue;

      for (const msg of parsed) {
        if (
          typeof msg === "object" && msg !== null &&
          typeof (msg as Record<string, unknown>).createdAt === "string" &&
          ((msg as Record<string, unknown>).createdAt as string).startsWith(targetDate) &&
          !(msg as Record<string, unknown>).error &&
          typeof (msg as Record<string, unknown>).text === "string" &&
          typeof (msg as Record<string, unknown>).role === "string"
        ) {
          const m = msg as Record<string, unknown>;
          results.push({
            role: String(m.role),
            text: String(m.text),
            provider,
            createdAt: String(m.createdAt),
          });
        }
      }
    } catch {
      // Ignore per-provider parse errors
    }
  }

  results.sort((a, b) => a.createdAt.localeCompare(b.createdAt));
  return results;
}

// ── API call ──────────────────────────────────────────────────────────────────

interface JournalGenerateRequest {
  date: string;
  messages: ActivityMessage[];
  memory: { type: string; content: string }[];
}

interface JournalGenerateResponse {
  date: string;
  headline: string;
  summary: string;
  categories: {
    actions: string[];
    decisions: string[];
    insights: string[];
    themes: string[];
  };
  messageCount: number;
}

export async function generateJournalEntry(
  date: string,
  messages: ActivityMessage[],
  memory: MemoryEntry[],
): Promise<GeneratedJournalEntry> {
  const baseUrl = getApiBaseUrl();
  const token = getLocalAuthToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const body: JournalGenerateRequest = {
    date,
    messages,
    memory: (memory ?? [])
      .filter((m) => m?.type !== "journal" && typeof m?.content === "string")
      .map((m) => ({ type: m.type, content: m.content })),
  };

  const res = await fetch(`${baseUrl}/api/v1/journal/generate`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const err = (await res.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(err?.detail ?? `HTTP ${res.status}`);
  }

  const data = (await res.json()) as JournalGenerateResponse;

  const entry: GeneratedJournalEntry = {
    id: crypto.randomUUID(),
    date: String(data.date ?? date),
    generatedAt: new Date().toISOString(),
    headline: String(data.headline ?? ""),
    summary: String(data.summary ?? ""),
    categories: {
      actions:   Array.isArray(data.categories?.actions)   ? data.categories.actions   : [],
      decisions: Array.isArray(data.categories?.decisions) ? data.categories.decisions : [],
      insights:  Array.isArray(data.categories?.insights)  ? data.categories.insights  : [],
      themes:    Array.isArray(data.categories?.themes)    ? data.categories.themes    : [],
    },
    messageCount: typeof data.messageCount === "number" ? data.messageCount : messages.length,
  };

  // Persist immediately
  try {
    const existing = loadGeneratedJournal();
    saveGeneratedJournal(upsertGeneratedJournalEntry(existing, entry));
  } catch {
    // Persistence failure is non-fatal
  }

  return entry;
}

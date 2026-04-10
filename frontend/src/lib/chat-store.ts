import type { ChatMessage } from "@/hooks/use-openclaw-chat";

// v1 key prefix — bump to v2 if ChatMessage schema ever changes incompatibly
const VERSION = "v1";
const PREFIX = `mc_chat_${VERSION}_`;
const OLD_PREFIX = "mc_chat_"; // pre-versioning keys — migrated on first read
const MAX_MESSAGES = 200;

function isValidChatMessage(m: unknown): m is ChatMessage {
  if (typeof m !== "object" || m === null) return false;
  const msg = m as Record<string, unknown>;
  return (
    typeof msg.id === "string" &&
    (msg.role === "user" || msg.role === "assistant") &&
    typeof msg.text === "string"
  );
}

function sanitize(messages: unknown[]): ChatMessage[] {
  return messages
    .filter(isValidChatMessage)
    .map((m) => ({
      ...m,
      streaming: false,      // never restore a mid-stream state
      text: typeof m.text === "string" ? m.text : "",
    }))
    .slice(-MAX_MESSAGES);
}

export function loadChatHistory(provider: string): ChatMessage[] {
  if (typeof window === "undefined") return [];

  // ── Try versioned key ──
  try {
    const raw = localStorage.getItem(PREFIX + provider);
    if (raw) {
      const parsed: unknown = JSON.parse(raw);
      if (Array.isArray(parsed)) return sanitize(parsed);
    }
  } catch {
    // Corrupt data — will fall through to migration or empty
    try { localStorage.removeItem(PREFIX + provider); } catch { /* ignore */ }
  }

  // ── Try old (unversioned) key and migrate ──
  try {
    const oldKey = OLD_PREFIX + provider;
    const oldRaw = localStorage.getItem(oldKey);
    if (oldRaw) {
      const oldParsed: unknown = JSON.parse(oldRaw);
      if (Array.isArray(oldParsed)) {
        const migrated = sanitize(oldParsed);
        try {
          localStorage.setItem(PREFIX + provider, JSON.stringify(migrated));
          localStorage.removeItem(oldKey);
        } catch { /* quota */ }
        return migrated;
      }
      // Old data is unreadable — just remove it
      try { localStorage.removeItem(oldKey); } catch { /* ignore */ }
    }
  } catch { /* ignore */ }

  return [];
}

export function saveChatHistory(provider: string, messages: ChatMessage[]): void {
  if (typeof window === "undefined") return;
  try {
    const toSave = sanitize(messages);
    localStorage.setItem(PREFIX + provider, JSON.stringify(toSave));
  } catch {
    // Storage quota — silently skip
  }
}

export function clearChatHistory(provider: string): void {
  if (typeof window === "undefined") return;
  try { localStorage.removeItem(PREFIX + provider); } catch { /* ignore */ }
  try { localStorage.removeItem(OLD_PREFIX + provider); } catch { /* ignore */ }
}

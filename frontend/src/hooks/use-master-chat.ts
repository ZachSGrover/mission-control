"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "@/auth/clerk";
import { getApiBaseUrl } from "@/lib/api-base";
import { buildMemoryContext, loadMemory } from "@/lib/memory-store";
import { requestManager } from "@/lib/request-manager";
import { openClawSend, subscribeToClaudeStatus } from "@/lib/openclaw-singleton";
import {
  type BestAnswer,
  type SynthesizedAnswer,
  type OrchestratorProvider,
  type OrchestratorTurn,
  loadOrchestratorHistory,
  saveOrchestratorHistory,
} from "@/lib/orchestrator-store";
import type { ConnectionStatus } from "@/lib/openclaw-client";

const MASTER_SESSION_KEY =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_ORCHESTRATOR_SESSION) ||
  "agent:main:master";

const DEFAULT_OPENAI_MODEL = "gpt-4o-mini";
const DEFAULT_GEMINI_MODEL = "gemini-2.5-flash";

const ALL_PROVIDERS: OrchestratorProvider[] = ["claude", "chatgpt", "gemini"];

// ── SSE helper ────────────────────────────────────────────────────────────────

function parseSseChunk(
  buffer: string,
  chunk: string,
  onEvent: (data: string) => void,
): string {
  const combined = buffer + chunk;
  const parts = combined.split("\n\n");
  for (let i = 0; i < parts.length - 1; i++) {
    const part = parts[i].trim();
    if (part.startsWith("data: ")) onEvent(part.slice(6));
  }
  return parts[parts.length - 1];
}

// ── Module-level streaming ────────────────────────────────────────────────────

async function runOrchestratorOpenAiStream(
  provider: string,
  apiMessages: { role: string; content: string }[],
  model: string,
  token: string | null,
): Promise<void> {
  try {
    const baseUrl = getApiBaseUrl();
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = `Bearer ${token}`;

    const response = await fetch(`${baseUrl}/api/v1/openai/chat/stream`, {
      method: "POST",
      headers,
      body: JSON.stringify({ messages: apiMessages, model }),
    });

    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as { detail?: string } | null;
      requestManager.fail(provider, body?.detail ?? `HTTP ${response.status}`);
      return;
    }

    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let sseBuffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      sseBuffer = parseSseChunk(sseBuffer, decoder.decode(value), (data) => {
        try {
          const parsed = JSON.parse(data) as { delta?: string; error?: string };
          if (parsed.delta) requestManager.appendDelta(provider, parsed.delta);
          if (parsed.error) requestManager.fail(provider, parsed.error);
        } catch { /* ignore malformed SSE */ }
      });
    }
    requestManager.complete(provider);
  } catch (err) {
    const msg = err instanceof Error ? err.message : "OpenAI request failed";
    console.error("[Orchestrator] OpenAI stream error:", msg);
    requestManager.fail(provider, msg);
  }
}

async function runOrchestratorGeminiStream(
  provider: string,
  apiMessages: { role: string; content: string }[],
  model: string,
  token: string | null,
): Promise<void> {
  try {
    const baseUrl = getApiBaseUrl();
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = `Bearer ${token}`;

    const response = await fetch(`${baseUrl}/api/v1/gemini/chat/stream`, {
      method: "POST",
      headers,
      body: JSON.stringify({ messages: apiMessages, model }),
    });

    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as { detail?: string } | null;
      requestManager.fail(provider, body?.detail ?? `HTTP ${response.status}`);
      return;
    }

    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let sseBuffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      sseBuffer = parseSseChunk(sseBuffer, decoder.decode(value), (data) => {
        try {
          const parsed = JSON.parse(data) as { delta?: string; error?: string };
          if (parsed.delta) requestManager.appendDelta(provider, parsed.delta);
          if (parsed.error) requestManager.fail(provider, parsed.error);
        } catch { /* ignore malformed SSE */ }
      });
    }
    requestManager.complete(provider);
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Gemini request failed";
    console.error("[Orchestrator] Gemini stream error:", msg);
    requestManager.fail(provider, msg);
  }
}

// ── Judge call ────────────────────────────────────────────────────────────────

async function callJudge(
  question: string,
  responses: Record<OrchestratorProvider, string>,
  memoryContext: string,
  token: string | null,
): Promise<BestAnswer> {
  const baseUrl = getApiBaseUrl();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${baseUrl}/api/v1/judge/evaluate`, {
    method: "POST",
    headers,
    body: JSON.stringify({ question, responses, memory_context: memoryContext }),
  });

  if (!res.ok) {
    const err = (await res.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(err?.detail ?? `HTTP ${res.status}`);
  }

  const data = (await res.json()) as {
    best: OrchestratorProvider;
    reasoning: string;
    scores: { claude: number; chatgpt: number; gemini: number };
  };

  if (!data || typeof data.best !== "string") {
    throw new Error("Judge returned malformed response");
  }

  return {
    provider: data.best,
    text: responses[data.best] ?? "",
    reasoning: data.reasoning ?? "",
    scores: data.scores ?? { claude: 0, chatgpt: 0, gemini: 0 },
  };
}

// ── Synthesis call ────────────────────────────────────────────────────────────

async function callSynthesizer(
  question: string,
  responses: Record<OrchestratorProvider, string>,
  memoryContext: string,
  token: string | null,
): Promise<SynthesizedAnswer> {
  const baseUrl = getApiBaseUrl();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${baseUrl}/api/v1/synthesize/generate`, {
    method: "POST",
    headers,
    body: JSON.stringify({ question, responses, memory_context: memoryContext }),
  });

  if (!res.ok) {
    const err = (await res.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(err?.detail ?? `HTTP ${res.status}`);
  }

  const data = (await res.json()) as { synthesis: string; model_used: string };

  if (!data || typeof data.synthesis !== "string") {
    throw new Error("Synthesizer returned malformed response");
  }

  return {
    text: data.synthesis,
    modelUsed: data.model_used ?? "unknown",
  };
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export interface MasterChatState {
  turns: OrchestratorTurn[];
  isSending: boolean;
  claudeStatus: ConnectionStatus;
  sendMessage: (text: string) => Promise<boolean>;
  clearHistory: () => void;
}

export function useMasterChat(): MasterChatState {
  const { getToken } = useAuth();
  const getTokenRef = useRef(getToken);
  useEffect(() => { getTokenRef.current = getToken; }, [getToken]);

  // ── IMPORTANT: Start with empty state so server and client initial renders match.
  // Load from localStorage in useEffect (client-only) to avoid hydration mismatch.
  const [turns, setTurns] = useState<OrchestratorTurn[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [claudeStatus, setClaudeStatus] = useState<ConnectionStatus>("idle");

  const activeTurnIdRef = useRef<string | null>(null);

  // Load persisted turns after mount (client-only, avoids SSR hydration mismatch)
  useEffect(() => {
    try {
      const stored = loadOrchestratorHistory();
      console.log("[Orchestrator] Loaded history:", stored.length, "turns");
      if (stored.length > 0) setTurns(stored);
    } catch (err) {
      console.error("[Orchestrator] Failed to load history:", err);
    }
  }, []);

  // Subscribe to Claude WS connection status
  useEffect(() => {
    try {
      return subscribeToClaudeStatus(setClaudeStatus);
    } catch (err) {
      console.error("[Orchestrator] Failed to subscribe to Claude status:", err);
      return undefined;
    }
  }, []);

  // Subscribe to requestManager for live streaming text
  useEffect(() => {
    try {
      return requestManager.subscribe(() => {
        const turnId = activeTurnIdRef.current;
        if (!turnId) return;

        try {
          setTurns((prev) =>
            prev.map((t) => {
              if (t.id !== turnId) return t;
              const results = { ...(t.results ?? {}) };
              let changed = false;
              for (const p of ALL_PROVIDERS) {
                const req = requestManager.getActive(`master:${p}`);
                if (req && (req.status === "pending" || req.status === "streaming")) {
                  results[p] = { text: req.partialText ?? "", streaming: true };
                  changed = true;
                }
              }
              return changed ? { ...t, results } : t;
            }),
          );
        } catch (err) {
          console.error("[Orchestrator] requestManager subscriber error:", err);
        }
      });
    } catch (err) {
      console.error("[Orchestrator] Failed to subscribe to requestManager:", err);
      return undefined;
    }
  }, []);

  const sendMessage = useCallback(
    async (userText: string): Promise<boolean> => {
      if (isSending) return false;

      const token = await getTokenRef.current();
      const turnId = crypto.randomUUID();
      const now = new Date().toISOString();

      const newTurn: OrchestratorTurn = {
        id: turnId,
        userText: String(userText ?? ""),
        createdAt: now,
        results: {},
        judging: false,
        synthesizing: false,
      };

      activeTurnIdRef.current = turnId;
      setIsSending(true);
      setTurns((prev) => [...(prev ?? []), newTurn]);

      let memCtx = "";
      try { memCtx = buildMemoryContext(loadMemory()) ?? ""; } catch { /* ignore */ }

      const apiMessages: { role: string; content: string }[] = [
        ...(memCtx ? [{ role: "system", content: memCtx }] : []),
        { role: "user", content: userText },
      ];

      const completed = new Map<OrchestratorProvider, { text: string; error?: string }>();

      const onProviderDone = (
        p: OrchestratorProvider,
        responseText: string,
        error?: string,
      ): void => {
        try {
          completed.set(p, { text: responseText ?? "", error });

          setTurns((prev) =>
            (prev ?? []).map((t) =>
              t.id !== turnId
                ? t
                : {
                    ...t,
                    results: {
                      ...(t.results ?? {}),
                      [p]: { text: responseText ?? "", streaming: false, error },
                    },
                  },
            ),
          );

          if (completed.size < ALL_PROVIDERS.length) return;

          // All providers done
          activeTurnIdRef.current = null;
          setIsSending(false);

          const responses: Record<OrchestratorProvider, string> = {
            claude: completed.get("claude")?.text ?? "",
            chatgpt: completed.get("chatgpt")?.text ?? "",
            gemini: completed.get("gemini")?.text ?? "",
          };

          console.log("[Orchestrator] All providers done. Starting judge + synthesis in parallel...");

          const hasAny = ALL_PROVIDERS.some((pr) => (responses[pr]?.length ?? 0) > 0);
          if (!hasAny) {
            setTurns((prev) => {
              const next = (prev ?? []).map((t) =>
                t.id === turnId
                  ? { ...t, judging: false, synthesizing: false, judgeError: "All providers failed to respond." }
                  : t,
              );
              try { saveOrchestratorHistory(next); } catch { /* ignore */ }
              return next;
            });
            return;
          }

          // Count how many providers actually responded
          const respondedCount = ALL_PROVIDERS.filter((pr) => (responses[pr]?.length ?? 0) > 0).length;

          // Start judging and synthesizing in parallel
          setTurns((prev) =>
            (prev ?? []).map((t) =>
              t.id === turnId
                ? { ...t, judging: true, synthesizing: respondedCount > 1 }
                : t,
            ),
          );

          // ── Judge ──────────────────────────────────────────────────────────
          void callJudge(userText, responses, memCtx, token)
            .then((bestAnswer) => {
              console.log("[Orchestrator] Judge result:", bestAnswer.provider);
              setTurns((prev) => {
                const next = (prev ?? []).map((t) =>
                  t.id !== turnId ? t : { ...t, judging: false, bestAnswer },
                );
                try { saveOrchestratorHistory(next); } catch { /* ignore */ }
                return next;
              });
            })
            .catch((err) => {
              const msg = err instanceof Error ? err.message : "Judge evaluation failed";
              console.error("[Orchestrator] Judge error:", msg);
              setTurns((prev) => {
                const next = (prev ?? []).map((t) =>
                  t.id !== turnId ? t : { ...t, judging: false, judgeError: msg },
                );
                try { saveOrchestratorHistory(next); } catch { /* ignore */ }
                return next;
              });
            });

          // ── Synthesis ──────────────────────────────────────────────────────
          // Skip if only one provider responded (callSynthesizer handles it but
          // the loading state would be misleading — just silently skip the UI spinner)
          if (respondedCount > 0) {
            void callSynthesizer(userText, responses, memCtx, token)
              .then((synthesizedAnswer) => {
                console.log("[Orchestrator] Synthesis complete via:", synthesizedAnswer.modelUsed);
                setTurns((prev) => {
                  const next = (prev ?? []).map((t) =>
                    t.id !== turnId ? t : { ...t, synthesizing: false, synthesizedAnswer },
                  );
                  try { saveOrchestratorHistory(next); } catch { /* ignore */ }
                  return next;
                });
              })
              .catch((err) => {
                const msg = err instanceof Error ? err.message : "Synthesis failed";
                console.error("[Orchestrator] Synthesis error:", msg);
                setTurns((prev) => {
                  const next = (prev ?? []).map((t) =>
                    t.id !== turnId ? t : { ...t, synthesizing: false, synthesisError: msg },
                  );
                  try { saveOrchestratorHistory(next); } catch { /* ignore */ }
                  return next;
                });
              });
          }
        } catch (err) {
          console.error("[Orchestrator] onProviderDone error:", err);
        }
      };

      // Register callbacks BEFORE starting streams
      for (const p of ALL_PROVIDERS) {
        requestManager.onComplete(`master:${p}`, (finalText) =>
          onProviderDone(p, finalText ?? ""),
        );
        requestManager.onFail(`master:${p}`, (errorMsg) =>
          onProviderDone(p, "", errorMsg ?? "Provider failed"),
        );
      }

      // Fan out — all three in parallel
      const claudeText = memCtx ? `${memCtx}\n\n---\n\n${userText}` : userText;
      void openClawSend("master:claude", MASTER_SESSION_KEY, claudeText).catch((err) => {
        const msg = err instanceof Error ? err.message : "Claude unavailable";
        console.error("[Orchestrator] Claude send error:", msg);
        if (!requestManager.getActive("master:claude")) {
          onProviderDone("claude", "", msg);
        } else {
          requestManager.fail("master:claude", msg);
        }
      });

      const chatgptId = crypto.randomUUID();
      requestManager.start("master:chatgpt", chatgptId);
      void runOrchestratorOpenAiStream("master:chatgpt", apiMessages, DEFAULT_OPENAI_MODEL, token);

      const geminiId = crypto.randomUUID();
      requestManager.start("master:gemini", geminiId);
      void runOrchestratorGeminiStream("master:gemini", apiMessages, DEFAULT_GEMINI_MODEL, token);

      return true;
    },
    [isSending],
  );

  const clearHistory = useCallback(() => {
    setTurns([]);
    try { saveOrchestratorHistory([]); } catch { /* ignore */ }
  }, []);

  return { turns, isSending, claudeStatus, sendMessage, clearHistory };
}

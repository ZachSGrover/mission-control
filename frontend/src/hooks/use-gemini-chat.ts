"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "@/auth/clerk";
import type { ChatState } from "@/components/templates/AiChatPage";
import type { ChatMessage } from "@/hooks/use-openclaw-chat";
import { getApiBaseUrl } from "@/lib/api-base";
import type { ConnectionStatus } from "@/lib/openclaw-client";
import { clearChatHistory, loadChatHistory, saveChatHistory } from "@/lib/chat-store";
import { buildMemoryContext, loadMemory } from "@/lib/memory-store";
import { getCachedStatus, setCachedStatus } from "@/lib/provider-status-cache";
import { requestManager } from "@/lib/request-manager";

const DEFAULT_GEMINI_MODEL = "gemini-2.5-flash";

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

// ── Module-level streaming function ─────────────────────────────────────────

async function executeGeminiStream(opts: {
  provider: string;
  assistantMsgId: string;
  preRequestMessages: ChatMessage[];
  userMsg: ChatMessage;
  apiMessages: { role: string; content: string }[];
  model: string;
  baseUrl: string;
  token: string | null;
}) {
  const { provider, assistantMsgId, preRequestMessages, userMsg, apiMessages, model, baseUrl, token } = opts;

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  try {
    const response = await fetch(`${baseUrl}/api/v1/gemini/chat/stream`, {
      method: "POST",
      headers,
      body: JSON.stringify({ messages: apiMessages, model }),
    });

    if (!response.ok) {
      const body = await response.json().catch(() => null) as { detail?: string } | null;
      requestManager.fail(provider, body?.detail ?? `HTTP ${response.status}`);
      saveChatHistory(provider, [
        ...preRequestMessages, userMsg,
        { id: assistantMsgId, role: "assistant" as const, text: "", streaming: false, error: body?.detail ?? `HTTP ${response.status}`, createdAt: new Date().toISOString() },
      ]);
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
          const parsed = JSON.parse(data) as { delta?: string; done?: boolean; error?: string };
          if (parsed.delta) requestManager.appendDelta(provider, parsed.delta);
          if (parsed.error) requestManager.fail(provider, parsed.error);
        } catch { /* ignore */ }
      });
    }

    const finalText = requestManager.getActive(provider)?.partialText ?? "";
    saveChatHistory(provider, [
      ...preRequestMessages, userMsg,
      { id: assistantMsgId, role: "assistant", text: finalText, streaming: false, createdAt: new Date().toISOString() },
    ]);
    requestManager.complete(provider);
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Request failed";
    requestManager.fail(provider, msg);
    saveChatHistory(provider, [
      ...preRequestMessages, userMsg,
      { id: assistantMsgId, role: "assistant" as const, text: "", streaming: false, error: msg, createdAt: new Date().toISOString() },
    ]);
  }
}

// ── Hook ─────────────────────────────────────────────────────────────────────

export function useGeminiChat(model?: string, provider = "gemini"): ChatState & { isConfigured: boolean; isReconnected: boolean } {
  const { getToken } = useAuth();
  const getTokenRef = useRef(getToken);
  useEffect(() => { getTokenRef.current = getToken; }, [getToken]);

  const modelRef = useRef(model ?? DEFAULT_GEMINI_MODEL);
  useEffect(() => { modelRef.current = model ?? DEFAULT_GEMINI_MODEL; }, [model]);

  // Start with [] so server and client initial renders match (avoids SSR hydration mismatch).
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  // Use cached value instantly if available — prevents "Connecting…" flash on tab switch.
  const cached = getCachedStatus("gemini");
  const [status, setStatus] = useState<ConnectionStatus>(cached !== null ? (cached ? "connected" : "error") : "connecting");
  const [isSending, setIsSending] = useState(false);
  const [isConfigured, setIsConfigured] = useState(cached ?? false);
  const [isReconnected, setIsReconnected] = useState(false);

  const historyRef = useRef<ChatMessage[]>([]);
  useEffect(() => { historyRef.current = messages; }, [messages]);

  // Guard so the persist effect never runs with the empty initial state,
  // which would wipe localStorage before the load effect restores it.
  const persistReadyRef = useRef(false);

  // Load persisted history after mount (client-only)
  useEffect(() => {
    persistReadyRef.current = true;
    try {
      const stored = loadChatHistory(provider);
      if (stored.length > 0) setMessages(stored);
    } catch { /* ignore */ }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Persist messages on every change (skips initial empty render)
  useEffect(() => {
    if (!persistReadyRef.current) return;
    saveChatHistory(provider, messages);
  }, [messages, provider]);

  // Check API key — skip fetch if cache is fresh (prevents re-fetch on every tab switch)
  useEffect(() => {
    const fresh = getCachedStatus("gemini");
    if (fresh !== null) {
      setIsConfigured(fresh);
      setStatus(fresh ? "connected" : "error");
      return; // cache hit — no fetch needed
    }
    let cancelled = false;
    (async () => {
      try {
        const baseUrl = getApiBaseUrl();
        const token = await getTokenRef.current();
        const headers: Record<string, string> = {};
        if (token) headers["Authorization"] = `Bearer ${token}`;
        const res = await fetch(`${baseUrl}/api/v1/gemini/status`, { headers });
        if (cancelled) return;
        if (res.ok) {
          const body = await res.json() as { configured: boolean };
          setCachedStatus("gemini", body.configured);
          setIsConfigured(body.configured);
          setStatus(body.configured ? "connected" : "error");
        } else {
          setStatus("error");
        }
      } catch {
        if (!cancelled) setStatus("error");
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // On mount: reconnect to any active request that survived a tab switch
  useEffect(() => {
    const req = requestManager.getActive(provider);
    if (!req) return;

    setIsSending(true);
    setIsReconnected(true);
    const t = setTimeout(() => setIsReconnected(false), 2500);

    setMessages((prev) => {
      const exists = prev.some((m) => m.id === req.assistantMsgId);
      if (exists) {
        return prev.map((m) =>
          m.id === req.assistantMsgId
            ? { ...m, text: req.partialText, streaming: true }
            : m,
        );
      }
      return [...prev, { id: req.assistantMsgId, role: "assistant", text: req.partialText, streaming: true }];
    });

    return () => clearTimeout(t);
  }, [provider]); // eslint-disable-line react-hooks/exhaustive-deps

  // Subscribe to request manager while this tab is mounted
  useEffect(() => {
    return requestManager.subscribe(() => {
      const req = requestManager.getActive(provider);

      if (!req) {
        setIsSending(false);
        setMessages((prev) =>
          prev.map((m) => (m.streaming ? { ...m, streaming: false } : m)),
        );
        return;
      }

      setIsSending(true);
      setMessages((prev) => {
        const exists = prev.some((m) => m.id === req.assistantMsgId);
        if (exists) {
          return prev.map((m) =>
            m.id === req.assistantMsgId
              ? {
                  ...m,
                  text: req.partialText,
                  streaming: req.status !== "complete" && req.status !== "error",
                  error: req.status === "error" ? req.errorMsg : undefined,
                }
              : m,
          );
        }
        return [
          ...prev,
          {
            id: req.assistantMsgId,
            role: "assistant",
            text: req.partialText,
            streaming: req.status !== "complete" && req.status !== "error",
          },
        ];
      });
    });
  }, [provider]);

  const sendMessage = useCallback(
    async (text: string): Promise<boolean> => {
      if (status !== "connected" || isSending) return false;

      const userMsg: ChatMessage = { id: crypto.randomUUID(), role: "user", text, streaming: false, createdAt: new Date().toISOString() };
      const assistantMsgId = crypto.randomUUID();

      setMessages((prev) => [
        ...prev,
        userMsg,
        { id: assistantMsgId, role: "assistant", text: "", streaming: true },
      ]);
      setIsSending(true);

      const preRequestMessages = historyRef.current.slice();
      const memCtx = buildMemoryContext(loadMemory());
      const apiMessages: { role: string; content: string }[] = [
        ...(memCtx ? [{ role: "system", content: memCtx }] : []),
        ...preRequestMessages.map((m) => ({ role: m.role, content: m.text })),
        { role: userMsg.role, content: userMsg.text },
      ];

      requestManager.start(provider, assistantMsgId);

      const token = await getTokenRef.current();
      void executeGeminiStream({
        provider,
        assistantMsgId,
        preRequestMessages,
        userMsg,
        apiMessages,
        model: modelRef.current,
        baseUrl: getApiBaseUrl(),
        token,
      });

      return true;
    },
    [status, isSending, provider],
  );

  const clearMessages = useCallback(() => {
    setMessages([]);
    clearChatHistory(provider);
  }, [provider]);

  return { messages, status, isSending, sendMessage, clearMessages, isConfigured, isReconnected };
}

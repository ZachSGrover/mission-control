"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { type ConnectionStatus } from "@/lib/openclaw-client";
import { openClawSend, subscribeToClaudeStatus } from "@/lib/openclaw-singleton";
import { requestManager } from "@/lib/request-manager";
import { clearChatHistory, loadChatHistory, saveChatHistory } from "@/lib/chat-store";
import { buildMemoryContext, loadMemory } from "@/lib/memory-store";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  streaming: boolean;
  error?: string;
  createdAt?: string; // ISO timestamp — used for journal activity collection
}

const DEFAULT_SESSION_KEY =
  process.env.NEXT_PUBLIC_OPENCLAW_SESSION ?? "agent:main:missioncontrol";

export function useOpenClawChat(
  sessionKey?: string,
  model?: string,
  provider = "claude",
) {
  const effectiveSession = sessionKey ?? DEFAULT_SESSION_KEY;
  void model; // model param kept for API compat; OpenClaw doesn't accept it in chat.send

  // Start with [] so server and client initial renders match (avoids SSR hydration mismatch).
  // Load from localStorage in useEffect (client-only).
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<ConnectionStatus>("idle");
  const [isSending, setIsSending] = useState(false);
  const [isReconnected, setIsReconnected] = useState(false);

  // Keep ref in sync with messages state so closures can read latest history
  const historyRef = useRef<ChatMessage[]>([]);
  useEffect(() => { historyRef.current = messages; }, [messages]);

  // Guard so the persist effect never runs with the empty initial state,
  // which would wipe localStorage before the load effect restores it.
  const persistReadyRef = useRef(false);

  // Load persisted history after mount (client-only)
  useEffect(() => {
    persistReadyRef.current = true; // mark ready before any setMessages
    try {
      const stored = loadChatHistory(provider);
      if (stored.length > 0) setMessages(stored);
    } catch { /* ignore */ }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Persist messages to localStorage whenever they change.
  // Skips the initial empty render so we don't overwrite real stored data.
  useEffect(() => {
    if (!persistReadyRef.current) return;
    saveChatHistory(provider, messages);
  }, [messages, provider]);

  // Subscribe to singleton connection status (WS never disconnects on unmount)
  useEffect(() => {
    return subscribeToClaudeStatus(setStatus);
  }, []);

  // On mount: reconnect to any active request that survived a tab switch
  useEffect(() => {
    const req = requestManager.getActive(provider);
    if (!req) return;

    setIsSending(true);
    setIsReconnected(true);
    const t = setTimeout(() => setIsReconnected(false), 2500);

    // Inject the in-progress assistant message into local state
    setMessages((prev) => {
      const exists = prev.some((m) => m.id === req.assistantMsgId);
      if (exists) {
        return prev.map((m) =>
          m.id === req.assistantMsgId
            ? { ...m, text: req.partialText, streaming: true }
            : m,
        );
      }
      return [
        ...prev,
        { id: req.assistantMsgId, role: "assistant", text: req.partialText, streaming: true },
      ];
    });

    return () => clearTimeout(t);
  }, [provider]); // eslint-disable-line react-hooks/exhaustive-deps

  // Subscribe to request manager updates while this tab is active
  useEffect(() => {
    return requestManager.subscribe(() => {
      const req = requestManager.getActive(provider);

      if (!req) {
        // Request completed or errored — stop spinner, finalise any streaming msg
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

      // Inject memory into the message text
      const memCtx = buildMemoryContext(loadMemory());
      const textToSend = memCtx ? `${memCtx}\n\n---\n\n${text}` : text;

      // Snapshot history BEFORE mutating state (historyRef is one render behind,
      // which is exactly what we want: history without the new message)
      const preMessages = historyRef.current.slice();
      const userMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "user",
        text,      // show clean text in UI (not memory-injected version)
        streaming: false,
        createdAt: new Date().toISOString(),
      };

      setMessages((prev) => [...prev, userMsg]);
      setIsSending(true);

      // Register a save callback that fires on completion even if this component
      // is unmounted (e.g. user switched tabs mid-stream).
      // The closure captures preMessages and userMsg which persist in memory.
      requestManager.onComplete(provider, (finalText, assistantMsgId) => {
        saveChatHistory(provider, [
          ...preMessages,
          userMsg,
          { id: assistantMsgId, role: "assistant", text: finalText, streaming: false, createdAt: new Date().toISOString() },
        ]);
      });
      requestManager.onFail(provider, (errorMsg, assistantMsgId) => {
        saveChatHistory(provider, [
          ...preMessages,
          userMsg,
          { id: assistantMsgId, role: "assistant", text: "", streaming: false, error: errorMsg, createdAt: new Date().toISOString() },
        ]);
      });

      try {
        // openClawSend uses the persistent singleton — not cancelled on unmount
        await openClawSend(provider, effectiveSession, textToSend);
        return true;
      } catch (err) {
        const errMsg = err instanceof Error ? err.message : "Failed to send";
        setMessages((prev) => [
          ...prev,
          { id: crypto.randomUUID(), role: "assistant", text: "", streaming: false, error: errMsg },
        ]);
        setIsSending(false);
        // Clean up unused callbacks
        requestManager.onComplete(provider, () => {});
        requestManager.onFail(provider, () => {});
        return false;
      }
    },
    [status, isSending, provider, effectiveSession],
  );

  const clearMessages = useCallback(() => {
    setMessages([]);
    clearChatHistory(provider);
  }, [provider]);

  return { messages, status, isSending, sendMessage, clearMessages, isReconnected };
}

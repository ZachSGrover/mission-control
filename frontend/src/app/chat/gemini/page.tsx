"use client";

import { useEffect, useState } from "react";

import { AiChatPage, type ModelOption } from "@/components/templates/AiChatPage";
import { useGeminiChat } from "@/hooks/use-gemini-chat";
import { logProviderSwitch } from "@/lib/action-logger";

const GEMINI_MODELS: ModelOption[] = [
  { value: "gemini-2.5-flash",   label: "Gemini 2.5 Flash" },
  { value: "gemini-2.5-pro",     label: "Gemini 2.5 Pro"   },
];

const STORAGE_KEY = "mc_model_gemini";
const DEFAULT_MODEL = GEMINI_MODELS[0].value;

export default function GeminiPage() {
  // Start with DEFAULT_MODEL so server and client initial renders match.
  // Load stored preference in useEffect (client-only) to avoid hydration mismatch.
  const [model, setModelState] = useState<string>(DEFAULT_MODEL);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored && GEMINI_MODELS.some((m) => m.value === stored)) {
        setModelState(stored);
      }
    } catch { /* ignore */ }
    // Track provider switch — burst of 3+ switches auto-triggers journal
    logProviderSwitch("Gemini", "/chat/gemini");
  }, []);

  const setModel = (next: string) => {
    setModelState(next);
    try { localStorage.setItem(STORAGE_KEY, next); } catch { /* ignore */ }
  };

  const chat = useGeminiChat(model);

  // Only show banner after status resolves — prevents flash during the status check
  const banner = chat.status !== "connecting" && !chat.isConfigured
    ? "Gemini requires a Google API key. Add it in Settings → API Keys."
    : undefined;

  return (
    <AiChatPage
      provider="Gemini"
      chat={chat}
      banner={banner}
      models={GEMINI_MODELS}
      model={model}
      onModelChange={setModel}
    />
  );
}

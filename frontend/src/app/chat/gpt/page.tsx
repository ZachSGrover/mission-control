"use client";

import { useEffect, useState } from "react";

import { AiChatPage, type ModelOption } from "@/components/templates/AiChatPage";
import { useOpenAiChat } from "@/hooks/use-openai-chat";
import { logProviderSwitch } from "@/lib/action-logger";

const OPENAI_MODELS: ModelOption[] = [
  { value: "gpt-4o-mini", label: "GPT-4o mini" },
  { value: "gpt-4o",      label: "GPT-4o"      },
];

const STORAGE_KEY = "mc_model_chatgpt";
const DEFAULT_MODEL = OPENAI_MODELS[0].value;

export default function ChatGptPage() {
  // Start with DEFAULT_MODEL so server and client initial renders match.
  // Load stored preference in useEffect (client-only) to avoid hydration mismatch.
  const [model, setModelState] = useState<string>(DEFAULT_MODEL);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored && OPENAI_MODELS.some((m) => m.value === stored)) {
        // Restore persisted selection on mount; cannot run during SSR render.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setModelState(stored);
      }
    } catch { /* ignore */ }
    // Track provider switch — burst of 3+ switches auto-triggers journal
    logProviderSwitch("ChatGPT", "/chat/gpt");
  }, []);

  const setModel = (next: string) => {
    setModelState(next);
    try { localStorage.setItem(STORAGE_KEY, next); } catch { /* ignore */ }
  };

  const chat = useOpenAiChat(model);

  // Only show banner after status resolves — prevents flash during the status check
  const banner = chat.status !== "connecting" && !chat.isConfigured
    ? "ChatGPT requires an OpenAI API key. Add it in Settings → API Keys."
    : undefined;

  return (
    <AiChatPage
      provider="ChatGPT"
      chat={chat}
      banner={banner}
      models={OPENAI_MODELS}
      model={model}
      onModelChange={setModel}
    />
  );
}

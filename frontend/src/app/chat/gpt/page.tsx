"use client";

import { useEffect, useState } from "react";

import { AiChatPage, type ModelOption } from "@/components/templates/AiChatPage";
import { useOpenAiChat } from "@/hooks/use-openai-chat";

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
        setModelState(stored);
      }
    } catch { /* ignore */ }
  }, []);

  const setModel = (next: string) => {
    setModelState(next);
    try { localStorage.setItem(STORAGE_KEY, next); } catch { /* ignore */ }
  };

  const chat = useOpenAiChat(model);

  const banner = !chat.isConfigured
    ? "ChatGPT requires an OpenAI API key. Add OPENAI_API_KEY to backend/.env and restart the backend."
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

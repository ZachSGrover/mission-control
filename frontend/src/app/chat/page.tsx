"use client";

import { useState } from "react";

import { AiChatPage, type ModelOption } from "@/components/templates/AiChatPage";
import { useOpenClawChat } from "@/hooks/use-openclaw-chat";

const SESSION_KEY =
  process.env.NEXT_PUBLIC_OPENCLAW_SESSION ?? "agent:main:missioncontrol";

// Claw is the single assistant. The dropdown below picks the model that
// powers the response — Deep / Balanced / Fast map to real Claude models.
const CLAW_MODELS: ModelOption[] = [
  { value: "claude-sonnet-4-6", label: "Balanced" },
  { value: "claude-opus-4-6",   label: "Deep"     },
  { value: "claude-haiku-4-5",  label: "Fast"     },
];

const STORAGE_KEY = "mc_model_claw";
const DEFAULT_MODEL = CLAW_MODELS[0].value;

export default function ClawChatPage() {
  const [model, setModelState] = useState<string>(() => {
    if (typeof window === "undefined") return DEFAULT_MODEL;
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored && CLAW_MODELS.some((m) => m.value === stored)) return stored;
    } catch { /* ignore */ }
    return DEFAULT_MODEL;
  });

  const setModel = (next: string) => {
    setModelState(next);
    try { localStorage.setItem(STORAGE_KEY, next); } catch { /* ignore */ }
  };

  const chat = useOpenClawChat(SESSION_KEY, model);

  return (
    <AiChatPage
      provider="Claw"
      chat={chat}
      models={CLAW_MODELS}
      model={model}
      onModelChange={setModel}
    />
  );
}

"use client";

import { useState } from "react";

import { AiChatPage, type ModelOption } from "@/components/templates/AiChatPage";
import { useOpenClawChat } from "@/hooks/use-openclaw-chat";

const SESSION_KEY =
  process.env.NEXT_PUBLIC_OPENCLAW_SESSION ?? "agent:main:missioncontrol";

// Claw is the primary chat for Digital OS. It runs on the local OpenClaw
// gateway and defaults to the balanced Sonnet model — Opus and Haiku remain
// available via the selector for deep reasoning or quick replies.
const CLAW_MODELS: ModelOption[] = [
  { value: "claude-sonnet-4-6", label: "Sonnet (balanced)" },
  { value: "claude-opus-4-6",   label: "Opus (deep)"      },
  { value: "claude-haiku-4-5",  label: "Haiku (fast)"     },
];

const STORAGE_KEY = "mc_model_claw";
const DEFAULT_MODEL = CLAW_MODELS[0].value;

export default function ClawChatPage() {
  // Lazy init reads the stored preference on first client render.
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

  const banner = chat.status === "connecting"
    ? "Connecting to local gateway…"
    : chat.status === "error" || chat.status === "idle"
    ? "Claw requires the OpenClaw Gateway running locally (ws://localhost:18789). This provider is local-only and is not available in the cloud deployment."
    : undefined;

  return (
    <AiChatPage
      provider="Claw"
      chat={chat}
      banner={banner}
      models={CLAW_MODELS}
      model={model}
      onModelChange={setModel}
    />
  );
}

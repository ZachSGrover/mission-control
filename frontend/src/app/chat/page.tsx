"use client";

import { useEffect, useState } from "react";

import { AiChatPage, type ModelOption } from "@/components/templates/AiChatPage";
import { useOpenClawChat } from "@/hooks/use-openclaw-chat";

const SESSION_KEY =
  process.env.NEXT_PUBLIC_OPENCLAW_SESSION ?? "agent:main:missioncontrol";

const CLAUDE_MODELS: ModelOption[] = [
  { value: "claude-haiku-4-5",  label: "Haiku"   },
  { value: "claude-sonnet-4-6", label: "Sonnet"  },
  { value: "claude-opus-4-6",   label: "Opus"    },
];

const STORAGE_KEY = "mc_model_claude";
const DEFAULT_MODEL = CLAUDE_MODELS[0].value;

export default function ClaudeChatPage() {
  // Start with DEFAULT_MODEL so server and client initial renders match.
  // Load the stored preference in useEffect (client-only) to avoid hydration mismatch.
  const [model, setModelState] = useState<string>(DEFAULT_MODEL);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored && CLAUDE_MODELS.some((m) => m.value === stored)) {
        setModelState(stored);
      }
    } catch { /* ignore */ }
  }, []);

  const setModel = (next: string) => {
    setModelState(next);
    try { localStorage.setItem(STORAGE_KEY, next); } catch { /* ignore */ }
  };

  const chat = useOpenClawChat(SESSION_KEY, model);

  // Show a clear status banner — never let the UI look broken without explanation.
  const banner = chat.status === "connecting"
    ? "Connecting to Claude gateway…"
    : chat.status === "error" || chat.status === "idle"
    ? "Claude requires the OpenClaw Gateway running locally (ws://localhost:18789). This provider is local-only and is not available in the cloud deployment."
    : undefined;

  return (
    <AiChatPage
      provider="Claude"
      chat={chat}
      banner={banner}
      models={CLAUDE_MODELS}
      model={model}
      onModelChange={setModel}
    />
  );
}

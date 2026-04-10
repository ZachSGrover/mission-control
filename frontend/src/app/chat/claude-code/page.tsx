"use client";

import { AiChatPage } from "@/components/templates/AiChatPage";
import { useOpenClawChat } from "@/hooks/use-openclaw-chat";

export default function ClaudeCodePage() {
  const chat = useOpenClawChat("agent:main:claude-code");
  return (
    <AiChatPage
      provider="Claude Code"
      chat={chat}
      banner="Claude Code integration is coming soon."
    />
  );
}

"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Mic, RefreshCw } from "lucide-react";

import { Markdown } from "@/components/atoms/Markdown";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import type { ChatMessage } from "@/hooks/use-openclaw-chat";
import {
  deriveClawdiusViewState,
  type ClawdiusTone,
  type ClawdiusViewState,
} from "@/lib/clawdius-status";
import type { ConnectionStatus } from "@/lib/openclaw-client";
import {
  isGatewayConfigured,
  isGatewayTokenConfigured,
  resetGatewayConnection,
} from "@/lib/openclaw-singleton";

// ── Shared chat state interface ────────────────────────────────────────────

export interface ChatState {
  messages: ChatMessage[];
  status: ConnectionStatus;
  isSending: boolean;
  sendMessage: (text: string) => Promise<boolean>;
  clearMessages: () => void;
  isReconnected?: boolean;
}

export interface ModelOption {
  value: string;
  label: string;
}

// ── Model selector ──────────────────────────────────────────────────────────

function ModelSelector({
  models,
  value,
  onChange,
}: {
  models: ModelOption[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="text-xs rounded-md border border-slate-200 bg-white px-2 py-1 text-slate-500 cursor-pointer hover:border-slate-300 hover:text-slate-700 focus:outline-none focus:ring-1 focus:ring-blue-400 transition-colors"
    >
      {models.map((m) => (
        <option key={m.value} value={m.value}>
          {m.label}
        </option>
      ))}
    </select>
  );
}

// ── Status dot ─────────────────────────────────────────────────────────────
//
// Mission Control can be online while the OpenClaw gateway is not. The pill
// distinguishes "Online", "Connecting", "Gateway not configured", "Gateway
// token missing", "Gateway unreachable", and "Ready" so the operator can tell
// what to do (paste a token, click Reconnect, re-auth Cloudflare Access) when
// chat is not reachable. Inputs come from the singleton getters; the derive
// is a pure helper covered by clawdius-status.test.ts.

const TONE_DOT: Record<ClawdiusTone, string> = {
  ok:      "bg-emerald-500",
  pending: "bg-yellow-400 animate-pulse",
  warn:    "bg-amber-500",
  error:   "bg-rose-500",
  muted:   "bg-slate-400",
};

function ClawdiusStatusPill({
  view,
  onReconnect,
}: {
  view: ClawdiusViewState;
  onReconnect: () => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <span
        title={view.hint}
        className="flex items-center gap-1.5 text-xs text-slate-500"
        data-testid="clawdius-status"
        data-status-kind={view.kind}
      >
        <span className={`inline-block h-2 w-2 rounded-full ${TONE_DOT[view.tone]}`} />
        {view.label}
      </span>
      {view.needsSettings && (
        <Link
          href="/settings"
          data-testid="clawdius-status-settings"
          className="text-xs text-blue-600 hover:underline"
        >
          Open Settings
        </Link>
      )}
      {view.canReconnect && (
        <button
          type="button"
          onClick={onReconnect}
          data-testid="clawdius-status-reconnect"
          className="flex items-center gap-1 rounded-md border border-slate-200 px-2 py-0.5 text-xs text-slate-500 hover:text-slate-700 hover:border-slate-300 transition-colors"
          title="Reset the OpenClaw connection and try again"
        >
          <RefreshCw className="h-3 w-3" />
          Reconnect
        </button>
      )}
    </div>
  );
}

// ── Message bubble ──────────────────────────────────────────────────────────

function MessageBubble({
  role,
  text,
  streaming,
  error,
}: {
  role: "user" | "assistant";
  text: string;
  streaming: boolean;
  error?: string;
}) {
  const isUser = role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[75%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? "bg-[var(--accent)] text-white rounded-br-sm"
            : "bg-white border border-slate-200 text-slate-800 rounded-bl-sm shadow-sm"
        }`}
      >
        {error ? (
          <span className="text-red-500 italic">{error}</span>
        ) : isUser ? (
          <span className="whitespace-pre-wrap">{text}</span>
        ) : (
          <div className="prose prose-sm max-w-none prose-p:my-1 prose-pre:my-2">
            <Markdown content={text || " "} variant="basic" />
            {streaming && (
              <span className="inline-block h-3 w-1.5 animate-pulse rounded-sm bg-slate-400 align-middle ml-0.5" />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Inline chat input ───────────────────────────────────────────────────────

function AiChatInput({
  placeholder,
  isSending,
  disabled,
  onSend,
}: {
  placeholder: string;
  isSending: boolean;
  disabled: boolean;
  onSend: (text: string) => Promise<boolean>;
}) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!isSending) textareaRef.current?.focus();
  }, [isSending]);

  const send = useCallback(async () => {
    const trimmed = value.trim();
    if (!trimmed || isSending || disabled) return;
    const ok = await onSend(trimmed);
    if (ok) setValue("");
  }, [value, isSending, disabled, onSend]);

  return (
    <div className="mt-4 flex flex-col gap-2">
      <textarea
        ref={textareaRef}
        rows={3}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            void send();
          }
        }}
        placeholder={placeholder}
        disabled={isSending || disabled}
        className="w-full resize-none rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:opacity-50"
      />
      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => void send()}
          disabled={isSending || disabled || !value.trim()}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40 transition-colors"
        >
          {isSending ? "Sending…" : "Send"}
        </button>
      </div>
    </div>
  );
}

// ── Chat content ────────────────────────────────────────────────────────────

function AiChatContent({
  provider,
  chat,
  banner,
  models,
  model,
  onModelChange,
  voicePlaceholder = false,
}: {
  provider: string;
  chat: ChatState;
  banner?: string;
  models?: ModelOption[];
  model?: string;
  onModelChange?: (model: string) => void;
  voicePlaceholder?: boolean;
}) {
  const { messages, status, isSending, sendMessage, clearMessages, isReconnected } = chat;
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Recompute the gateway config snapshot on the client only — the singleton
  // getters read window.location and localStorage, both unavailable in SSR.
  // The status callback fires whenever the user saves a token (via
  // resetGatewayConnection → "idle"), so we re-read on each status change.
  const [gatewayConfigured, setGatewayConfigured] = useState(false);
  const [tokenConfigured, setTokenConfigured] = useState(false);
  useEffect(() => {
    // Reading the singleton getters requires window / localStorage, so we
    // cannot do it during SSR render. Same SSR-bridge pattern as ClawChatPage.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setGatewayConfigured(isGatewayConfigured());
    setTokenConfigured(isGatewayTokenConfigured());
  }, [status]);

  const view = deriveClawdiusViewState({
    status,
    gatewayConfigured,
    tokenConfigured,
  });

  const handleReconnect = useCallback(() => {
    resetGatewayConnection();
  }, []);

  return (
    <main className="flex flex-col overflow-hidden h-full flex-1">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-4 shrink-0">
        <div>
          <h1 className="text-base font-semibold text-slate-900">{provider}</h1>
          <p className="text-xs text-slate-500">Your assistant</p>
        </div>
        <div className="flex items-center gap-3">
          {models && model && onModelChange && (
            <ModelSelector models={models} value={model} onChange={onModelChange} />
          )}
          {voicePlaceholder && (
            <button
              type="button"
              disabled
              aria-label="Voice Mode"
              title="Voice Mode coming next: talk to Clawdius through your headset."
              className="rounded-md p-1.5 text-slate-300 cursor-not-allowed"
            >
              <Mic className="h-4 w-4" />
            </button>
          )}
          {isSending && (
            <span className="flex items-center gap-1.5 text-xs text-slate-400">
              <span className="h-1.5 w-1.5 rounded-full bg-blue-500 animate-pulse" />
              {isReconnected ? "Reconnected" : "Running…"}
            </span>
          )}
          <ClawdiusStatusPill view={view} onReconnect={handleReconnect} />
          {messages.length > 0 && (
            <button
              onClick={clearMessages}
              className="text-xs text-slate-400 hover:text-slate-600 transition-colors"
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {/* Optional info / warning banner */}
      {banner && (
        <div className="mx-6 mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 shrink-0">
          {banner}
        </div>
      )}

      {/* Message list */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        {messages.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center text-slate-400">
              <p className="text-2xl mb-2">💬</p>
              <p className="text-sm font-medium">
                {view.kind === "connected" || view.kind === "idle"
                  ? `Send a message to ${provider}`
                  : view.label}
              </p>
              <p className="mt-1 text-xs text-slate-400 max-w-sm mx-auto">
                {view.hint}
              </p>
            </div>
          </div>
        ) : (
          <div className="mx-auto max-w-2xl space-y-4">
            {messages.map((msg) => (
              <MessageBubble
                key={msg.id}
                role={msg.role}
                text={msg.text}
                streaming={msg.streaming}
                error={msg.error}
              />
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-slate-200 bg-white px-6 pb-6 shrink-0">
        <div className="mx-auto max-w-2xl">
          <AiChatInput
            placeholder={`Message ${provider}…`}
            isSending={isSending}
            disabled={!view.canSend}
            onSend={sendMessage}
          />
        </div>
      </div>
    </main>
  );
}

// ── Page wrapper ────────────────────────────────────────────────────────────

export interface AiChatPageProps {
  provider: string;
  chat: ChatState;
  banner?: string;
  models?: ModelOption[];
  model?: string;
  onModelChange?: (model: string) => void;
  // When true, renders a disabled microphone icon next to the model selector.
  // Placeholder for Voice Mode — see /guide#voice.
  voicePlaceholder?: boolean;
}

// Always renders sidebar + content regardless of auth state.
// Clerk redirect guards are incompatible with Electron (no external auth flow).
export function AiChatPage({
  provider,
  chat,
  banner,
  models,
  model,
  onModelChange,
  voicePlaceholder,
}: AiChatPageProps) {
  return (
    <DashboardShell>
      <DashboardSidebar />
      <AiChatContent
        provider={provider}
        chat={chat}
        banner={banner}
        models={models}
        model={model}
        onModelChange={onModelChange}
        voicePlaceholder={voicePlaceholder}
      />
    </DashboardShell>
  );
}

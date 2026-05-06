"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Circle,
  Loader2,
  Sparkles,
  Star,
  Target,
  Trash2,
  Trophy,
  XCircle,
  Zap,
} from "lucide-react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { Markdown } from "@/components/atoms/Markdown";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { useMasterChat } from "@/hooks/use-master-chat";
import { useExecutionMode } from "@/hooks/use-execution-mode";
import type { ExecutionMode } from "@/hooks/use-execution-mode";
import { useOperator } from "@/hooks/use-operator";
import type { MasterChatState } from "@/hooks/use-master-chat";
import type { OperatorState } from "@/hooks/use-operator";
import type { OrchestratorTurn, OrchestratorProvider } from "@/lib/orchestrator-store";
import type { OperatorSession, OperatorStep, StepType } from "@/lib/operator-store";

// ── Types ──────────────────────────────────────────────────────────────────────
type Mode = "chat" | "operator";

// ── Provider meta ─────────────────────────────────────────────────────────────
const PROVIDER_LABEL: Record<OrchestratorProvider, string> = {
  claude: "Claude",
  chatgpt: "ChatGPT",
  gemini: "Gemini",
};
const PROVIDER_COLOR: Record<OrchestratorProvider, string> = {
  claude: "text-amber-400",
  chatgpt: "text-emerald-400",
  gemini: "text-blue-400",
};

// ── Step meta ─────────────────────────────────────────────────────────────────
const STEP_TYPE_LABEL: Record<StepType, string> = {
  research: "Research",
  write: "Write",
  analyze: "Analyze",
  decide: "Decide",
};
const STEP_TYPE_COLOR: Record<StepType, string> = {
  research: "text-blue-400",
  write: "text-emerald-400",
  analyze: "text-amber-400",
  decide: "text-purple-400",
};
const STEP_PROVIDER_LABEL: Record<StepType, string> = {
  research: "Gemini",
  write: "ChatGPT",
  analyze: "Claude",
  decide: "Claude",
};

// ── Score bar ─────────────────────────────────────────────────────────────────
function ScoreBar({ score }: { score: number }) {
  const pct = Math.round(Math.max(0, Math.min(10, score ?? 0)) * 10);
  return (
    <div className="flex items-center gap-2 min-w-[80px]">
      <div className="h-1 rounded-full flex-1" style={{ background: "var(--surface-muted)" }}>
        <div className="h-1 rounded-full" style={{ width: `${pct}%`, background: "var(--accent)" }} />
      </div>
      <span className="text-[10px] tabular-nums w-5 text-right" style={{ color: "var(--text-quiet)" }}>
        {(score ?? 0).toFixed(1)}
      </span>
    </div>
  );
}

// ── Synthesized card ──────────────────────────────────────────────────────────
function SynthesizedCard({ turn }: { turn: OrchestratorTurn }) {
  const { synthesizing, synthesizedAnswer, synthesisError } = turn;
  if (!synthesizing && !synthesizedAnswer && !synthesisError) return null;
  return (
    <div
      className="rounded-xl p-5 space-y-3"
      style={{
        background: "linear-gradient(135deg, var(--surface-strong) 0%, var(--surface) 100%)",
        border: "1px solid var(--accent)",
        boxShadow: "0 0 0 1px color-mix(in srgb, var(--accent) 20%, transparent)",
      }}
    >
      <div className="flex items-center gap-2">
        <Sparkles className="h-4 w-4 shrink-0" style={{ color: "var(--accent)" }} />
        <span className="text-xs font-bold uppercase tracking-widest" style={{ color: "var(--accent)" }}>
          Synthesized Answer
        </span>
        {synthesizedAnswer?.modelUsed && synthesizedAnswer.modelUsed !== "passthrough" && (
          <span className="ml-auto text-[10px] px-1.5 py-0.5 rounded" style={{ background: "var(--surface-muted)", color: "var(--text-quiet)" }}>
            via {synthesizedAnswer.modelUsed}
          </span>
        )}
      </div>
      {synthesizing ? (
        <div className="flex items-center gap-2" style={{ color: "var(--text-muted)" }}>
          <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" style={{ color: "var(--accent)" }} />
          <span className="text-sm">Synthesizing best answer…</span>
        </div>
      ) : synthesisError ? (
        <div className="flex items-start gap-2">
          <AlertCircle className="h-3.5 w-3.5 shrink-0 mt-0.5 text-red-400" />
          <p className="text-sm text-red-400">{synthesisError}</p>
        </div>
      ) : synthesizedAnswer ? (
        <div
          className="text-sm leading-relaxed prose prose-sm max-w-none prose-p:my-1.5 prose-pre:my-2 prose-headings:text-sm prose-headings:font-semibold"
          style={{ color: "var(--text)" }}
        >
          <Markdown content={synthesizedAnswer.text} variant="basic" />
        </div>
      ) : null}
    </div>
  );
}

// ── Best individual answer card ───────────────────────────────────────────────
function BestAnswerCard({ turn }: { turn: OrchestratorTurn }) {
  const { judging, bestAnswer, judgeError } = turn;
  if (!judging && !bestAnswer && !judgeError) return null;
  return (
    <div
      className="rounded-xl p-4 space-y-2"
      style={{ background: "var(--surface-strong)", border: "1px solid var(--border-strong)" }}
    >
      <div className="flex items-center gap-2">
        <Trophy className="h-3.5 w-3.5 shrink-0" style={{ color: "var(--text-quiet)" }} />
        <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>
          Best Individual
        </span>
        {bestAnswer && (
          <span className={`text-xs font-medium ${PROVIDER_COLOR[bestAnswer.provider]}`}>
            — {PROVIDER_LABEL[bestAnswer.provider]}
          </span>
        )}
      </div>
      {judging ? (
        <div className="flex items-center gap-2" style={{ color: "var(--text-muted)" }}>
          <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" style={{ color: "var(--accent)" }} />
          <span className="text-sm">Evaluating responses…</span>
        </div>
      ) : judgeError ? (
        <div className="flex items-start gap-2">
          <AlertCircle className="h-3.5 w-3.5 shrink-0 mt-0.5 text-red-400" />
          <span className="text-sm text-red-400">{judgeError}</span>
        </div>
      ) : bestAnswer ? (
        <>
          <p className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: "var(--text-muted)" }}>
            {bestAnswer.text}
          </p>
          {bestAnswer.reasoning && (
            <p className="text-[11px] italic mt-1" style={{ color: "var(--text-quiet)" }}>
              {bestAnswer.reasoning}
            </p>
          )}
        </>
      ) : null}
    </div>
  );
}

// ── Provider card ─────────────────────────────────────────────────────────────
function ProviderCard({
  provider,
  result,
  score,
  isBest,
}: {
  provider: OrchestratorProvider;
  result?: { text: string; streaming: boolean; error?: string };
  score?: number;
  isBest?: boolean;
}) {
  const isEmpty = !result?.text && !result?.streaming && !result?.error;
  return (
    <div
      className="rounded-xl p-4 space-y-2"
      style={{
        background: "var(--surface-strong)",
        border: `1px solid ${isBest ? "var(--accent)" : "var(--border)"}`,
      }}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className={`text-xs font-semibold ${PROVIDER_COLOR[provider]}`}>
            {PROVIDER_LABEL[provider]}
          </span>
          {isBest && (
            <span className="flex items-center gap-0.5 text-[10px] font-semibold px-1.5 py-0.5 rounded" style={{ background: "var(--accent)", color: "#fff" }}>
              <Star className="h-2.5 w-2.5" /> Best
            </span>
          )}
          {result?.streaming && (
            <span className="flex items-center gap-1 text-[10px]" style={{ color: "var(--text-quiet)" }}>
              <span className="inline-block h-1.5 w-1.5 rounded-full animate-pulse" style={{ background: "var(--accent)" }} />
              Streaming…
            </span>
          )}
        </div>
        {score !== undefined && <ScoreBar score={score} />}
      </div>
      {result?.error ? (
        <div className="flex items-start gap-2">
          <AlertCircle className="h-3.5 w-3.5 shrink-0 mt-0.5 text-red-400" />
          <p className="text-sm text-red-400">{result.error}</p>
        </div>
      ) : isEmpty ? (
        <p className="text-sm" style={{ color: "var(--text-quiet)" }}>
          {result?.streaming ? "Waiting…" : "No response"}
        </p>
      ) : (
        <p className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: "var(--text)" }}>
          {result?.text ?? ""}
          {result?.streaming && (
            <span className="inline-block w-0.5 h-3.5 ml-0.5 align-middle animate-pulse" style={{ background: "var(--accent)" }} />
          )}
        </p>
      )}
    </div>
  );
}

// ── Turn card ─────────────────────────────────────────────────────────────────
function TurnCard({ turn }: { turn: OrchestratorTurn }) {
  const isStreaming = Object.values(turn.results ?? {}).some((r) => r?.streaming);
  const isActive = turn.judging || turn.synthesizing || isStreaming;
  const [expanded, setExpanded] = useState(isActive);
  const scores = turn.bestAnswer?.scores;

  useEffect(() => {
    // Sync external "isActive" signal to local expand state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (isActive) setExpanded(true);
  }, [isActive]);

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <div className="max-w-[75%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed" style={{ background: "var(--accent)", color: "#fff" }}>
          {turn.userText}
        </div>
      </div>
      <SynthesizedCard turn={turn} />
      <BestAnswerCard turn={turn} />
      {isStreaming && !turn.synthesizing && !turn.judging && (
        <div className="rounded-xl px-4 py-3 flex items-center gap-2" style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}>
          <span className="inline-block h-1.5 w-1.5 rounded-full animate-pulse" style={{ background: "var(--accent)" }} />
          <span className="text-sm" style={{ color: "var(--text-muted)" }}>Collecting responses…</span>
        </div>
      )}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-1.5 text-xs transition-opacity hover:opacity-70 pl-0.5"
        style={{ color: "var(--text-quiet)" }}
      >
        {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        {expanded ? "Hide" : "Show"} individual responses
      </button>
      {expanded && (
        <div className="space-y-2">
          {(["claude", "chatgpt", "gemini"] as OrchestratorProvider[]).map((p) => (
            <ProviderCard
              key={p}
              provider={p}
              result={turn.results?.[p]}
              score={scores?.[p]}
              isBest={turn.bestAnswer?.provider === p}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Step status icon ──────────────────────────────────────────────────────────
function StepStatusIcon({ status }: { status: OperatorStep["status"] }) {
  if (status === "pending") return <Circle className="h-4 w-4 shrink-0" style={{ color: "var(--text-quiet)" }} />;
  if (status === "running") return <Loader2 className="h-4 w-4 shrink-0 animate-spin" style={{ color: "var(--accent)" }} />;
  if (status === "done")    return <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />;
  return <XCircle className="h-4 w-4 shrink-0 text-red-400" />;
}

// ── Step row ──────────────────────────────────────────────────────────────────
function StepRow({ step, index }: { step: OperatorStep; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const hasContent = Boolean(step.result ?? step.error);

  useEffect(() => {
    // Auto-expand once the step transitions to done with a result.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (step.status === "done" && step.result) setExpanded(true);
  }, [step.status, step.result]);

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{
        background: "var(--surface-strong)",
        border: `1px solid ${
          step.status === "running" ? "var(--accent)"
          : step.status === "error" ? "rgb(248 113 113 / 0.4)"
          : "var(--border)"
        }`,
        transition: "border-color 0.2s",
      }}
    >
      <button
        type="button"
        onClick={() => hasContent && setExpanded((v) => !v)}
        className="w-full flex items-start gap-3 px-4 py-3 text-left"
        style={{ cursor: hasContent ? "pointer" : "default" }}
      >
        <div className="mt-0.5"><StepStatusIcon status={step.status} /></div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: "var(--text-quiet)" }}>
              Step {index + 1}
            </span>
            <span className={`text-[10px] font-semibold uppercase tracking-wide ${STEP_TYPE_COLOR[step.type]}`}>
              {STEP_TYPE_LABEL[step.type]}
            </span>
            {step.status === "pending" && (
              <span className="text-[10px]" style={{ color: "var(--text-quiet)" }}>
                → {STEP_PROVIDER_LABEL[step.type]}
              </span>
            )}
            {step.provider && step.status !== "pending" && (
              <span className="text-[10px]" style={{ color: "var(--text-quiet)" }}>
                via {step.provider}
              </span>
            )}
          </div>
          <p className="text-sm mt-0.5 leading-snug" style={{ color: "var(--text)" }}>{step.task}</p>
        </div>
        {hasContent && (
          <span className="shrink-0 mt-1" style={{ color: "var(--text-quiet)" }}>
            {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </span>
        )}
      </button>
      {expanded && hasContent && (
        <div className="px-4 pb-4 pt-0 border-t" style={{ borderColor: "var(--border)" }}>
          {step.error ? (
            <div className="flex items-start gap-2 mt-3">
              <AlertCircle className="h-3.5 w-3.5 shrink-0 mt-0.5 text-red-400" />
              <p className="text-sm text-red-400">{step.error}</p>
            </div>
          ) : step.result ? (
            <div
              className="mt-3 text-sm leading-relaxed prose prose-sm max-w-none prose-p:my-1.5 prose-pre:my-2 prose-headings:text-sm prose-headings:font-semibold"
              style={{ color: "var(--text-muted)" }}
            >
              <Markdown content={step.result} variant="basic" />
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

// ── Operator session view ─────────────────────────────────────────────────────
function OperatorSessionView({ session }: { session: OperatorSession }) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const doneCount = session.steps.filter((s) => s.status === "done").length;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [session.phase, session.currentStepIndex]);

  return (
    <div className="space-y-4 max-w-2xl mx-auto">
      {/* Objective card */}
      <div
        className="rounded-xl p-4 flex items-start gap-3"
        style={{
          background: "linear-gradient(135deg, var(--surface-strong) 0%, var(--surface) 100%)",
          border: "1px solid var(--accent)",
          boxShadow: "0 0 0 1px color-mix(in srgb, var(--accent) 20%, transparent)",
        }}
      >
        <Target className="h-4 w-4 shrink-0 mt-0.5" style={{ color: "var(--accent)" }} />
        <div className="flex-1 min-w-0">
          <p className="text-[10px] font-bold uppercase tracking-widest mb-1" style={{ color: "var(--accent)" }}>
            Objective
          </p>
          <p className="text-sm leading-snug font-medium" style={{ color: "var(--text)" }}>
            {session.objective}
          </p>
          {session.goal && session.goal !== session.objective && (
            <p className="text-xs mt-1" style={{ color: "var(--text-quiet)" }}>→ {session.goal}</p>
          )}
        </div>
        {/* Phase badge */}
        <div
          className="shrink-0 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide rounded-full px-2.5 py-1"
          style={{
            background:
              session.phase === "done" ? "rgb(52 211 153 / 0.15)"
              : session.phase === "error" ? "rgb(248 113 113 / 0.15)"
              : "color-mix(in srgb, var(--accent) 15%, transparent)",
            color:
              session.phase === "done" ? "rgb(52 211 153)"
              : session.phase === "error" ? "rgb(248 113 113)"
              : "var(--accent)",
          }}
        >
          {(session.phase === "planning" || session.phase === "executing") && <Loader2 className="h-3 w-3 animate-spin" />}
          {session.phase === "done" && <CheckCircle2 className="h-3 w-3" />}
          {session.phase === "error" && <XCircle className="h-3 w-3" />}
          <span>
            {session.phase === "planning" && "Planning…"}
            {session.phase === "executing" && `${doneCount} / ${session.steps.length}`}
            {session.phase === "done" && "Complete"}
            {session.phase === "error" && "Error"}
            {session.phase === "idle" && "Idle"}
          </span>
        </div>
      </div>

      {/* Planning spinner */}
      {session.phase === "planning" && (
        <div className="rounded-xl px-4 py-3 flex items-center gap-2" style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}>
          <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" style={{ color: "var(--accent)" }} />
          <span className="text-sm" style={{ color: "var(--text-muted)" }}>Building execution plan…</span>
        </div>
      )}

      {/* Fatal error */}
      {session.phase === "error" && session.error && (
        <div className="rounded-xl px-4 py-3 flex items-start gap-2" style={{ background: "var(--surface-strong)", border: "1px solid rgb(248 113 113 / 0.4)" }}>
          <AlertCircle className="h-3.5 w-3.5 shrink-0 mt-0.5 text-red-400" />
          <p className="text-sm text-red-400">{session.error}</p>
        </div>
      )}

      {/* Steps */}
      {session.steps.length > 0 && (
        <div className="space-y-2">
          {session.steps.map((step, i) => (
            <StepRow key={step.id} step={step} index={i} />
          ))}
        </div>
      )}

      {/* Insights */}
      {session.insights.length > 0 && (
        <div className="rounded-xl p-4 space-y-3" style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}>
          <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>
            Memory Insights Stored
          </p>
          <div className="space-y-2">
            {session.insights.map((ins, i) => (
              <div key={i} className="flex items-start gap-2">
                <span
                  className="text-[9px] font-bold uppercase tracking-wide rounded px-1.5 py-0.5 shrink-0 mt-0.5"
                  style={{
                    background:
                      ins.type === "decision" ? "rgb(167 139 250 / 0.2)"
                      : ins.type === "context" ? "rgb(96 165 250 / 0.2)"
                      : "rgb(52 211 153 / 0.15)",
                    color:
                      ins.type === "decision" ? "rgb(167 139 250)"
                      : ins.type === "context" ? "rgb(96 165 250)"
                      : "rgb(52 211 153)",
                  }}
                >
                  {ins.type}
                </span>
                <p className="text-xs leading-snug" style={{ color: "var(--text-muted)" }}>
                  {ins.content}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}

// ── Chat view ─────────────────────────────────────────────────────────────────
interface ChatViewProps { chat: MasterChatState }

function ChatView({ chat }: ChatViewProps) {
  const { turns, isSending, sendMessage } = chat;
  const [inputText, setInputText] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (turns.length > 0) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns.length]);

  const handleSend = useCallback(async () => {
    const text = inputText.trim();
    if (!text || isSending) return;
    setInputText("");
    await sendMessage(text);
    inputRef.current?.focus();
  }, [inputText, isSending, sendMessage]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void handleSend();
    }
  };

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex-1 overflow-y-auto px-6 py-6">
        {turns.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center space-y-3">
            <div className="h-12 w-12 rounded-full flex items-center justify-center" style={{ background: "var(--surface-strong)" }}>
              <Sparkles className="h-6 w-6" style={{ color: "var(--accent)" }} />
            </div>
            <p className="text-sm font-medium" style={{ color: "var(--text)" }}>Ask anything</p>
            <p className="text-sm max-w-sm leading-relaxed" style={{ color: "var(--text-quiet)" }}>
              Claude, ChatGPT, and Gemini respond simultaneously. Answers are ranked and synthesized.
            </p>
          </div>
        ) : (
          <div className="max-w-2xl mx-auto space-y-10">
            {turns.map((turn) => <TurnCard key={turn.id} turn={turn} />)}
            <div ref={bottomRef} />
          </div>
        )}
      </div>
      <div className="shrink-0 px-6 py-4" style={{ borderTop: "1px solid var(--border)", background: "var(--bg)" }}>
        <div className="max-w-2xl mx-auto">
          <div className="flex items-end gap-3 rounded-xl px-4 py-3" style={{ background: "var(--surface-strong)", border: "1px solid var(--border-strong)" }}>
            <textarea
              ref={inputRef}
              rows={1}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={isSending ? "Waiting for responses…" : "Ask all three AIs at once…"}
              disabled={isSending}
              className="flex-1 resize-none bg-transparent text-sm focus:outline-none disabled:opacity-50"
              style={{ color: "var(--text)", minHeight: "24px", maxHeight: "120px" }}
            />
            <button
              type="button"
              onClick={() => void handleSend()}
              disabled={!inputText.trim() || isSending}
              className="shrink-0 rounded-lg px-4 py-1.5 text-sm font-medium text-white transition-opacity hover:opacity-80 disabled:opacity-40"
              style={{ background: "var(--accent)" }}
            >
              {isSending ? <Loader2 className="h-4 w-4 animate-spin" /> : "Send"}
            </button>
          </div>
          <p className="mt-1.5 text-[10px] text-center" style={{ color: "var(--text-quiet)" }}>
            Enter to send · Shift+Enter for new line
          </p>
        </div>
      </div>
    </div>
  );
}

// ── Operator view ─────────────────────────────────────────────────────────────
interface OperatorViewProps {
  op: OperatorState;
  executionMode: ExecutionMode;
}

function OperatorView({ op, executionMode }: OperatorViewProps) {
  const { sessions, isRunning, startSession } = op;
  const [text, setText] = useState("");
  const isLocalMode = executionMode === "local";

  const handleSend = useCallback(() => {
    const trimmed = text.trim();
    if (!trimmed || isRunning || isLocalMode) return;
    setText("");
    void startSession(trimmed, executionMode);
  }, [text, isRunning, isLocalMode, executionMode, startSession]);

  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex-1 overflow-y-auto px-6 py-6">
        {sessions.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center space-y-3">
            <div className="h-12 w-12 rounded-full flex items-center justify-center" style={{ background: "var(--surface-strong)" }}>
              <Zap className="h-6 w-6" style={{ color: "var(--accent)" }} />
            </div>
            <p className="text-sm font-medium" style={{ color: "var(--text)" }}>Operator Mode</p>
            <p className="text-sm max-w-sm leading-relaxed" style={{ color: "var(--text-quiet)" }}>
              Give an objective. The system plans steps, routes each to the best AI, executes in order, and stores insights to memory.
            </p>
          </div>
        ) : (
          <div className="space-y-12">
            {sessions.map((session) => (
              <OperatorSessionView key={session.id} session={session} />
            ))}
          </div>
        )}
      </div>
      <div className="shrink-0 px-6 py-4" style={{ borderTop: "1px solid var(--border)", background: "var(--bg)" }}>
        <div className="max-w-2xl mx-auto">
          {isLocalMode && (
            <div
              className="mb-2 rounded-lg px-3 py-2 text-xs text-center"
              style={{ background: "rgb(251 191 36 / 0.1)", border: "1px solid rgb(251 191 36 / 0.3)", color: "rgb(251 191 36)" }}
            >
              Local mode — execution disabled. Switch to System to run.
            </div>
          )}
          <div
            className="flex items-end gap-3 rounded-xl px-4 py-3"
            style={{
              background: "var(--surface-strong)",
              border: `1px solid ${isLocalMode ? "rgb(251 191 36 / 0.3)" : "var(--border-strong)"}`,
            }}
          >
            <textarea
              rows={1}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={handleKey}
              placeholder={
                isLocalMode ? "Local mode — switch to System to execute…"
                : isRunning ? "Executing…"
                : sessions.length > 0 ? "New objective…"
                : "Enter an objective to execute…"
              }
              disabled={isRunning || isLocalMode}
              className="flex-1 resize-none bg-transparent text-sm focus:outline-none disabled:opacity-50"
              style={{ color: "var(--text)", minHeight: "24px", maxHeight: "120px" }}
            />
            <button
              type="button"
              onClick={handleSend}
              disabled={!text.trim() || isRunning || isLocalMode}
              className="shrink-0 rounded-lg px-4 py-1.5 text-sm font-medium text-white transition-opacity hover:opacity-80 disabled:opacity-40 flex items-center gap-1.5"
              style={{ background: isLocalMode ? "var(--surface-muted)" : "var(--accent)" }}
            >
              {isRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <><Zap className="h-3.5 w-3.5" /> Execute</>}
            </button>
          </div>
          <p className="mt-1.5 text-[10px] text-center" style={{ color: "var(--text-quiet)" }}>
            {isLocalMode
              ? "Local mode active · No external calls · Memory not modified"
              : "Enter to execute · Plans steps automatically · Routes to best AI · Stores insights to memory"}
          </p>
        </div>
      </div>
    </div>
  );
}

// ── Execution mode toggle ─────────────────────────────────────────────────────
const EXEC_MODES: { value: ExecutionMode; label: string; title: string }[] = [
  { value: "local",    label: "Local",    title: "No external calls — local UI and memory only" },
  { value: "system",   label: "System",   title: "Normal Mission Control execution" },
  { value: "external", label: "External", title: "Future: allow external integrations (Telegram, agents)" },
];

// ── Main shell — single hook instance, passed as props ────────────────────────
function MasterContent() {
  const [mode, setMode] = useState<Mode>("chat");
  const chat = useMasterChat();
  const op = useOperator();
  const { mode: execMode, setMode: setExecMode } = useExecutionMode();
  const [mounted, setMounted] = useState(false);

  // Hydration flag: must run after mount to avoid SSR/client mismatch.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { setMounted(true); }, []);

  return (
    <div className="flex flex-col h-full">

      {/* ── Tab bar ──────────────────────────────────────────────────────────── */}
      <div
        className="shrink-0 flex items-stretch"
        style={{ borderBottom: "2px solid var(--border)", background: "var(--surface)" }}
      >
        {/* Mode tabs */}
        <button
          type="button"
          onClick={() => setMode("chat")}
          className="flex items-center gap-2 px-6 py-3 text-sm font-semibold transition-all"
          style={{
            borderBottom: mode === "chat" ? "2px solid var(--accent)" : "2px solid transparent",
            marginBottom: "-2px",
            color: mode === "chat" ? "var(--accent)" : "var(--text-quiet)",
            background: "transparent",
          }}
        >
          <Sparkles className="h-4 w-4" />
          Chat
        </button>
        <button
          type="button"
          onClick={() => setMode("operator")}
          className="flex items-center gap-2 px-6 py-3 text-sm font-semibold transition-all"
          style={{
            borderBottom: mode === "operator" ? "2px solid var(--accent)" : "2px solid transparent",
            marginBottom: "-2px",
            color: mode === "operator" ? "var(--accent)" : "var(--text-quiet)",
            background: "transparent",
          }}
        >
          <Zap className="h-4 w-4" />
          Operator
        </button>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Execution mode toggle — only shown in Operator tab */}
        {mode === "operator" && mounted && (
          <div className="flex items-center gap-2 px-4">
            <span className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-quiet)" }}>
              Execution
            </span>
            <div
              className="flex items-center rounded-md p-0.5"
              style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}
            >
              {EXEC_MODES.map(({ value, label, title }) => (
                <button
                  key={value}
                  type="button"
                  title={title}
                  onClick={() => setExecMode(value)}
                  className="px-2.5 py-1 rounded text-[11px] font-medium transition-all"
                  style={{
                    background: execMode === value ? (value === "local" ? "rgb(251 191 36 / 0.2)" : "var(--accent)") : "transparent",
                    color: execMode === value ? (value === "local" ? "rgb(251 191 36)" : "#fff") : "var(--text-quiet)",
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Clear button */}
        <div className="flex items-center px-3">
          {mode === "chat" && chat.turns.length > 0 && !chat.isSending && (
            <button
              type="button"
              onClick={chat.clearHistory}
              className="rounded-md p-1.5 transition-opacity hover:opacity-70"
              style={{ color: "var(--text-quiet)" }}
              title="Clear chat"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          )}
          {mode === "operator" && op.sessions.length > 0 && !op.isRunning && (
            <button
              type="button"
              onClick={op.clearSessions}
              className="rounded-md p-1.5 transition-opacity hover:opacity-70"
              style={{ color: "var(--text-quiet)" }}
              title="Clear sessions"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* ── Body ────────────────────────────────────────────────────────────── */}
      {!mounted ? (
        <div className="flex-1" />
      ) : (
        <div className="flex-1 min-h-0">
          {mode === "chat"
            ? <ChatView chat={chat} />
            : <OperatorView op={op} executionMode={execMode} />
          }
        </div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function MasterChatPage() {
  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel message="Sign in to access Digidle OS" forceRedirectUrl="/chat/master" />
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <main className="flex-1 overflow-hidden" style={{ background: "var(--bg)" }}>
          <ErrorBoundary>
            <MasterContent />
          </ErrorBoundary>
        </main>
      </SignedIn>
    </DashboardShell>
  );
}

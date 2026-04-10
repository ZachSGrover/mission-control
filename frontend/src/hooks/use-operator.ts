"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { getLocalAuthToken } from "@/auth/localAuth";
import { getApiBaseUrl } from "@/lib/api-base";
import type { ExecutionMode } from "@/lib/execution-mode-store";
import { buildMemoryContext, inferArea, inferProject, loadMemory, saveMemory } from "@/lib/memory-store";
import type { MemoryEntry } from "@/lib/memory-store";
import {
  type OperatorInsight,
  type OperatorSession,
  type OperatorStep,
  type StepType,
  loadOperatorSessions,
  saveOperatorSessions,
} from "@/lib/operator-store";

// ── Provider routing ──────────────────────────────────────────────────────────

const STEP_PROVIDER: Record<StepType, "claude" | "chatgpt" | "gemini"> = {
  research: "gemini",
  write: "chatgpt",
  analyze: "claude",
  decide: "claude",
};

// ── API helpers ───────────────────────────────────────────────────────────────

function makeHeaders(): Record<string, string> {
  const token = getLocalAuthToken();
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${getApiBaseUrl()}${path}`, {
    method: "POST",
    headers: makeHeaders(),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = (await res.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(err?.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// ── Types ─────────────────────────────────────────────────────────────────────

export interface OperatorState {
  sessions: OperatorSession[];
  activeSession: OperatorSession | null;
  isRunning: boolean;
  startSession: (objective: string, executionMode?: ExecutionMode) => Promise<void>;
  clearSessions: () => void;
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useOperator(): OperatorState {
  const [sessions, setSessions] = useState<OperatorSession[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const runningRef = useRef(false);

  // Load persisted sessions after mount (avoids SSR hydration mismatch)
  useEffect(() => {
    try {
      const stored = loadOperatorSessions();
      if (stored.length > 0) setSessions(stored);
    } catch { /* ignore */ }
  }, []);

  // ── State helpers ──────────────────────────────────────────────────────────

  const updateSessions = useCallback(
    (updater: (prev: OperatorSession[]) => OperatorSession[]) => {
      setSessions((prev) => {
        const next = updater(prev);
        try { saveOperatorSessions(next); } catch { /* quota */ }
        return next;
      });
    },
    [],
  );

  const patchSession = useCallback(
    (id: string, patch: Partial<OperatorSession>) => {
      updateSessions((prev) =>
        prev.map((s) => (s.id !== id ? s : { ...s, ...patch })),
      );
    },
    [updateSessions],
  );

  const patchStep = useCallback(
    (sessionId: string, stepId: number, patch: Partial<OperatorStep>) => {
      updateSessions((prev) =>
        prev.map((s) =>
          s.id !== sessionId
            ? s
            : {
                ...s,
                steps: s.steps.map((st) =>
                  st.id !== stepId ? st : { ...st, ...patch },
                ),
              },
        ),
      );
    },
    [updateSessions],
  );

  // ── Main execution ─────────────────────────────────────────────────────────

  const startSession = useCallback(
    async (objective: string, executionMode: ExecutionMode = "system") => {
      if (runningRef.current) return;

      // ── Execution mode safeguard ───────────────────────────────────────────
      if (executionMode === "local") {
        console.info("[Operator] Local mode — execution blocked. No external calls made.");
        return;
      }
      // "external" falls through to normal execution (future integrations hook in here)

      runningRef.current = true;
      setIsRunning(true);

      const sessionId = crypto.randomUUID();
      const now = new Date().toISOString();

      // Snapshot memory at start
      let memCtx = "";
      try { memCtx = buildMemoryContext(loadMemory()) ?? ""; } catch { /* ignore */ }

      // Infer project from objective (used when saving insights to memory)
      const project = inferProject(objective);

      // Create session optimistically
      const newSession: OperatorSession = {
        id: sessionId,
        objective,
        goal: "",
        steps: [],
        phase: "planning",
        currentStepIndex: 0,
        insights: [],
        createdAt: now,
      };
      updateSessions((prev) => [newSession, ...prev]);

      try {
        // ── 1. Planning ──────────────────────────────────────────────────────
        console.log("[Operator] Planning:", objective);

        const plan = await apiPost<{
          goal: string;
          steps: { id: number; task: string; type: StepType }[];
        }>("/api/v1/operator/plan", { objective, memory_context: memCtx });

        console.log(`[Operator] Plan: "${plan.goal}" (${plan.steps.length} steps)`);

        const steps: OperatorStep[] = plan.steps.map((s) => ({
          ...s,
          status: "pending" as const,
        }));

        patchSession(sessionId, {
          goal: plan.goal,
          steps,
          phase: "executing",
          currentStepIndex: 0,
        });

        // ── 2. Execute steps sequentially ────────────────────────────────────
        let contextAccumulator = "";
        const sessionInsights: OperatorInsight[] = [];

        for (let i = 0; i < steps.length; i++) {
          const step = steps[i];
          const provider = STEP_PROVIDER[step.type] ?? "claude";

          console.log(
            `[Operator] Step ${i + 1}/${steps.length}: [${step.type} → ${provider}] ${step.task}`,
          );

          patchStep(sessionId, step.id, {
            status: "running",
            startedAt: new Date().toISOString(),
          });
          patchSession(sessionId, { currentStepIndex: i });

          try {
            const exec = await apiPost<{ result: string; provider: string }>(
              "/api/v1/operator/execute",
              {
                task: step.task,
                provider,
                context: contextAccumulator,
                memory_context: memCtx,
              },
            );

            console.log(
              `[Operator] Step ${i + 1} done via ${exec.provider} (${exec.result.length} chars)`,
            );

            patchStep(sessionId, step.id, {
              status: "done",
              result: exec.result,
              provider: exec.provider,
              completedAt: new Date().toISOString(),
            });

            // Build context for next step
            contextAccumulator += `\nStep ${i + 1} — ${step.task}:\n${exec.result}\n`;

            // ── 3. Extract & persist insights ──────────────────────────────
            try {
              const insightRes = await apiPost<{
                insights: { type: string; content: string }[];
              }>("/api/v1/operator/extract-insights", {
                goal: plan.goal,
                step_task: step.task,
                step_result: exec.result,
              });

              if (insightRes.insights.length > 0) {
                console.log(
                  `[Operator] Extracted ${insightRes.insights.length} insight(s) from step ${i + 1}`,
                );

                const newInsights: OperatorInsight[] = insightRes.insights.map((ins) => ({
                  type: ins.type as OperatorInsight["type"],
                  content: ins.content,
                }));

                sessionInsights.push(...newInsights);
                patchSession(sessionId, { insights: [...sessionInsights] });

                // Save to memory store with project/area metadata
                try {
                  const memory = loadMemory();
                  const entries: MemoryEntry[] = newInsights.map((ins) => ({
                    id: crypto.randomUUID(),
                    // "insight" maps to "note" in MemoryType
                    type: ins.type === "insight" ? "note" : (ins.type as MemoryEntry["type"]),
                    content: ins.content,
                    createdAt: new Date().toISOString(),
                    source: `operator:${plan.goal.slice(0, 50)}`,
                    tags: ["operator", step.type],
                    project,
                    area: inferArea(step.type),
                  }));
                  saveMemory([...memory, ...entries]);
                  // Refresh memory context for subsequent steps
                  memCtx = buildMemoryContext([...memory, ...entries]) ?? "";
                } catch { /* ignore quota */ }
              }
            } catch (insightErr) {
              console.warn("[Operator] Insight extraction failed:", insightErr);
            }
          } catch (stepErr) {
            const msg = stepErr instanceof Error ? stepErr.message : "Step failed";
            console.error(`[Operator] Step ${i + 1} error:`, msg);
            patchStep(sessionId, step.id, {
              status: "error",
              error: msg,
              completedAt: new Date().toISOString(),
            });
            // Continue — don't abort the whole session on one step failure
            contextAccumulator += `\nStep ${i + 1} — ${step.task}: [FAILED: ${msg}]\n`;
          }
        }

        // ── 4. Done ──────────────────────────────────────────────────────────
        console.log("[Operator] Session complete:", sessionId);
        patchSession(sessionId, {
          phase: "done",
          completedAt: new Date().toISOString(),
          currentStepIndex: steps.length,
          insights: sessionInsights,
        });
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Session failed";
        console.error("[Operator] Fatal error:", msg);
        patchSession(sessionId, { phase: "error", error: msg });
      } finally {
        runningRef.current = false;
        setIsRunning(false);
      }
    },
    [patchSession, patchStep, updateSessions],
  );

  const clearSessions = useCallback(() => {
    setSessions([]);
    try { saveOperatorSessions([]); } catch { /* ignore */ }
  }, []);

  return {
    sessions,
    activeSession: sessions[0] ?? null,
    isRunning,
    startSession,
    clearSessions,
  };
}

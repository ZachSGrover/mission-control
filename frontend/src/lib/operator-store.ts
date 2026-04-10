// Operator System — session persistence (mc_operator_v1)

const KEY = "mc_operator_v1";
const MAX_SESSIONS = 20;

export type StepStatus = "pending" | "running" | "done" | "error";
export type StepType = "research" | "write" | "analyze" | "decide";
export type OperatorPhase = "idle" | "planning" | "executing" | "done" | "error";
export type InsightType = "context" | "decision" | "insight";

export interface OperatorStep {
  id: number;
  task: string;
  type: StepType;
  status: StepStatus;
  result?: string;
  error?: string;
  provider?: string; // e.g. "claude/claude-sonnet-4-5"
  startedAt?: string;
  completedAt?: string;
}

export interface OperatorInsight {
  type: InsightType;
  content: string;
}

export interface OperatorSession {
  id: string;
  objective: string;
  goal: string;
  steps: OperatorStep[];
  phase: OperatorPhase;
  currentStepIndex: number;
  insights: OperatorInsight[];
  createdAt: string;
  completedAt?: string;
  error?: string;
}

function isValidSession(s: unknown): s is OperatorSession {
  if (typeof s !== "object" || s === null) return false;
  const obj = s as Record<string, unknown>;
  return typeof obj.id === "string" && typeof obj.objective === "string";
}

function sanitizeStep(step: unknown): OperatorStep | null {
  if (typeof step !== "object" || step === null) return null;
  const s = step as Record<string, unknown>;
  if (typeof s.id !== "number" || typeof s.task !== "string") return null;
  return {
    id: s.id,
    task: s.task,
    type: (s.type as StepType) ?? "analyze",
    // Never restore a running state — mark as error so UI is consistent
    status: s.status === "running" ? "error" : (s.status as StepStatus) ?? "pending",
    result: typeof s.result === "string" ? s.result : undefined,
    error: typeof s.error === "string" ? s.error : undefined,
    provider: typeof s.provider === "string" ? s.provider : undefined,
    startedAt: typeof s.startedAt === "string" ? s.startedAt : undefined,
    completedAt: typeof s.completedAt === "string" ? s.completedAt : undefined,
  };
}

function sanitizeSession(s: OperatorSession): OperatorSession {
  const steps = Array.isArray(s.steps)
    ? (s.steps.map(sanitizeStep).filter(Boolean) as OperatorStep[])
    : [];
  return {
    ...s,
    steps,
    // Never restore mid-execution state
    phase: s.phase === "executing" || s.phase === "planning" ? "error" : s.phase,
    insights: Array.isArray(s.insights) ? s.insights : [],
  };
}

export function loadOperatorSessions(): OperatorSession[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isValidSession).map(sanitizeSession);
  } catch {
    try { localStorage.removeItem(KEY); } catch { /* ignore */ }
    return [];
  }
}

export function saveOperatorSessions(sessions: OperatorSession[]): void {
  if (typeof window === "undefined") return;
  try {
    const toSave = sessions.filter(isValidSession).slice(-MAX_SESSIONS);
    localStorage.setItem(KEY, JSON.stringify(toSave));
  } catch { /* quota */ }
}

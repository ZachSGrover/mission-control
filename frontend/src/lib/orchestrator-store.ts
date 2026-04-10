// Orchestrator persistence — mc_master_chat_v1
// Stores multi-provider turn history for the Master Chat orchestrator.

const KEY = "mc_master_chat_v1";
const MAX_TURNS = 100;

export type OrchestratorProvider = "claude" | "chatgpt" | "gemini";

export interface ProviderResult {
  text: string;
  streaming: boolean;
  error?: string;
}

export interface BestAnswer {
  provider: OrchestratorProvider;
  text: string;
  reasoning: string;
  scores: { claude: number; chatgpt: number; gemini: number };
}

export interface SynthesizedAnswer {
  text: string;
  modelUsed: string;  // e.g. "claude/claude-sonnet-4-5" or "openai/gpt-4o"
}

export interface OrchestratorTurn {
  id: string;
  userText: string;
  createdAt: string;
  results: Partial<Record<OrchestratorProvider, ProviderResult>>;
  bestAnswer?: BestAnswer;
  judging: boolean;
  judgeError?: string;
  // Synthesis fields
  synthesizing: boolean;
  synthesizedAnswer?: SynthesizedAnswer;
  synthesisError?: string;
}

function isValidTurn(t: unknown): t is OrchestratorTurn {
  if (typeof t !== "object" || t === null) return false;
  const turn = t as Record<string, unknown>;
  return typeof turn.id === "string" && typeof turn.userText === "string";
}

function sanitizeResult(v: unknown): ProviderResult {
  if (typeof v !== "object" || v === null) {
    return { text: "", streaming: false };
  }
  const r = v as Record<string, unknown>;
  return {
    text: typeof r.text === "string" ? r.text : "",
    streaming: false, // never restore mid-stream
    error: typeof r.error === "string" ? r.error : undefined,
  };
}

function sanitizeTurn(t: OrchestratorTurn): OrchestratorTurn {
  const results: Partial<Record<OrchestratorProvider, ProviderResult>> = {};
  for (const p of ["claude", "chatgpt", "gemini"] as OrchestratorProvider[]) {
    if (t.results?.[p] !== undefined) {
      results[p] = sanitizeResult(t.results[p]);
    }
  }
  return { ...t, judging: false, synthesizing: false, results };
}

export function loadOrchestratorHistory(): OrchestratorTurn[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isValidTurn).map(sanitizeTurn);
  } catch {
    try { localStorage.removeItem(KEY); } catch { /* ignore */ }
    return [];
  }
}

export function saveOrchestratorHistory(turns: OrchestratorTurn[]): void {
  if (typeof window === "undefined") return;
  try {
    const toSave = turns
      .filter(isValidTurn)
      .map((t) => ({ ...t, judging: false, synthesizing: false }))
      .slice(-MAX_TURNS);
    localStorage.setItem(KEY, JSON.stringify(toSave));
  } catch { /* quota */ }
}

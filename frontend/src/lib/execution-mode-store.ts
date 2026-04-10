// ── Execution mode ────────────────────────────────────────────────────────────
// Controls where operator execution is allowed to reach.
//
//  local    — no external API calls; only local UI + memory updates
//  system   — normal Mission Control behavior (default active state)
//  external — future: allow external integrations (Telegram, agents, etc.)

export type ExecutionMode = "local" | "system" | "external";

const KEY = "mc_execution_mode";
export const DEFAULT_EXECUTION_MODE: ExecutionMode = "local";

export function loadExecutionMode(): ExecutionMode {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "local" || v === "system" || v === "external") return v;
  } catch { /* ignore */ }
  return DEFAULT_EXECUTION_MODE;
}

export function saveExecutionMode(mode: ExecutionMode): void {
  try { localStorage.setItem(KEY, mode); } catch { /* ignore */ }
}

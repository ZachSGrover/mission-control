/**
 * system-monitor — singleton background health-check loop.
 *
 * Runs every 45 seconds while the user is signed in.
 * Most ticks are pure localStorage reads (uses provider-status-cache).
 * Network calls happen only when the cache is stale (≤ every 5 min).
 *
 * State machine:
 *   unknown  →  healthy | degraded | failing
 *   healthy  →  degraded | failing
 *   degraded →  healthy (recovery) | failing
 *   failing  →  healthy (recovery) | degraded
 *
 * At 3 consecutive non-healthy checks → runAutoFix("all_providers_failed")
 * On transition back to healthy       → logSystemAction("bug_fix", "System recovered")
 *
 * Mount in DashboardShell:
 *   useEffect(() => {
 *     systemMonitor.start(() => getTokenRef.current());
 *     return () => systemMonitor.stop();
 *   }, []);
 */

import { getApiBaseUrl } from "@/lib/api-base";
import { loadMemory } from "@/lib/memory-store";
import { logSystemAction, writeAutoJournal } from "@/lib/action-logger";
import { getCachedStatus, setCachedStatus } from "@/lib/provider-status-cache";
import { runAutoFix } from "@/lib/auto-fix";

// ── Types ─────────────────────────────────────────────────────────────────────

export type SystemStatus = "unknown" | "healthy" | "degraded" | "failing";

export interface MonitorState {
  status: SystemStatus;
  /** ISO timestamp of the last completed health check. */
  lastCheck: string | null;
  /** ISO timestamp of the last non-healthy check. */
  lastFailure: string | null;
  /** Resets to 0 on a healthy tick, increments otherwise. */
  consecutiveFailures: number;
  /** Total ticks run since start(). */
  checkCount: number;
  /** Per-check detail — shown in tooltip. */
  detail: string;
}

type Subscriber = (state: Readonly<MonitorState>) => void;

interface CheckResult {
  openaiOk: boolean;
  geminiOk: boolean;
  recentErrors: number;
  status: SystemStatus;
}

// ── Constants ─────────────────────────────────────────────────────────────────

/** How often to run a health tick. */
const MONITOR_INTERVAL_MS = 45_000; // 45 s

/** First check fires this long after start() — let the app settle. */
const INITIAL_DELAY_MS = 15_000;    // 15 s

/** Consecutive failures required before escalating to a priority fix. */
const ESCALATION_THRESHOLD = 3;

/** How many recent [ERROR] entries in memory count as "degraded". */
const DEGRADED_ERROR_COUNT = 2;

/** How many recent [ERROR] entries count as "failing". */
const FAILING_ERROR_COUNT = 5;

/** Window for counting "recent" errors (10 min). */
const RECENT_ERRORS_WINDOW_MS = 10 * 60 * 1000;

// ── Singleton class ───────────────────────────────────────────────────────────

class SystemMonitor {
  private _state: MonitorState = {
    status:               "unknown",
    lastCheck:            null,
    lastFailure:          null,
    consecutiveFailures:  0,
    checkCount:           0,
    detail:               "Monitor not yet started.",
  };

  private _intervalId: ReturnType<typeof setInterval>  | null = null;
  private _firstCheckId: ReturnType<typeof setTimeout> | null = null;
  private _subscribers = new Set<Subscriber>();
  private _getToken: (() => Promise<string | null>) | null = null;

  // ── Lifecycle ───────────────────────────────────────────────────────────────

  /**
   * Start the monitor loop.
   * Safe to call multiple times — only the first call takes effect.
   *
   * @param getToken  Async function that returns the current Clerk JWT (or null).
   */
  start(getToken: () => Promise<string | null>): void {
    if (typeof window === "undefined") return;
    if (this._intervalId !== null) return; // already running

    this._getToken = getToken;

    // First tick fires after a short delay so the app can fully settle
    this._firstCheckId = setTimeout(() => void this._tick(), INITIAL_DELAY_MS);
    this._intervalId   = setInterval(() => void this._tick(), MONITOR_INTERVAL_MS);
  }

  /** Stop the loop (call on DashboardShell unmount / sign-out). */
  stop(): void {
    if (this._intervalId  !== null) { clearInterval(this._intervalId);  this._intervalId  = null; }
    if (this._firstCheckId !== null) { clearTimeout(this._firstCheckId); this._firstCheckId = null; }
    this._getToken = null;
    this._mutate({
      status:              "unknown",
      lastCheck:           null,
      lastFailure:         null,
      consecutiveFailures: 0,
      checkCount:          0,
      detail:              "Monitor stopped.",
    });
  }

  // ── Subscription ────────────────────────────────────────────────────────────

  /**
   * Subscribe to state changes.
   * The callback is called immediately with the current state, then on every
   * change.  Returns an unsubscribe function.
   */
  subscribe(cb: Subscriber): () => void {
    this._subscribers.add(cb);
    try { cb({ ...this._state }); } catch { /* never let a subscriber crash the monitor */ }
    return () => this._subscribers.delete(cb);
  }

  /** Read current state synchronously (used to initialise React state). */
  getState(): Readonly<MonitorState> {
    return { ...this._state };
  }

  // ── Internal ─────────────────────────────────────────────────────────────────

  private _mutate(partial: Partial<MonitorState>): void {
    this._state = { ...this._state, ...partial };
    for (const cb of this._subscribers) {
      try { cb({ ...this._state }); } catch { /* ignore */ }
    }
  }

  private async _tick(): Promise<void> {
    if (!this._getToken) return;

    // Skip checks when the tab is hidden — no need to burn resources
    if (typeof document !== "undefined" && document.visibilityState === "hidden") return;

    try {
      const token  = await this._getToken();
      const result = await this._performCheck(token);
      const now    = new Date().toISOString();
      const prev   = this._state.status;

      if (result.status === "healthy") {
        // ── Recovery transition ─────────────────────────────────────────────
        if (prev === "degraded" || prev === "failing") {
          logSystemAction(
            "bug_fix",
            `System recovered (was ${prev})`,
            `OpenAI: ${result.openaiOk ? "✓" : "✗"}  Gemini: ${result.geminiOk ? "✓" : "✗"}  Recent errors: ${result.recentErrors}`,
          );
          writeAutoJournal(); // normal path — threshold still applies
        }
        this._mutate({
          status:              "healthy",
          lastCheck:           now,
          consecutiveFailures: 0,
          checkCount:          this._state.checkCount + 1,
          detail: `OpenAI ${result.openaiOk ? "✓" : "✗"}  Gemini ${result.geminiOk ? "✓" : "✗"}  Errors (10 min): ${result.recentErrors}`,
        });

      } else {
        // ── Degraded / failing ───────────────────────────────────────────────
        const consecutive = this._state.consecutiveFailures + 1;

        this._mutate({
          status:              result.status,
          lastCheck:           now,
          lastFailure:         now,
          consecutiveFailures: consecutive,
          checkCount:          this._state.checkCount + 1,
          detail: `OpenAI ${result.openaiOk ? "✓" : "✗"}  Gemini ${result.geminiOk ? "✓" : "✗"}  Errors (10 min): ${result.recentErrors}`,
        });

        // Log first detection of degradation
        if (consecutive === 1) {
          logSystemAction(
            "error",
            `System ${result.status} (monitor)`,
            `OpenAI: ${result.openaiOk}  Gemini: ${result.geminiOk}  Recent errors: ${result.recentErrors}`,
          );
        }

        // Escalate at threshold — attempt priority fix
        if (consecutive === ESCALATION_THRESHOLD) {
          logSystemAction(
            "error",
            `System monitor: ${consecutive} consecutive failures — escalating`,
            `Status: ${result.status}`,
          );
          void runAutoFix("all_providers_failed", { token }).then((fix) =>
            writeAutoJournal({ priority: true, fixResult: fix }),
          );
        }
      }
    } catch (err) {
      // The health check itself threw — treat as a degraded tick
      const now        = new Date().toISOString();
      const consecutive = this._state.consecutiveFailures + 1;
      const msg        = err instanceof Error ? err.message : "Health check error";
      this._mutate({
        status:              "degraded",
        lastCheck:           now,
        lastFailure:         now,
        consecutiveFailures: consecutive,
        checkCount:          this._state.checkCount + 1,
        detail:              `Check threw: ${msg}`,
      });
    }
  }

  // ── Health check ─────────────────────────────────────────────────────────────

  private async _performCheck(token: string | null): Promise<CheckResult> {
    // ── Provider status ─────────────────────────────────────────────────────
    // Use cached values when fresh (no network) — fetch only when stale.
    let openaiOk = getCachedStatus("openai");
    let geminiOk = getCachedStatus("gemini");

    const staleFetches: Promise<void>[] = [];

    if (openaiOk === null) {
      staleFetches.push(
        this._pingProvider("openai", token).then((ok) => {
          openaiOk = ok;
          setCachedStatus("openai", ok);
        }),
      );
    }
    if (geminiOk === null) {
      staleFetches.push(
        this._pingProvider("gemini", token).then((ok) => {
          geminiOk = ok;
          setCachedStatus("gemini", ok);
        }),
      );
    }
    if (staleFetches.length > 0) await Promise.all(staleFetches);

    const openaiConfigured = openaiOk ?? false;
    const geminiConfigured = geminiOk ?? false;

    // ── Recent error count (pure localStorage read) ──────────────────────────
    const windowCutoff = new Date(Date.now() - RECENT_ERRORS_WINDOW_MS).toISOString();
    let recentErrors = 0;
    try {
      recentErrors = loadMemory().filter(
        (e) =>
          e.source === "system" &&
          e.type   === "note"   &&
          e.createdAt > windowCutoff &&
          e.content.includes("[ERROR]"),
      ).length;
    } catch { /* ignore — memory unavailable */ }

    // ── Status derivation ────────────────────────────────────────────────────
    const bothDown = !openaiConfigured && !geminiConfigured;
    let status: SystemStatus;

    if (bothDown || recentErrors >= FAILING_ERROR_COUNT) {
      status = "failing";
    } else if (!openaiConfigured || !geminiConfigured || recentErrors >= DEGRADED_ERROR_COUNT) {
      status = "degraded";
    } else {
      status = "healthy";
    }

    return { openaiOk: openaiConfigured, geminiOk: geminiConfigured, recentErrors, status };
  }

  private async _pingProvider(provider: "openai" | "gemini", token: string | null): Promise<boolean> {
    try {
      const headers: Record<string, string> = {};
      if (token) headers["Authorization"] = `Bearer ${token}`;
      const res  = await fetch(`${getApiBaseUrl()}/api/v1/${provider}/status`, { headers });
      if (!res.ok) return false;
      const body = await res.json() as { configured: boolean };
      return body.configured;
    } catch {
      return false;
    }
  }
}

// ── Export singleton ──────────────────────────────────────────────────────────

export const systemMonitor = new SystemMonitor();

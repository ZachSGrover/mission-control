/**
 * system-monitor — singleton background health-check loop.
 *
 * Runs every 45 s while the user is signed in.  Most ticks are pure
 * localStorage reads (uses provider-status-cache); network calls only
 * happen when the cache is stale (≤ once per 5 min).
 *
 * ── Classification (per tick) ────────────────────────────────────────
 *
 * Status is derived from TWO independent signals:
 *
 *   1. Provider health    (getCachedStatus / live ping when stale)
 *   2. Weighted error score  (rolling 10-min window from memory store)
 *
 * Error weight by age:
 *   < 2 min   → 3.0  (high   — very recent burst)
 *   2–5 min   → 1.5  (medium — sustained recent activity)
 *   5–10 min  → 0.5  (low    — fading history)
 *   > 10 min  → 0    (excluded)
 *
 * Score thresholds:
 *   score ≥ 6.0  OR  both providers down  → "failing"
 *   score ≥ 1.5  OR  one provider down    → "degraded"
 *   score < 1.5  AND both providers OK    → healthy-candidate
 *
 * ── Recovery gate ────────────────────────────────────────────────────
 *
 * Prevents flip-flopping.  A single clean tick does NOT return status
 * to "healthy".  The system must produce RECOVERY_CLEAN_TICKS=2
 * consecutive healthy-candidate ticks before transitioning.  While
 * stabilizing the status stays "degraded" with a progress indicator.
 *
 * ── Escalation ───────────────────────────────────────────────────────
 *
 * At ESCALATION_THRESHOLD=3 consecutive non-healthy ticks:
 *   → runAutoFix("all_providers_failed") + priority journal
 *
 * ── Mount ─────────────────────────────────────────────────────────────
 *
 *   useEffect(() => {
 *     systemMonitor.start(() => getTokenRef.current());
 *     return () => systemMonitor.stop();
 *   }, [isSignedIn]);
 */

import { getApiBaseUrl } from "@/lib/api-base";
import { loadMemory } from "@/lib/memory-store";
import { logSystemAction, writeAutoJournal } from "@/lib/action-logger";
import { getCachedStatus, setCachedStatus } from "@/lib/provider-status-cache";
import { runAutoFix } from "@/lib/auto-fix";

// ── Types ─────────────────────────────────────────────────────────────────────

export type SystemStatus = "unknown" | "healthy" | "degraded" | "failing";

export interface MonitorState {
  /** Current health status. */
  status: SystemStatus;

  /** ISO timestamp of the last completed health tick. */
  lastCheck: string | null;

  /** ISO timestamp of the most recent non-healthy tick. */
  lastFailure: string | null;

  /** ISO timestamp of the last confirmed recovery (healthy after gate). */
  lastRecoveryTimestamp: string | null;

  /**
   * Consecutive ticks that returned non-healthy.
   * Resets to 0 on any healthy-candidate tick.
   */
  consecutiveFailures: number;

  /**
   * Consecutive healthy-candidate ticks since the last failure.
   * Must reach RECOVERY_CLEAN_TICKS before status flips back to healthy.
   */
  cleanTicksSinceFailure: number;

  /** Total ticks executed since start(). */
  checkCount: number;

  /**
   * Up to MAX_ERROR_TIMESTAMPS recent [ERROR] entry timestamps (newest first).
   * Source: memory store — only hook-logged errors, not monitor's own entries.
   */
  lastErrorTimestamps: readonly string[];

  /**
   * Current weighted error score.
   * Recomputed each tick from lastErrorTimestamps.
   */
  weightedErrorScore: number;

  /** Human-readable detail for tooltip display. */
  detail: string;
}

type Subscriber = (state: Readonly<MonitorState>) => void;

interface CheckResult {
  openaiOk:        boolean;
  geminiOk:        boolean;
  errorTimestamps: string[];
  weightedScore:   number;
  /** Raw classification before the recovery gate is applied. */
  rawStatus:       "healthy" | "degraded" | "failing";
  detail:          string;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const MONITOR_INTERVAL_MS    = 45_000;  // tick every 45 s
const INITIAL_DELAY_MS       = 15_000;  // first tick 15 s after start()
const ESCALATION_THRESHOLD   = 3;       // consecutive failures before priority fix
const RECOVERY_CLEAN_TICKS   = 2;       // consecutive clean ticks needed to confirm recovery
const MAX_ERROR_TIMESTAMPS   = 20;      // cap on stored timestamps
const ERROR_WINDOW_MS        = 10 * 60_000;   // rolling window for error collection

// Weighted score thresholds
const SCORE_FAILING          = 6.0;
const SCORE_DEGRADED         = 1.5;

// ── Weight function ───────────────────────────────────────────────────────────

/**
 * Returns the weight for a single error entry based on how old it is.
 * Older errors have less influence on the current score.
 */
function errorWeight(timestampIso: string): number {
  const ageMs = Date.now() - new Date(timestampIso).getTime();
  if (ageMs < 2 * 60_000)  return 3.0;  // < 2 min  — very recent burst
  if (ageMs < 5 * 60_000)  return 1.5;  // 2–5 min  — sustained activity
  if (ageMs < 10 * 60_000) return 0.5;  // 5–10 min — fading signal
  return 0;                             // > 10 min  — excluded
}

function computeWeightedScore(timestamps: readonly string[]): number {
  return timestamps.reduce((sum, ts) => sum + errorWeight(ts), 0);
}

// ── Classification ────────────────────────────────────────────────────────────

function classify(
  openaiOk: boolean,
  geminiOk: boolean,
  score: number,
): "healthy" | "degraded" | "failing" {
  const bothDown = !openaiOk && !geminiOk;
  const oneDown  = !openaiOk || !geminiOk;
  if (bothDown || score >= SCORE_FAILING)  return "failing";
  if (oneDown  || score >= SCORE_DEGRADED) return "degraded";
  return "healthy";
}

// ── Singleton class ───────────────────────────────────────────────────────────

class SystemMonitor {
  private _state: MonitorState = {
    status:                  "unknown",
    lastCheck:               null,
    lastFailure:             null,
    lastRecoveryTimestamp:   null,
    consecutiveFailures:     0,
    cleanTicksSinceFailure:  0,
    checkCount:              0,
    lastErrorTimestamps:     [],
    weightedErrorScore:      0,
    detail:                  "Monitor not yet started.",
  };

  private _intervalId:   ReturnType<typeof setInterval>  | null = null;
  private _firstCheckId: ReturnType<typeof setTimeout>   | null = null;
  private _subscribers = new Set<Subscriber>();
  private _getToken: (() => Promise<string | null>) | null = null;

  // ── Lifecycle ───────────────────────────────────────────────────────────────

  start(getToken: () => Promise<string | null>): void {
    if (typeof window === "undefined") return;
    if (this._intervalId !== null) return;  // singleton guard

    this._getToken    = getToken;
    this._firstCheckId = setTimeout(() => void this._tick(), INITIAL_DELAY_MS);
    this._intervalId   = setInterval(() => void this._tick(), MONITOR_INTERVAL_MS);
  }

  stop(): void {
    if (this._intervalId   !== null) { clearInterval(this._intervalId);  this._intervalId   = null; }
    if (this._firstCheckId !== null) { clearTimeout(this._firstCheckId); this._firstCheckId = null; }
    this._getToken = null;
    this._mutate({
      status:                  "unknown",
      lastCheck:               null,
      lastFailure:             null,
      consecutiveFailures:     0,
      cleanTicksSinceFailure:  0,
      checkCount:              0,
      lastErrorTimestamps:     [],
      weightedErrorScore:      0,
      detail:                  "Monitor stopped.",
    });
  }

  // ── Subscription ────────────────────────────────────────────────────────────

  subscribe(cb: Subscriber): () => void {
    this._subscribers.add(cb);
    try { cb({ ...this._state }); } catch { /* subscriber errors must not crash the monitor */ }
    return () => this._subscribers.delete(cb);
  }

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
    if (typeof document !== "undefined" && document.visibilityState === "hidden") return;

    const now = new Date().toISOString();

    try {
      const token  = await this._getToken();
      const result = await this._performCheck(token);

      // ── Apply recovery gate ───────────────────────────────────────────────
      if (result.rawStatus === "healthy") {
        await this._handleCleanTick(result, now, token);
      } else {
        this._handleUnhealthyTick(result, now, token);
      }

    } catch (err) {
      // Check itself threw — treat as one degraded tick
      const consecutive = this._state.consecutiveFailures + 1;
      const msg = err instanceof Error ? err.message : "Check error";
      this._mutate({
        status:                  "degraded",
        lastCheck:               now,
        lastFailure:             now,
        consecutiveFailures:     consecutive,
        cleanTicksSinceFailure:  0,
        checkCount:              this._state.checkCount + 1,
        detail:                  `Tick threw: ${msg}`,
      });
    }
  }

  // ── Tick handlers ─────────────────────────────────────────────────────────

  private async _handleCleanTick(
    result: CheckResult,
    now: string,
    token: string | null,
  ): Promise<void> {
    const prevStatus = this._state.status;
    const cleanTicks = this._state.cleanTicksSinceFailure + 1;

    if (prevStatus === "healthy" || prevStatus === "unknown") {
      // Already healthy — stay healthy, reset clean counter
      this._mutate({
        status:                  "healthy",
        lastCheck:               now,
        consecutiveFailures:     0,
        cleanTicksSinceFailure:  cleanTicks,
        checkCount:              this._state.checkCount + 1,
        lastErrorTimestamps:     result.errorTimestamps,
        weightedErrorScore:      result.weightedScore,
        detail:                  result.detail,
      });
      return;
    }

    // Coming from degraded/failing — wait for the gate
    if (cleanTicks < RECOVERY_CLEAN_TICKS) {
      this._mutate({
        status:                  "degraded",   // stay degraded while stabilizing
        lastCheck:               now,
        consecutiveFailures:     0,
        cleanTicksSinceFailure:  cleanTicks,
        checkCount:              this._state.checkCount + 1,
        lastErrorTimestamps:     result.errorTimestamps,
        weightedErrorScore:      result.weightedScore,
        detail:                  `Stabilizing (${cleanTicks}/${RECOVERY_CLEAN_TICKS} clean ticks) — ${result.detail}`,
      });
      return;
    }

    // Gate passed — confirmed recovery
    logSystemAction(
      "bug_fix",
      `System recovered (was ${prevStatus})`,
      `Score: ${result.weightedScore.toFixed(1)}  ${result.detail}`,
    );
    writeAutoJournal();   // normal path — let threshold guard decide

    this._mutate({
      status:                  "healthy",
      lastCheck:               now,
      lastRecoveryTimestamp:   now,
      consecutiveFailures:     0,
      cleanTicksSinceFailure:  cleanTicks,
      checkCount:              this._state.checkCount + 1,
      lastErrorTimestamps:     result.errorTimestamps,
      weightedErrorScore:      result.weightedScore,
      detail:                  result.detail,
    });
  }

  private _handleUnhealthyTick(
    result: CheckResult,
    now: string,
    token: string | null,
  ): void {
    const consecutive = this._state.consecutiveFailures + 1;

    this._mutate({
      status:                  result.rawStatus,
      lastCheck:               now,
      lastFailure:             now,
      consecutiveFailures:     consecutive,
      cleanTicksSinceFailure:  0,    // reset recovery progress
      checkCount:              this._state.checkCount + 1,
      lastErrorTimestamps:     result.errorTimestamps,
      weightedErrorScore:      result.weightedScore,
      detail:                  result.detail,
    });

    // Log first detection
    if (consecutive === 1) {
      logSystemAction(
        "error",
        `System ${result.rawStatus} (monitor)`,
        `Score: ${result.weightedScore.toFixed(1)}  ${result.detail}`,
      );
    }

    // Escalate at threshold
    if (consecutive === ESCALATION_THRESHOLD) {
      logSystemAction(
        "error",
        `Monitor: ${consecutive} consecutive failures — escalating`,
        `Status: ${result.rawStatus}  Score: ${result.weightedScore.toFixed(1)}`,
      );
      void runAutoFix("all_providers_failed", { token }).then((fix) =>
        writeAutoJournal({ priority: true, fixResult: fix }),
      );
    }
  }

  // ── Health check ──────────────────────────────────────────────────────────

  private async _performCheck(token: string | null): Promise<CheckResult> {
    // ── Provider status ───────────────────────────────────────────────────
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

    // ── Rolling error window (pure localStorage read) ─────────────────────
    // Collect error timestamps from hook-logged [ERROR] entries only.
    // Exclude the monitor's own diagnostic logs to avoid feedback loops.
    const windowCutoff = new Date(Date.now() - ERROR_WINDOW_MS).toISOString();
    let errorTimestamps: string[] = [];

    try {
      errorTimestamps = loadMemory()
        .filter(
          (e) =>
            e.source    === "system" &&
            e.type      === "note"   &&
            e.createdAt >  windowCutoff &&
            e.content.includes("[ERROR]") &&
            !e.content.includes(" (monitor)"),  // exclude monitor's own entries
        )
        .map((e) => e.createdAt)
        .slice(0, MAX_ERROR_TIMESTAMPS);
    } catch { /* memory unavailable — proceed with empty window */ }

    // ── Weighted score ────────────────────────────────────────────────────
    const weightedScore = computeWeightedScore(errorTimestamps);

    // ── Classify ──────────────────────────────────────────────────────────
    const rawStatus = classify(openaiConfigured, geminiConfigured, weightedScore);

    // ── Build detail string ───────────────────────────────────────────────
    const recentCount = errorTimestamps.filter(
      (ts) => Date.now() - new Date(ts).getTime() < 2 * 60_000,
    ).length;

    const detail = [
      `OpenAI ${openaiConfigured ? "✓" : "✗"}`,
      `Gemini ${geminiConfigured ? "✓" : "✗"}`,
      `Score: ${weightedScore.toFixed(1)}`,
      errorTimestamps.length > 0
        ? `Errors: ${errorTimestamps.length} (${recentCount} recent)`
        : "Errors: 0",
    ].join("  ");

    return { openaiOk: openaiConfigured, geminiOk: geminiConfigured, errorTimestamps, weightedScore, rawStatus, detail };
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

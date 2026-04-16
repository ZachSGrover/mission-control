/**
 * system-monitor — singleton background health-check loop with alerting.
 *
 * Runs every 45 s while the user is signed in.  Most ticks are pure
 * localStorage reads (uses provider-status-cache); network calls only
 * happen when the cache is stale (≤ once per 5 min).
 *
 * ── Classification (per tick) ────────────────────────────────────────
 *
 *   1. Provider health    (getCachedStatus / live ping when stale)
 *   2. Weighted error score  (rolling 10-min window from memory store)
 *
 *   Error weight by age:
 *     < 2 min   → 3.0  high
 *     2–5 min   → 1.5  medium
 *     5–10 min  → 0.5  low
 *
 *   Score thresholds:
 *     score ≥ 6.0  OR  both down  → "failing"
 *     score ≥ 1.5  OR  one down   → "degraded"
 *     otherwise                   → healthy-candidate
 *
 * ── Recovery gate ────────────────────────────────────────────────────
 *
 *   Requires RECOVERY_CLEAN_TICKS=2 consecutive clean ticks before
 *   flipping back to "healthy".  Prevents flip-flopping.
 *
 * ── Alert system ─────────────────────────────────────────────────────
 *
 *   Three alert types, each with a 2-min cooldown:
 *
 *   "failing"
 *     Trigger: status = "failing"
 *     Action:  invalidate caches + runAutoFix("all_providers_failed")
 *
 *   "degraded_sustained"
 *     Trigger: status has been "degraded" for DEGRADED_ALERT_TICKS=3
 *     Action:  invalidate caches (gentle nudge, no hard reset)
 *
 *   "rising_risk_sustained"
 *     Trigger: risingRisk = true for RISING_ALERT_TICKS=3 consecutive ticks
 *     Action:  log warning (observation only — system not yet unhealthy)
 *
 *   Each alert:
 *     1. logSystemAction("alert", ...)
 *     2. run action handler
 *     3. fire webhook (non-blocking, fails silently)
 *
 * ── Webhook ───────────────────────────────────────────────────────────
 *
 *   Optional. Set via:
 *     systemMonitor.configure({ webhookUrl: "https://..." })
 *   or env var NEXT_PUBLIC_MONITOR_WEBHOOK_URL.
 *
 *   Payload: AlertPayload (see type below).
 *   Never blocks the UI — fire-and-forget with 5 s timeout.
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
import { getCachedStatus, setCachedStatus, invalidateStatus } from "@/lib/provider-status-cache";
import { runAutoFix } from "@/lib/auto-fix";

// ── Types ─────────────────────────────────────────────────────────────────────

export type SystemStatus = "unknown" | "healthy" | "degraded" | "failing";
export type AlertType    = "failing" | "degraded_sustained" | "rising_risk_sustained";

export interface AlertPayload {
  alertType:          AlertType;
  status:             SystemStatus;
  weightedErrorScore: number;
  errorCount:         number;
  openaiOk:           boolean;
  geminiOk:           boolean;
  risingRisk:         boolean;
  consecutiveFailures: number;
  timestamp:          string;
}

export interface MonitorConfig {
  /** POST endpoint that receives AlertPayload as JSON. Omit to disable webhook. */
  webhookUrl?: string;
}

export interface MonitorState {
  status:                  SystemStatus;
  lastCheck:               string | null;
  lastFailure:             string | null;
  lastRecoveryTimestamp:   string | null;
  consecutiveFailures:     number;
  cleanTicksSinceFailure:  number;
  /** Consecutive ticks where status === "degraded" (resets on any non-degraded tick). */
  consecutiveDegraded:     number;
  /** Consecutive ticks where risingRisk === true (resets when risingRisk drops). */
  consecutiveRisingRisk:   number;
  checkCount:              number;
  lastErrorTimestamps:     readonly string[];
  weightedErrorScore:      number;
  risingRisk:              boolean;
  openaiOk:                boolean;
  geminiOk:                boolean;
  detail:                  string;
}

type Subscriber = (state: Readonly<MonitorState>) => void;

interface CheckResult {
  openaiOk:        boolean;
  geminiOk:        boolean;
  errorTimestamps: string[];
  weightedScore:   number;
  rawStatus:       "healthy" | "degraded" | "failing";
  detail:          string;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const MONITOR_INTERVAL_MS    = 45_000;
const INITIAL_DELAY_MS       = 15_000;
const ESCALATION_THRESHOLD   = 3;
const RECOVERY_CLEAN_TICKS   = 2;
const MAX_ERROR_TIMESTAMPS   = 20;
const ERROR_WINDOW_MS        = 10 * 60_000;
const SCORE_FAILING          = 6.0;
const SCORE_DEGRADED         = 1.5;

/** Consecutive degraded ticks before firing "degraded_sustained" alert. */
const DEGRADED_ALERT_TICKS   = 3;

/** Consecutive rising-risk ticks before firing "rising_risk_sustained" alert. */
const RISING_ALERT_TICKS     = 3;

/** Minimum ms between alerts of the same type (2 minutes). */
const ALERT_COOLDOWN_MS      = 2 * 60_000;

/** Webhook POST timeout (ms). Never blocks UI — fire and forget. */
const WEBHOOK_TIMEOUT_MS     = 5_000;

// ── Weight / classify ─────────────────────────────────────────────────────────

function errorWeight(ts: string): number {
  const age = Date.now() - new Date(ts).getTime();
  if (age < 2 * 60_000)  return 3.0;
  if (age < 5 * 60_000)  return 1.5;
  if (age < 10 * 60_000) return 0.5;
  return 0;
}

function computeWeightedScore(timestamps: readonly string[]): number {
  return timestamps.reduce((sum, ts) => sum + errorWeight(ts), 0);
}

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
    consecutiveDegraded:     0,
    consecutiveRisingRisk:   0,
    checkCount:              0,
    lastErrorTimestamps:     [],
    weightedErrorScore:      0,
    risingRisk:              false,
    openaiOk:                false,
    geminiOk:                false,
    detail:                  "Monitor not yet started.",
  };

  private _intervalId:    ReturnType<typeof setInterval>  | null = null;
  private _firstCheckId:  ReturnType<typeof setTimeout>   | null = null;
  private _subscribers  = new Set<Subscriber>();
  private _getToken:      (() => Promise<string | null>) | null = null;
  private _scoreHistory:  number[] = [];
  private _webhookUrl:    string | null = null;

  /**
   * Per-alert-type last-fired timestamp (ms).
   * Enforces ALERT_COOLDOWN_MS between firings of the same type.
   */
  private _alertLastFired: Partial<Record<AlertType, number>> = {};

  // ── Public API ───────────────────────────────────────────────────────────────

  /**
   * Configure optional settings.  Call before or after start() — both work.
   *
   * @example
   *   systemMonitor.configure({ webhookUrl: process.env.NEXT_PUBLIC_MONITOR_WEBHOOK_URL })
   */
  configure(cfg: MonitorConfig): void {
    if (cfg.webhookUrl !== undefined) this._webhookUrl = cfg.webhookUrl || null;
  }

  start(getToken: () => Promise<string | null>): void {
    if (typeof window === "undefined") return;
    if (this._intervalId !== null) return;

    // Pick up webhook URL from env var if not explicitly set via configure()
    if (!this._webhookUrl) {
      const envUrl = process.env.NEXT_PUBLIC_MONITOR_WEBHOOK_URL;
      if (envUrl) this._webhookUrl = envUrl;
    }

    this._getToken     = getToken;
    this._firstCheckId = setTimeout(() => void this._tick(), INITIAL_DELAY_MS);
    this._intervalId   = setInterval(() => void this._tick(), MONITOR_INTERVAL_MS);
  }

  stop(): void {
    if (this._intervalId   !== null) { clearInterval(this._intervalId);  this._intervalId   = null; }
    if (this._firstCheckId !== null) { clearTimeout(this._firstCheckId); this._firstCheckId = null; }
    this._getToken     = null;
    this._scoreHistory = [];
    this._alertLastFired = {};
    this._mutate({
      status:                  "unknown",
      lastCheck:               null,
      lastFailure:             null,
      consecutiveFailures:     0,
      cleanTicksSinceFailure:  0,
      consecutiveDegraded:     0,
      consecutiveRisingRisk:   0,
      checkCount:              0,
      lastErrorTimestamps:     [],
      weightedErrorScore:      0,
      risingRisk:              false,
      openaiOk:                false,
      geminiOk:                false,
      detail:                  "Monitor stopped.",
    });
  }

  subscribe(cb: Subscriber): () => void {
    this._subscribers.add(cb);
    try { cb({ ...this._state }); } catch { /* never let a subscriber crash the loop */ }
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

      // Score history ring buffer (max 3 entries) — O(1)
      this._scoreHistory = [...this._scoreHistory, result.weightedScore].slice(-3);
      const h = this._scoreHistory;
      const risingRisk = h.length === 3 && h[0] < h[1] && h[1] < h[2] && h[2] > 0;

      if (result.rawStatus === "healthy") {
        await this._handleCleanTick(result, now, token, risingRisk);
      } else {
        this._handleUnhealthyTick(result, now, token, risingRisk);
      }

      // Alert evaluation runs AFTER state is mutated (sees latest counters)
      this._evaluateAlerts(token);

    } catch (err) {
      this._scoreHistory = [];
      const consecutive  = this._state.consecutiveFailures + 1;
      const msg          = err instanceof Error ? err.message : "Check error";
      this._mutate({
        status:                  "degraded",
        lastCheck:               now,
        lastFailure:             now,
        consecutiveFailures:     consecutive,
        cleanTicksSinceFailure:  0,
        consecutiveDegraded:     this._state.consecutiveDegraded + 1,
        checkCount:              this._state.checkCount + 1,
        risingRisk:              false,
        consecutiveRisingRisk:   0,
        detail:                  `Tick threw: ${msg}`,
      });
      this._evaluateAlerts(null);
    }
  }

  // ── Tick handlers ─────────────────────────────────────────────────────────

  private async _handleCleanTick(
    result: CheckResult,
    now: string,
    token: string | null,
    risingRisk: boolean,
  ): Promise<void> {
    const prevStatus = this._state.status;
    const cleanTicks = this._state.cleanTicksSinceFailure + 1;

    // Rising-risk counter: increment if still rising, else reset
    const consecutiveRisingRisk = risingRisk
      ? this._state.consecutiveRisingRisk + 1
      : 0;

    const base = {
      lastCheck:              now,
      consecutiveFailures:    0,
      cleanTicksSinceFailure: cleanTicks,
      consecutiveDegraded:    0,         // any clean tick resets degraded streak
      consecutiveRisingRisk,
      checkCount:             this._state.checkCount + 1,
      lastErrorTimestamps:    result.errorTimestamps,
      weightedErrorScore:     result.weightedScore,
      risingRisk,
      openaiOk:               result.openaiOk,
      geminiOk:               result.geminiOk,
      detail:                 result.detail,
    };

    if (prevStatus === "healthy" || prevStatus === "unknown") {
      this._mutate({ status: "healthy", ...base });
      return;
    }

    // Stabilizing — recovery gate not yet passed
    if (cleanTicks < RECOVERY_CLEAN_TICKS) {
      this._mutate({ status: "degraded", ...base });
      return;
    }

    // Gate passed — confirmed recovery
    logSystemAction(
      "bug_fix",
      `System recovered (was ${prevStatus})`,
      `Score: ${result.weightedScore.toFixed(1)}  ${result.detail}`,
    );
    writeAutoJournal();

    this._mutate({ status: "healthy", lastRecoveryTimestamp: now, ...base });
  }

  private _handleUnhealthyTick(
    result: CheckResult,
    now: string,
    token: string | null,
    risingRisk: boolean,
  ): void {
    const consecutive       = this._state.consecutiveFailures + 1;
    const consecutiveDegraded = result.rawStatus === "degraded"
      ? this._state.consecutiveDegraded + 1
      : 0;
    const consecutiveRisingRisk = risingRisk
      ? this._state.consecutiveRisingRisk + 1
      : 0;

    this._mutate({
      status:                  result.rawStatus,
      lastCheck:               now,
      lastFailure:             now,
      consecutiveFailures:     consecutive,
      cleanTicksSinceFailure:  0,
      consecutiveDegraded,
      consecutiveRisingRisk,
      checkCount:              this._state.checkCount + 1,
      lastErrorTimestamps:     result.errorTimestamps,
      weightedErrorScore:      result.weightedScore,
      risingRisk,
      openaiOk:                result.openaiOk,
      geminiOk:                result.geminiOk,
      detail:                  result.detail,
    });

    // Log first detection only (subsequent ticks are covered by alerts)
    if (consecutive === 1) {
      logSystemAction(
        "error",
        `System ${result.rawStatus} (monitor)`,
        `Score: ${result.weightedScore.toFixed(1)}  ${result.detail}`,
      );
    }

    // Escalate at escalation threshold — this is separate from the alert system
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

  // ── Alert evaluation ──────────────────────────────────────────────────────

  /**
   * Called after every tick (after state mutation).
   * Checks all three alert conditions and fires when triggered + not cooling down.
   * O(1) — three simple integer comparisons.
   */
  private _evaluateAlerts(token: string | null): void {
    const s = this._state;

    // ── "failing" alert ───────────────────────────────────────────────────
    if (s.status === "failing") {
      this._maybeFireAlert("failing", token, {
        description: "System status: FAILING",
        detail:      `Score: ${s.weightedErrorScore.toFixed(1)}  OpenAI: ${s.openaiOk}  Gemini: ${s.geminiOk}`,
        action: async (tk) => {
          // Invalidate both provider caches + attempt auto-fix
          invalidateStatus("openai");
          invalidateStatus("gemini");
          const fix = await runAutoFix("all_providers_failed", { token: tk });
          writeAutoJournal({ priority: true, fixResult: fix });
        },
      });
    }

    // ── "degraded_sustained" alert ────────────────────────────────────────
    if (s.consecutiveDegraded >= DEGRADED_ALERT_TICKS) {
      this._maybeFireAlert("degraded_sustained", token, {
        description: `System degraded for ${s.consecutiveDegraded} consecutive ticks`,
        detail:      `Score: ${s.weightedErrorScore.toFixed(1)}  OpenAI: ${s.openaiOk}  Gemini: ${s.geminiOk}`,
        action: async () => {
          // Gentle nudge — invalidate caches so hooks re-check on next render
          invalidateStatus("openai");
          invalidateStatus("gemini");
          logSystemAction("config", "Monitor invalidated provider caches (degraded_sustained)", "auto-action");
        },
      });
    }

    // ── "rising_risk_sustained" alert ─────────────────────────────────────
    if (s.consecutiveRisingRisk >= RISING_ALERT_TICKS) {
      this._maybeFireAlert("rising_risk_sustained", token, {
        description: `Rising risk sustained for ${s.consecutiveRisingRisk} ticks`,
        detail:      `Score trajectory rising: ${s.weightedErrorScore.toFixed(1)}`,
        action: async () => {
          // Observation-only — log the warning; system not yet unhealthy
          logSystemAction("alert", "Rising error trend — monitor advises attention", `Score: ${s.weightedErrorScore.toFixed(1)}`);
        },
      });
    }
  }

  /**
   * Fire an alert if the per-type cooldown has elapsed.
   *
   * Flow:
   *   1. Check cooldown — skip if < ALERT_COOLDOWN_MS since last fire
   *   2. Record fire timestamp
   *   3. logSystemAction("alert", ...)
   *   4. Run action handler (non-blocking, errors caught)
   *   5. Send webhook (fire-and-forget, never throws)
   */
  private _maybeFireAlert(
    type: AlertType,
    token: string | null,
    opts: {
      description: string;
      detail:      string;
      action:      (token: string | null) => Promise<void>;
    },
  ): void {
    const now      = Date.now();
    const lastFire = this._alertLastFired[type] ?? 0;
    if (now - lastFire < ALERT_COOLDOWN_MS) return;  // still cooling down

    // Record immediately to prevent re-entry during async action
    this._alertLastFired[type] = now;

    logSystemAction("alert", opts.description, opts.detail);

    // Run action handler (non-blocking)
    void opts.action(token).catch((err) => {
      const msg = err instanceof Error ? err.message : "Alert action error";
      logSystemAction("error", `Alert action failed for "${type}"`, msg);
    });

    // Send webhook (fire-and-forget)
    this._sendWebhook(type);
  }

  // ── Webhook ───────────────────────────────────────────────────────────────

  private _sendWebhook(alertType: AlertType): void {
    const url = this._webhookUrl;
    if (!url || typeof window === "undefined") return;

    const s = this._state;
    const payload: AlertPayload = {
      alertType,
      status:             s.status,
      weightedErrorScore: s.weightedErrorScore,
      errorCount:         s.lastErrorTimestamps.length,
      openaiOk:           s.openaiOk,
      geminiOk:           s.geminiOk,
      risingRisk:         s.risingRisk,
      consecutiveFailures: s.consecutiveFailures,
      timestamp:          new Date().toISOString(),
    };

    // AbortController gives the request a hard 5 s deadline
    const controller = new AbortController();
    const timeoutId  = setTimeout(() => controller.abort(), WEBHOOK_TIMEOUT_MS);

    fetch(url, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(payload),
      signal:  controller.signal,
    })
      .then(() => clearTimeout(timeoutId))
      .catch(() => clearTimeout(timeoutId));
    // All errors intentionally swallowed — webhook must never affect UI
  }

  // ── Health check ─────────────────────────────────────────────────────────

  private async _performCheck(token: string | null): Promise<CheckResult> {
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

    // Rolling error window — prune to 10 min, cap at 20, exclude monitor entries
    const now10m = new Date(Date.now() - ERROR_WINDOW_MS).toISOString();
    let errorTimestamps: string[] = [];
    try {
      errorTimestamps = loadMemory()
        .filter(
          (e) =>
            e.source    === "system" &&
            e.type      === "note"   &&
            e.createdAt >  now10m   &&
            e.content.includes("[ERROR]") &&
            !e.content.includes(" (monitor)"),
        )
        .map((e) => e.createdAt)
        .slice(0, MAX_ERROR_TIMESTAMPS);
    } catch { /* memory unavailable */ }

    const weightedScore = computeWeightedScore(errorTimestamps);
    const rawStatus     = classify(openaiConfigured, geminiConfigured, weightedScore);

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

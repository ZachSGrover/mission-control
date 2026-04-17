/**
 * auto-fix — attempt lightweight recovery actions before journaling a priority event.
 *
 * runAutoFix(eventType, ctx?) is called by priority event handlers immediately
 * after logging the event and BEFORE calling writeAutoJournal(). The returned
 * FixResult is passed into writeAutoJournal({ fixResult }) so the journal
 * records what was attempted and whether it worked.
 *
 * Fix handlers must be:
 *   - Fast (< 3s total) — they run in the request path
 *   - Non-throwing — always return a FixResult, never throw
 *   - Non-destructive — don't clear user data, don't hard-reload the page
 *
 * Handler map:
 *   all_providers_failed  → invalidate caches, re-ping OpenAI + Gemini
 *   app_render_crash      → clear corrupted transient localStorage state
 *   provider_recovery     → one stability ping to confirm connection held
 *   deploy_completed      → backend health check
 *   system_paused         → write mc_intervention_required flag
 */

import { getApiBaseUrl } from "@/lib/api-base";
import { logSystemAction, type FixResult } from "@/lib/action-logger";
import { setCachedStatus, invalidateStatus } from "@/lib/provider-status-cache";

// ── Types ─────────────────────────────────────────────────────────────────────

export type FixEventType =
  | "all_providers_failed"
  | "app_render_crash"
  | "provider_recovery"
  | "deploy_completed"
  | "system_paused";

export interface AutoFixContext {
  /** Clerk JWT for authenticated backend calls. Optional — fixes degrade gracefully without it. */
  token?: string | null;
  /** Which provider recovered (used by provider_recovery handler). */
  provider?: "openai" | "gemini";
  /** Human-readable reason (used by system_paused handler). */
  reason?: string;
}

// ── Router ────────────────────────────────────────────────────────────────────

/**
 * Run the fix handler for a priority event.
 * Always returns a FixResult — never throws.
 */
export async function runAutoFix(
  eventType: FixEventType,
  ctx?: AutoFixContext,
): Promise<FixResult> {
  try {
    switch (eventType) {
      case "all_providers_failed":
        return await fixAllProvidersFailed(ctx?.token ?? null);
      case "app_render_crash":
        return fixAppRenderCrash();
      case "provider_recovery":
        return await fixProviderRecovery(ctx?.provider ?? "openai", ctx?.token ?? null);
      case "deploy_completed":
        return await fixDeployCompleted(ctx?.token ?? null);
      case "system_paused":
        return fixSystemPaused(ctx?.reason);
      default:
        return {
          attempted: `No handler for event "${eventType as string}"`,
          success: false,
          partial: false,
          detail: "Unrecognised event type — journal written without fix.",
        };
    }
  } catch (err) {
    // A fix handler should never throw, but catch the unexpected case
    const msg = err instanceof Error ? err.message : "Unexpected error in fix handler";
    return {
      attempted: `Fix handler for "${eventType}"`,
      success: false,
      partial: false,
      detail: `Handler threw unexpectedly: ${msg}`,
    };
  }
}

// ── Fix handlers ──────────────────────────────────────────────────────────────

/**
 * all_providers_failed
 *
 * 1. Invalidate cached statuses so the next hook render forces a fresh check.
 * 2. Re-ping both provider status endpoints once.
 * 3. Update caches with the fresh results.
 * 4. Report which providers recovered (if any).
 */
async function fixAllProvidersFailed(token: string | null): Promise<FixResult> {
  const attempted = "Re-checked OpenAI and Gemini status, refreshed provider cache";

  // Blow away stale "false" cache entries so the hooks re-check on next render
  invalidateStatus("openai");
  invalidateStatus("gemini");

  if (typeof window === "undefined") {
    return { attempted, success: false, partial: false, detail: "Running server-side — skipped network checks" };
  }

  const baseUrl = getApiBaseUrl();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  // null = not configured (no API key set — not a failure); false = configured but unreachable
  const pingProvider = async (provider: "openai" | "gemini"): Promise<boolean | null> => {
    try {
      const r = await fetch(`${baseUrl}/api/v1/${provider}/status`, { headers });
      if (!r.ok) return false;
      const body = await r.json() as { configured: boolean };
      return body.configured ? true : null;
    } catch {
      return false;
    }
  };

  const [openaiOk, geminiOk] = await Promise.all([
    pingProvider("openai"),
    pingProvider("gemini"),
  ]);

  // Only cache boolean results — null (not configured) will be re-fetched next tick
  if (openaiOk !== null) setCachedStatus("openai", openaiOk);
  if (geminiOk !== null) setCachedStatus("gemini", geminiOk);

  const configured = [openaiOk, geminiOk].filter((v): v is boolean => v !== null);
  const anyConfigured = configured.length > 0;
  const anyRecovered  = configured.some((v) => v === true);

  if (!anyConfigured) {
    return {
      attempted,
      success: true,
      partial: false,
      detail: "No providers configured — add API keys in Settings to enable AI providers.",
    };
  }

  if (anyRecovered) {
    const recovered = [openaiOk === true && "OpenAI", geminiOk === true && "Gemini"].filter(Boolean).join(", ");
    const stillDown  = [openaiOk === false && "OpenAI", geminiOk === false && "Gemini"].filter(Boolean).join(", ");
    logSystemAction("bug_fix", `Provider(s) back online after all-fail: ${recovered}`, "auto-fix");
    return {
      attempted,
      success: configured.every((v) => v === true),
      partial: anyRecovered && configured.some((v) => v === false),
      detail: `Recovered: ${recovered}.${stillDown ? ` Still down: ${stillDown}.` : ""}`.trim(),
    };
  }

  return {
    attempted,
    success: false,
    partial: false,
    detail: "Configured providers still unreachable — check API keys in Settings.",
  };
}

/**
 * app_render_crash
 *
 * Clears transient state most likely to cause or perpetuate a render crash:
 *   - Orchestrator history (complex nested streaming state)
 *   - Provider status cache (force fresh status checks on reload)
 *
 * Does NOT clear: memory store, chat history, settings — those are user data.
 */
function fixAppRenderCrash(): FixResult {
  const attempted = "Cleared transient state that may have caused the crash";
  const cleared: string[] = [];

  if (typeof window === "undefined") {
    return { attempted, success: false, partial: false, detail: "Running server-side — skipped" };
  }

  // Orchestrator history: complex nested objects with streaming state,
  // most likely to contain partially-written or corrupted JSON after a crash
  try {
    localStorage.removeItem("mc_orchestrator_v1");
    cleared.push("orchestrator history");
  } catch { /* ignore */ }

  // Provider status cache (module-level): force fresh status checks on reload
  try {
    invalidateStatus("openai");
    invalidateStatus("gemini");
    cleared.push("provider status cache");
  } catch { /* ignore */ }

  if (cleared.length > 0) {
    logSystemAction("bug_fix", "Cleared crash-related state", cleared.join(", "));
    return {
      attempted,
      success: true,
      partial: false,
      detail: `Cleared: ${cleared.join(", ")}. Reload the page to fully recover.`,
    };
  }

  return {
    attempted,
    success: false,
    partial: false,
    detail: "Nothing could be cleared — manual reload required.",
  };
}

/**
 * provider_recovery
 *
 * Runs one stability ping after a provider status transitions false → true.
 * If the second check also passes, the recovery is confirmed stable.
 * If it fails, the first result may have been a fluke and we note instability.
 */
async function fixProviderRecovery(
  provider: "openai" | "gemini",
  token: string | null,
): Promise<FixResult> {
  const attempted = `Verified ${provider} connection stability (confirmation ping)`;

  if (typeof window === "undefined") {
    return { attempted, success: false, partial: false, detail: "Running server-side — skipped" };
  }

  const baseUrl = getApiBaseUrl();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  try {
    const res = await fetch(`${baseUrl}/api/v1/${provider}/status`, { headers });
    const body = res.ok ? (await res.json() as { configured: boolean }) : null;
    const stable = res.ok && (body?.configured ?? false);

    // Re-confirm cache with the fresh result
    if (stable) setCachedStatus(provider, true);
    else invalidateStatus(provider); // unstable — let next render re-check

    if (stable) {
      return {
        attempted,
        success: true,
        partial: false,
        detail: `${provider} confirmed stable. Cache refreshed.`,
      };
    }

    logSystemAction("error", `${provider} recovery unstable — second check failed`, "auto-fix");
    return {
      attempted,
      success: false,
      partial: true,
      detail: `${provider} first check passed but second check failed — connection may be flaky.`,
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Network error";
    return {
      attempted,
      success: false,
      partial: false,
      detail: `Stability ping threw: ${msg}`,
    };
  }
}

/**
 * deploy_completed
 *
 * Pings the backend health-check endpoint to confirm the new deploy is alive.
 * Falls back to the API-keys status endpoint if health-check isn't available.
 */
async function fixDeployCompleted(token: string | null): Promise<FixResult> {
  const attempted = "Post-deploy health check";

  if (typeof window === "undefined") {
    return { attempted, success: false, partial: false, detail: "Running server-side — skipped" };
  }

  const baseUrl = getApiBaseUrl();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  try {
    // Try the dedicated health-check endpoint first
    const res = await fetch(`${baseUrl}/api/v1/workflows/health`, { headers });

    if (res.ok) {
      const body = await res.json() as { status?: string; healthy?: boolean };
      const healthy = body.healthy ?? body.status === "healthy";
      return {
        attempted,
        success: healthy,
        partial: !healthy,
        detail: healthy
          ? "Backend healthy after deploy."
          : `Health check returned degraded state: ${JSON.stringify(body)}`,
      };
    }

    // Health endpoint not available — use settings endpoint as proxy
    const fallback = await fetch(`${baseUrl}/api/v1/settings/api-keys`, { headers });
    if (fallback.ok) {
      return {
        attempted,
        success: true,
        partial: false,
        detail: "Backend responding normally (settings endpoint reachable).",
      };
    }

    return {
      attempted,
      success: false,
      partial: false,
      detail: `Backend not yet responding — health check HTTP ${fallback.status}. May still be starting up.`,
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Network error";
    return {
      attempted,
      success: false,
      partial: false,
      detail: `Health check failed: ${msg}`,
    };
  }
}

/**
 * system_paused
 *
 * Writes an `mc_intervention_required` flag to localStorage.
 * Any part of the UI can read this flag to surface a manual-action banner.
 */
function fixSystemPaused(reason?: string): FixResult {
  const attempted = "Marked system for manual intervention";

  if (typeof window === "undefined") {
    return { attempted, success: false, partial: false, detail: "Running server-side — skipped" };
  }

  try {
    const payload = JSON.stringify({
      at: new Date().toISOString(),
      reason: reason ?? "master controller flagged manual_intervention_required",
    });
    localStorage.setItem("mc_intervention_required", payload);

    return {
      attempted,
      success: true,
      partial: false,
      detail: `Intervention flag set. Reason: ${reason ?? "unspecified"}. Read mc_intervention_required from localStorage to surface in UI.`,
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : "localStorage write failed";
    return { attempted, success: false, partial: false, detail: msg };
  }
}

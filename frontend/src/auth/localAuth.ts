"use client";

import { AuthMode } from "@/auth/mode";

let localToken: string | null = null;
const STORAGE_KEY = "mc_local_auth_token";

export function isLocalAuthMode(): boolean {
  return process.env.NEXT_PUBLIC_AUTH_MODE === AuthMode.Local;
}

export function setLocalAuthToken(token: string): void {
  localToken = token;
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(STORAGE_KEY, token);
  } catch {
    // Ignore storage failures (private mode / policy).
  }
}

export function getLocalAuthToken(): string | null {
  if (localToken) return localToken;
  if (typeof window !== "undefined") {
    try {
      const stored = window.sessionStorage.getItem(STORAGE_KEY);
      if (stored) {
        localToken = stored;
        return stored;
      }
    } catch {
      // Ignore storage failures (private mode / policy).
    }
  }
  // Fall back to the token baked in at build time — eliminates manual login
  // for personal local deployments.
  //
  // Sprint 3 hardening: refuse this fallback in production builds.
  // Sprint 4 strengthening: also refuse in any Clerk auth mode (because
  // the local-token fallback should only ever apply when AUTH_MODE=local)
  // and refuse if the build is running on a hostname that looks like prod.
  // ``NEXT_PUBLIC_*`` variables are inlined into the client bundle, so any
  // value here is effectively shipped to every visitor.
  const envToken = process.env.NEXT_PUBLIC_LOCAL_AUTH_TOKEN;
  if (!envToken || envToken.length < 50) return null;

  if (!isLocalAuthFallbackAllowed()) {
    // Loud, non-fatal warning — the app keeps working, just without
    // the build-time fallback. Operators see the message in the
    // browser console; production should never reach this branch.
    // eslint-disable-next-line no-console
    console.warn(
      "[security] NEXT_PUBLIC_LOCAL_AUTH_TOKEN is set but the build looks " +
        "like production or non-local-auth. Ignoring it; this fallback is " +
        "dev-only and must never reach a real visitor.",
    );
    return null;
  }

  localToken = envToken;
  return envToken;
}

/**
 * Returns true iff the build-time ``NEXT_PUBLIC_LOCAL_AUTH_TOKEN``
 * fallback is allowed to be used.
 *
 * Allow only when **all** of the following hold:
 * - ``NODE_ENV`` is not ``production``.
 * - The configured auth mode is ``local`` (this token is meaningless in
 *   Clerk mode and shouldn't be relied on).
 * - The runtime hostname (when available) is a developer-typical loopback
 *   or LAN address. This is a defence-in-depth check; the token would be
 *   useless to a server-side leak path, but a paranoid extra check costs
 *   us nothing.
 */
function isLocalAuthFallbackAllowed(): boolean {
  if (process.env.NODE_ENV === "production") return false;
  if (!isLocalAuthMode()) return false;

  // Hostname check is best-effort — it only runs in the browser. SSR
  // path returns true and the per-render warning still triggers if the
  // server-rendered page is later hydrated on a real hostname.
  if (typeof window !== "undefined") {
    const host = window.location?.hostname ?? "";
    const isLocalHost =
      host === "localhost" ||
      host === "127.0.0.1" ||
      host === "::1" ||
      host.endsWith(".local") ||
      // Common LAN / docker / dev hostnames.
      host.startsWith("192.168.") ||
      host.startsWith("10.") ||
      host.startsWith("172.");
    if (!isLocalHost) return false;
  }
  return true;
}

export function clearLocalAuthToken(): void {
  localToken = null;
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Ignore storage failures (private mode / policy).
  }
}

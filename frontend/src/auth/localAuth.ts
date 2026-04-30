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
  // ``NEXT_PUBLIC_*`` variables are inlined into the client bundle, so
  // any value here is effectively shipped to every visitor. The local
  // auth dev convenience must not become a production back door.
  const envToken = process.env.NEXT_PUBLIC_LOCAL_AUTH_TOKEN;
  const isProduction = process.env.NODE_ENV === "production";
  if (envToken && envToken.length >= 50) {
    if (isProduction) {
      // Loud, non-fatal warning — the app keeps working, just without
      // the build-time fallback. Operators see the message in the
      // browser console; production should never reach this branch.
      // eslint-disable-next-line no-console
      console.warn(
        "[security] NEXT_PUBLIC_LOCAL_AUTH_TOKEN is set in a production build. " +
          "Ignoring it; this fallback is dev-only.",
      );
      return null;
    }
    localToken = envToken;
    return envToken;
  }
  return null;
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

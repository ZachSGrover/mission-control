"use client";

// Browser-only store for the OpenClaw gateway operator token.
//
// The deployed app (app.digidle.com) doesn't ship a token in its bundle —
// the user pastes it into Settings once and it lives in localStorage scoped
// to this origin. The OpenClaw singleton reads this at WS-connect time and
// falls back to NEXT_PUBLIC_OPENCLAW_TOKEN (the local-dev path via .env.local)
// when nothing is stored.
//
// localStorage is readable by any JS on the page — fine for a single-user,
// Clerk-gated tool, but never log the token, never echo it in error messages.

const STORAGE_KEY = "mc_openclaw_token";

export function loadGatewayToken(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function saveGatewayToken(value: string): void {
  if (typeof window === "undefined") return;
  try {
    const trimmed = value.trim();
    if (trimmed) {
      window.localStorage.setItem(STORAGE_KEY, trimmed);
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // localStorage may be disabled / quota exceeded — fail silently rather
    // than crashing Settings. The user will see no preview and can retry.
  }
}

export function clearGatewayToken(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}

/**
 * Display-only masking. Keeps the last 4 characters so the user can confirm
 * which token is stored without exposing the rest.
 */
export function maskGatewayToken(value: string): string {
  if (!value) return "";
  if (value.length <= 4) return "••••";
  return `•••• •••• ${value.slice(-4)}`;
}

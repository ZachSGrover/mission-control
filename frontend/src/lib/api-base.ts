/**
 * Returns the base URL for all backend API calls.
 *
 * Priority:
 *   1. NEXT_PUBLIC_API_URL env var (set in Render / .env.local).
 *      Example: https://mission-control-jbx8.onrender.com
 *   2. Known production host mapping — covers deployed frontend hosts even
 *      when NEXT_PUBLIC_API_URL was not set at build time.
 *   3. Auto-resolve: same hostname as the browser, port 8000.
 *      Works for local dev (http://localhost:8000).
 */

/** Known frontend host → backend URL. Update if service URLs change. */
const KNOWN_PRODUCTION_HOSTS: Record<string, string> = {
  "hq.digidle.com":                              "https://mission-control-jbx8.onrender.com",
  "app.digidle.com":                             "https://mission-control-jbx8.onrender.com",
  "mission-control-frontend-iyoj.onrender.com":  "https://mission-control-jbx8.onrender.com",
};

export function getApiBaseUrl(): string {
  const raw = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (raw && raw.toLowerCase() !== "auto") {
    const normalized = raw.replace(/\/+$/, "");
    if (!normalized) {
      throw new Error("NEXT_PUBLIC_API_URL is invalid (empty after trimming).");
    }
    return normalized;
  }

  if (typeof window !== "undefined") {
    const host = window.location.hostname;

    // Known production host → hardcoded backend URL (no env var needed)
    if (host && KNOWN_PRODUCTION_HOSTS[host]) {
      return KNOWN_PRODUCTION_HOSTS[host];
    }

    const protocol = window.location.protocol === "https:" ? "https" : "http";
    if (host) {
      // Local dev: auto-resolve to same host on port 8000
      if (host === "localhost" || host === "127.0.0.1") {
        return `${protocol}://${host}:8000`;
      }
      // Unknown production host — warn and fall through to error
      console.warn(
        `[api-base] NEXT_PUBLIC_API_URL is not set and "${host}" is not in KNOWN_PRODUCTION_HOSTS. ` +
        `Add this host to api-base.ts or set NEXT_PUBLIC_API_URL in Render environment variables.`,
      );
    }
  }

  throw new Error(
    "NEXT_PUBLIC_API_URL is not set and cannot be auto-resolved. " +
    "Set NEXT_PUBLIC_API_URL in Render environment variables, or add your host to KNOWN_PRODUCTION_HOSTS in api-base.ts.",
  );
}

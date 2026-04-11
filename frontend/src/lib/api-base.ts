/**
 * Returns the base URL for all backend API calls.
 *
 * Priority:
 *   1. NEXT_PUBLIC_API_URL env var — set this in Vercel / .env.local.
 *      Example: https://your-backend.onrender.com
 *   2. Auto-resolve: same hostname as the browser, port 8000.
 *      Works for local dev (http://localhost:8000).
 *      Will NOT work on app.digidle.com unless the backend runs there.
 *
 * IMPORTANT for production (Vercel / app.digidle.com):
 *   You MUST set NEXT_PUBLIC_API_URL in your Vercel project settings:
 *   Vercel Dashboard → Project → Settings → Environment Variables
 *   Key:   NEXT_PUBLIC_API_URL
 *   Value: https://your-backend-domain.com   ← wherever FastAPI is deployed
 */
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
    const protocol = window.location.protocol === "https:" ? "https" : "http";
    const host = window.location.hostname;
    if (host) {
      const url = `${protocol}://${host}:8000`;
      // Warn in production: auto-resolve only works if the backend is on the
      // same domain as the frontend (unusual for Vercel deployments).
      if (protocol === "https" && host !== "localhost") {
        console.warn(
          `[api-base] NEXT_PUBLIC_API_URL is not set. ` +
          `Auto-resolving to ${url} — this will fail unless the backend ` +
          `is reachable at that address. ` +
          `Set NEXT_PUBLIC_API_URL in Vercel environment variables.`,
        );
      }
      return url;
    }
  }

  throw new Error(
    "NEXT_PUBLIC_API_URL is not set and cannot be auto-resolved outside the browser. " +
    "Set NEXT_PUBLIC_API_URL in your environment (Vercel project settings).",
  );
}

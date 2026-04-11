"use client";

/**
 * useAuthFetch — unified authenticated fetch for both local and Clerk auth modes.
 *
 * Returns a stable `fetchWithAuth(url, options)` function that automatically
 * injects the correct `Authorization: Bearer <token>` header.
 *
 * - Local mode  : token comes from sessionStorage via getLocalAuthToken()
 * - Clerk mode  : token is a short-lived Clerk session JWT from getToken()
 *
 * The returned `fetchWithAuth` reference is intentionally stable (never
 * changes identity) so it is safe to pass as a useEffect dependency.
 */

import { useCallback, useRef } from "react";

import { useAuth } from "@/auth/clerk";
import { getApiBaseUrl } from "@/lib/api-base";

export function useAuthFetch() {
  const { getToken } = useAuth();
  const apiBase = getApiBaseUrl();

  // Keep a ref to the latest getToken so fetchWithAuth never needs to
  // re-create itself (avoids spurious useEffect re-runs in consumers).
  const getTokenRef = useRef(getToken);
  getTokenRef.current = getToken;

  const fetchWithAuth = useCallback(
    async (url: string, options: RequestInit = {}): Promise<Response> => {
      const token = await getTokenRef.current();
      const existing = (options.headers ?? {}) as Record<string, string>;
      const headers: Record<string, string> = { ...existing };
      if (token) headers["Authorization"] = `Bearer ${token}`;
      return fetch(url, { ...options, headers });
    },
    [], // stable — reads token via ref on every call
  );

  return { fetchWithAuth, apiBase };
}

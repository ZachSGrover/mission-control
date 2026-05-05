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
  // The ref is intentionally written during render: every call must read the
  // freshest getToken without breaking fetchWithAuth's stable identity.
  const getTokenRef = useRef(getToken);
  // eslint-disable-next-line react-hooks/refs
  getTokenRef.current = getToken;

  const fetchWithAuth: typeof fetch = useCallback(
    async (input: URL | RequestInfo, init?: RequestInit): Promise<Response> => {
      const token = await getTokenRef.current();
      const headers = new Headers(init?.headers);
      if (token) headers.set("Authorization", `Bearer ${token}`);
      return fetch(input, { ...init, headers });
    },
    [], // stable — reads token via ref on every call
  );

  return { fetchWithAuth, apiBase };
}

"use client";

import { useEffect, useState } from "react";

import { useAuthFetch } from "@/hooks/use-auth-fetch";
import type { MCRole } from "@/lib/roles";

type RoleState = {
  role: MCRole | null;
  disabled: boolean;
  loading: boolean;
  error: string | null;
};

/**
 * Fetches and caches the current user's Mission Control role.
 *
 * Returns `null` while loading.  On error, defaults to `"viewer"` so the UI
 * degrades gracefully rather than exposing privileged sections.
 */
export function useRole(): RoleState {
  const [state, setState] = useState<RoleState>({
    role: null,
    disabled: false,
    loading: true,
    error: null,
  });

  const { fetchWithAuth, apiBase } = useAuthFetch();

  useEffect(() => {
    let cancelled = false;

    async function fetchRole() {
      try {
        const res = await fetchWithAuth(`${apiBase}/api/v1/roles/me`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as { role: MCRole; disabled: boolean };
        if (!cancelled) {
          setState({ role: data.role, disabled: data.disabled, loading: false, error: null });
        }
      } catch (err) {
        if (!cancelled) {
          setState({
            role: "viewer",
            disabled: false,
            loading: false,
            error: err instanceof Error ? err.message : "Failed to load role.",
          });
        }
      }
    }

    void fetchRole();
    return () => { cancelled = true; };
  }, [fetchWithAuth, apiBase]);

  return state;
}

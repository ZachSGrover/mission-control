"use client";

import { useEffect, useState } from "react";

import { useAuthFetch } from "@/hooks/use-auth-fetch";
import type { MCRole } from "@/lib/roles";
import { getRolePreview, subscribeRolePreview } from "@/lib/role-preview";

type RoleState = {
  /** Effective role used by the UI.  Equals ``realRole`` unless preview is on. */
  role: MCRole | null;
  /** Real role from the backend.  Use this for owner-only client-side checks. */
  realRole: MCRole | null;
  /** True iff ``role`` differs from ``realRole`` because of preview mode. */
  previewing: boolean;
  disabled: boolean;
  loading: boolean;
  error: string | null;
};

/**
 * Fetches the user's Mission Control role from the backend, then
 * layers the owner-only frontend role-preview on top so the owner can
 * see the UI as another role would.  Backend permissions are always
 * decided by the server using the real role, so preview mode never
 * grants real privileges.
 *
 * Returns `null` while loading.  On error, defaults to `"viewer"` so
 * the UI degrades gracefully rather than exposing privileged sections.
 */
export function useRole(): RoleState {
  const [realRole, setRealRole] = useState<MCRole | null>(null);
  const [disabled, setDisabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<MCRole | null>(() => getRolePreview());

  const { fetchWithAuth, apiBase } = useAuthFetch();

  useEffect(() => {
    let cancelled = false;

    async function fetchRole() {
      try {
        const res = await fetchWithAuth(`${apiBase}/api/v1/roles/me`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as { role: MCRole; disabled: boolean };
        if (!cancelled) {
          setRealRole(data.role);
          setDisabled(data.disabled);
          setLoading(false);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setRealRole("viewer");
          setDisabled(false);
          setLoading(false);
          setError(err instanceof Error ? err.message : "Failed to load role.");
        }
      }
    }

    void fetchRole();
    return () => {
      cancelled = true;
    };
  }, [fetchWithAuth, apiBase]);

  // Keep the local preview in sync with localStorage (writes from
  // RolePreviewControl, or from another tab).
  useEffect(() => {
    return subscribeRolePreview(() => {
      setPreview(getRolePreview());
    });
  }, []);

  // Preview is owner-only — anything else falls back to the real role.
  const previewActive = realRole === "owner" && preview !== null && preview !== "owner";
  const role: MCRole | null = previewActive ? preview : realRole;

  return {
    role,
    realRole,
    previewing: previewActive,
    disabled,
    loading,
    error,
  };
}

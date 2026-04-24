"use client";

import { useCallback, useState } from "react";

import { useAuthFetch } from "@/hooks/use-auth-fetch";

// ── Types ────────────────────────────────────────────────────────────────────

export interface ChangedFile {
  path: string;
  status: string;
}

export interface SuspiciousFile {
  path: string;
  reason: string;
}

export interface GitPreview {
  branch: string;
  remote: string;
  willPushBranch: string;
  changedFiles: ChangedFile[];
  statusSummary: string;
  diffStat: string;
  commitMessage: string;
  hasChanges: boolean;
  suspiciousFiles: SuspiciousFile[];
  error?: string;
}

export type PreviewStatus = "idle" | "loading" | "ready" | "error";

export interface PreviewState {
  status: PreviewStatus;
  preview: GitPreview | null;
  error: string;
  load: () => Promise<void>;
  reset: () => void;
}

// ── Hook ─────────────────────────────────────────────────────────────────────

export function useGitPreview(): PreviewState {
  const [status, setStatus] = useState<PreviewStatus>("idle");
  const [preview, setPreview] = useState<GitPreview | null>(null);
  const [error, setError] = useState("");

  const { fetchWithAuth, apiBase } = useAuthFetch();

  const reset = useCallback(() => {
    setStatus("idle");
    setPreview(null);
    setError("");
  }, []);

  const load = useCallback(async () => {
    setStatus("loading");
    setError("");
    try {
      const res = await fetchWithAuth(`${apiBase}/api/v1/git/preview`, { method: "GET" });
      if (!res.ok) {
        if (res.status === 404) {
          throw new Error(
            "Preview endpoint not available (backend may need a restart to load the new route).",
          );
        }
        let detail = "";
        try {
          const body = (await res.json()) as { error?: string; detail?: string };
          detail = body.error || body.detail || "";
        } catch { /* ignore */ }
        throw new Error(detail || `HTTP ${res.status}`);
      }
      const data = (await res.json()) as GitPreview;
      setPreview(data);
      setStatus("ready");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load preview";
      setStatus("error");
      setError(msg);
    }
  }, [fetchWithAuth, apiBase]);

  return { status, preview, error, load, reset };
}

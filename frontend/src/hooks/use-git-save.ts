"use client";

import { useCallback, useState } from "react";

import { useAuthFetch } from "@/hooks/use-auth-fetch";

// ── Types ─────────────────────────────────────────────────────────────────────

export type SaveStatus = "idle" | "saving" | "saved" | "error";

export interface SaveState {
  status: SaveStatus;
  message: string;
  filesChanged: number;
  commitHash: string;
  error: string;
  save: () => Promise<void>;
  reset: () => void;
}

interface SaveResponse {
  status: string;
  message: string;
  files_changed: number;
  commit_hash: string;
  error: string;
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useGitSave(): SaveState {
  const [status, setStatus] = useState<SaveStatus>("idle");
  const [message, setMessage] = useState("");
  const [filesChanged, setFilesChanged] = useState(0);
  const [commitHash, setCommitHash] = useState("");
  const [error, setError] = useState("");

  const { fetchWithAuth, apiBase } = useAuthFetch();

  const reset = useCallback(() => {
    setStatus("idle");
    setMessage("");
    setFilesChanged(0);
    setCommitHash("");
    setError("");
  }, []);

  const save = useCallback(async () => {
    if (status === "saving") return;

    setStatus("saving");
    setMessage("");
    setError("");

    try {
      const res = await fetchWithAuth(`${apiBase}/api/v1/git/save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });

      const data = (await res.json()) as SaveResponse;

      if (!res.ok) {
        throw new Error(data.error || data.message || `HTTP ${res.status}`);
      }

      if (data.status === "no_changes") {
        setStatus("saved");
        setMessage("Already up to date — nothing to save.");
        return;
      }

      if (data.status === "error") {
        setStatus("error");
        setMessage(data.message || "Save failed");
        setError(data.error || "");
        return;
      }

      // status === "saved"
      setStatus("saved");
      setMessage(data.message);
      setFilesChanged(data.files_changed);
      setCommitHash(data.commit_hash);

      // Auto-reset to idle after 5s
      setTimeout(() => {
        setStatus("idle");
        setMessage("");
      }, 5000);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Save failed";
      setStatus("error");
      setMessage(msg);
      setError(msg);
    }
  }, [status, fetchWithAuth, apiBase]);

  return { status, message, filesChanged, commitHash, error, save, reset };
}

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";

import { useAuthFetch } from "@/hooks/use-auth-fetch";
import { cn } from "@/lib/utils";

import { postRefresh, UsageApiError } from "../_lib/api";
import type { RefreshResponse, RefreshWindowHours } from "../_lib/types";

type Status = "idle" | "running" | "ok" | "error" | "throttled";

interface RefreshButtonProps {
  onRefreshed?: (result: RefreshResponse) => void;
  // When set, the refresh sends this window to the backend.  Default 24h
  // matches the backend default — omitting the prop keeps existing UX.
  windowHours?: RefreshWindowHours;
}

/**
 * Manual "Refresh Usage" trigger.
 *
 * Disables itself while a request is in flight, surfaces the success/error/
 * throttle (HTTP 429) result inline for ~4s, and avoids spamming by ignoring
 * additional clicks until the previous call completes.
 */
export function RefreshButton({ onRefreshed, windowHours }: RefreshButtonProps) {
  const { fetchWithAuth } = useAuthFetch();
  const [status, setStatus] = useState<Status>("idle");
  const [message, setMessage] = useState<string | null>(null);
  // Cancel any in-flight clear-timer when a new click starts so an earlier
  // click's "fade after 4s" can't wipe out the new throttle / error message.
  const clearTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (clearTimerRef.current) clearTimeout(clearTimerRef.current);
    };
  }, []);

  const handleClick = useCallback(async () => {
    if (status === "running") return;
    if (clearTimerRef.current) {
      clearTimeout(clearTimerRef.current);
      clearTimerRef.current = null;
    }
    setStatus("running");
    setMessage(null);
    try {
      const result = await postRefresh(fetchWithAuth, { windowHours });
      setStatus("ok");
      const okCount = result.results.filter((r) => r.status === "ok").length;
      const notConfigured = result.results.filter(
        (r) => r.status === "not_configured",
      ).length;
      const errored = result.results.filter((r) => r.status === "error").length;
      const parts = [`${okCount} live`];
      if (notConfigured) parts.push(`${notConfigured} placeholder`);
      if (errored) parts.push(`${errored} error`);
      setMessage(`Refreshed (${parts.join(", ")})`);
      onRefreshed?.(result);
    } catch (e) {
      if (e instanceof UsageApiError && e.status === 429) {
        setStatus("throttled");
        setMessage(e.message || "Refresh throttled. Please wait a few seconds.");
      } else {
        setStatus("error");
        setMessage(e instanceof Error ? e.message : "Refresh failed");
      }
    } finally {
      clearTimerRef.current = setTimeout(() => {
        setStatus("idle");
        setMessage(null);
        clearTimerRef.current = null;
      }, 4000);
    }
  }, [fetchWithAuth, onRefreshed, status, windowHours]);

  const running = status === "running";

  return (
    <div className="flex items-center gap-3">
      {message && (
        <span
          className="text-xs"
          style={{
            color:
              status === "ok"
                ? "#22c55e"
                : status === "throttled"
                ? "#f59e0b"
                : status === "error"
                ? "#ef4444"
                : "var(--text-quiet)",
          }}
        >
          {message}
        </span>
      )}
      <button
        type="button"
        onClick={() => void handleClick()}
        disabled={running}
        className={cn(
          "inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium",
          "transition-opacity disabled:opacity-50",
        )}
        style={{
          background: "var(--accent)",
          color: "white",
        }}
        aria-label="Refresh usage data"
      >
        {running ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <RefreshCw className="h-4 w-4" />
        )}
        {running ? "Refreshing…" : "Refresh Usage"}
      </button>
    </div>
  );
}

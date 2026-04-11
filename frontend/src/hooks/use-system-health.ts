"use client";

/**
 * useSystemHealth — React hook for reading system monitor state.
 *
 * Subscribes to the singleton systemMonitor and re-renders the component
 * whenever the monitor emits a new state.  Delivers current state on first
 * render so there is no flash of "unknown" after mount.
 *
 * Usage:
 *   const { status, lastCheck, consecutiveFailures, detail } = useSystemHealth();
 */

import { useEffect, useState } from "react";
import { systemMonitor, type MonitorState } from "@/lib/system-monitor";

export function useSystemHealth(): Readonly<MonitorState> {
  // Initialise from singleton so there's no stale state on first render
  const [state, setState] = useState<MonitorState>(() => systemMonitor.getState());

  useEffect(() => {
    // subscribe() delivers current state immediately, then on every change
    return systemMonitor.subscribe(setState);
  }, []);

  return state;
}

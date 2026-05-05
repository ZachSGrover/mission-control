"use client";

import { useCallback, useEffect, useState } from "react";
import {
  type ExecutionMode,
  DEFAULT_EXECUTION_MODE,
  loadExecutionMode,
  saveExecutionMode,
} from "@/lib/execution-mode-store";

export type { ExecutionMode };

export function useExecutionMode() {
  const [mode, setModeState] = useState<ExecutionMode>(DEFAULT_EXECUTION_MODE);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    // Hydrate from localStorage on mount; cannot run during SSR render.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMounted(true);
    setModeState(loadExecutionMode());
  }, []);

  const setMode = useCallback((next: ExecutionMode) => {
    setModeState(next);
    saveExecutionMode(next);
  }, []);

  return { mode, setMode, mounted };
}

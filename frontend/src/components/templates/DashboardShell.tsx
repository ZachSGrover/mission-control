"use client";

import { useCallback, useEffect, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { usePathname } from "next/navigation";
import { Menu, X } from "lucide-react";

import { BrandMark } from "@/components/atoms/BrandMark";

// `-webkit-app-region` is a non-standard Electron/Chrome CSS property that
// flags an element as OS-level window drag surface (or `no-drag` for
// interactive controls inside it). TS CSSProperties doesn't know about it.
const DRAG_REGION = { WebkitAppRegion: "drag" } as CSSProperties;
const NO_DRAG_REGION = { WebkitAppRegion: "no-drag" } as CSSProperties;

// Detect Electron on macOS so we can reserve space for traffic-light buttons
// without wasting left-pad in the browser build. Lazy initializer — reads
// window.electron on the first client render.
function useIsMacElectron(): boolean {
  const [isMacElectron] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    const w = window as unknown as { electron?: { platform?: string } };
    return w.electron?.platform === "darwin";
  });
  return isMacElectron;
}

export function DashboardShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const isMacElectron = useIsMacElectron();

  const [sidebarState, setSidebarState] = useState({ open: false, path: pathname });
  if (sidebarState.path !== pathname) {
    setSidebarState({ open: false, path: pathname });
  }
  const sidebarOpen = sidebarState.open;

  const toggleSidebar = useCallback(
    () => setSidebarState((prev) => ({ open: !prev.open, path: pathname })),
    [pathname],
  );

  useEffect(() => {
    if (!sidebarOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSidebarState((prev) => ({ ...prev, open: false }));
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [sidebarOpen]);

  return (
    <div
      className="h-screen flex flex-col overflow-hidden"
      style={{ background: "var(--bg)", color: "var(--text)" }}
      data-sidebar={sidebarOpen ? "open" : "closed"}
    >
      {/* ── Header ──────────────────────────────────────────────────────── */}
      {/* The header is an Electron drag region (on macOS) so the window can
          be moved by grabbing it. Interactive controls inside opt out via
          NO_DRAG_REGION. */}
      <header
        className="shrink-0 flex items-center border-b"
        style={{
          background: "var(--surface)",
          borderColor: "var(--border)",
          height: "64px",
          ...(isMacElectron ? DRAG_REGION : {}),
        }}
      >
        <div
          className="flex items-center pr-4 shrink-0 w-[220px]"
          style={{ paddingLeft: isMacElectron ? "88px" : "24px" }}
        >
          <button
            type="button"
            className="mr-3 rounded-md p-1.5 md:hidden"
            style={{ color: "var(--text-muted)", ...NO_DRAG_REGION }}
            onClick={toggleSidebar}
            aria-label="Toggle navigation"
          >
            {sidebarOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
          </button>
          <BrandMark />
        </div>

      </header>

      {/* ── Mobile overlay ──────────────────────────────────────────────── */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 md:hidden"
          onClick={toggleSidebar}
          aria-hidden="true"
        />
      )}

      {/* ── Body ───────────────────────────────────────────────────────── */}
      <div className="flex flex-1 overflow-hidden">
        {children}
      </div>
    </div>
  );
}

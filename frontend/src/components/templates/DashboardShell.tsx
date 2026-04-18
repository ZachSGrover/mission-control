"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { Menu, X } from "lucide-react";

import { useAuth } from "@/auth/clerk";
import { BrandMark } from "@/components/atoms/BrandMark";

export function DashboardShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { isSignedIn } = useAuth();

  // DEBUG: track client-side mount and hydration
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
    console.log("APP MOUNTED — DashboardShell hydrated on client");
    console.log("pathname:", pathname);
    console.log("isSignedIn:", isSignedIn);
    console.log("window.location:", window.location.href);
  }, []);

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
      {/* ── DEBUG BANNER — remove after confirming UI loads ── */}
      <div
        style={{
          position: "fixed",
          top: 0,
          left: 0,
          right: 0,
          zIndex: 9999,
          background: mounted ? "#16a34a" : "#dc2626",
          color: "#ffffff",
          textAlign: "center",
          padding: "6px 0",
          fontSize: "13px",
          fontWeight: 700,
          fontFamily: "monospace",
          letterSpacing: "0.05em",
        }}
      >
        {mounted ? "✓ APP LOADED — client hydrated" : "⏳ APP LOADED — SSR (awaiting hydration)"}
      </div>

      {/* ── Header ──────────────────────────────────────────────────────── */}
      <header
        className="shrink-0 flex items-center border-b"
        style={{
          background: "var(--surface)",
          borderColor: "var(--border)",
          height: "64px",
          marginTop: "29px", // offset for debug banner
        }}
      >
        <div className="flex items-center pl-6 pr-4 shrink-0 w-[220px]">
          <button
            type="button"
            className="mr-3 rounded-md p-1.5 md:hidden"
            style={{ color: "var(--text-muted)" }}
            onClick={toggleSidebar}
            aria-label="Toggle navigation"
          >
            {sidebarOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
          </button>
          <BrandMark />
        </div>

        <div className="flex-1" />

        <div className="flex items-center gap-3 pr-5">
          <span
            className="text-xs px-2 py-1 rounded font-mono"
            style={{
              background: isSignedIn ? "rgba(34,197,94,0.15)" : "rgba(245,158,11,0.15)",
              color: isSignedIn ? "#22c55e" : "#f59e0b",
              border: `1px solid ${isSignedIn ? "rgba(34,197,94,0.3)" : "rgba(245,158,11,0.3)"}`,
            }}
          >
            {mounted ? (isSignedIn ? "signed in" : "not signed in") : "..."}
          </span>
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

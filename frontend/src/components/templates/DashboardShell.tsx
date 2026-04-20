"use client";

import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { Menu, X } from "lucide-react";

import { BrandMark } from "@/components/atoms/BrandMark";

export function DashboardShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

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
      <header
        className="shrink-0 flex items-center border-b"
        style={{
          background: "var(--surface)",
          borderColor: "var(--border)",
          height: "64px",
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

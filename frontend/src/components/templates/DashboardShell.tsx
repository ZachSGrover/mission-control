"use client";

import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Menu, X } from "lucide-react";

import { SignedIn, useAuth } from "@/auth/clerk";
import { ApiError } from "@/api/mutator";
import {
  type getMeApiV1UsersMeGetResponse,
  useGetMeApiV1UsersMeGet,
} from "@/api/generated/users/users";
import { BrandMark } from "@/components/atoms/BrandMark";
import { UserMenu } from "@/components/organisms/UserMenu";
import { isOnboardingComplete } from "@/lib/onboarding";

export function DashboardShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { isSignedIn } = useAuth();
  const isOnboardingPath = pathname === "/onboarding";

  const [sidebarState, setSidebarState] = useState({ open: false, path: pathname });
  if (sidebarState.path !== pathname) {
    setSidebarState({ open: false, path: pathname });
  }
  const sidebarOpen = sidebarState.open;

  const meQuery = useGetMeApiV1UsersMeGet<getMeApiV1UsersMeGetResponse, ApiError>({
    query: {
      enabled: Boolean(isSignedIn) && !isOnboardingPath,
      retry: false,
      // "always" caused header/avatar to flash on every route change.
      // true = refetch only when stale (respects 2-min staleTime in QueryProvider).
      refetchOnMount: true,
    },
  });
  const profile = meQuery.data?.status === 200 ? meQuery.data.data : null;
  const displayName = profile?.name ?? profile?.preferred_name ?? "Operator";
  const displayEmail = profile?.email ?? "";

  const skipOnboarding = process.env.NEXT_PUBLIC_SKIP_ONBOARDING === "true";
  useEffect(() => {
    if (skipOnboarding) return;
    if (!isSignedIn || isOnboardingPath) return;
    if (!profile) return;
    if (!isOnboardingComplete(profile)) router.replace("/onboarding");
  }, [isOnboardingPath, isSignedIn, profile, router, skipOnboarding]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const handleStorage = (e: StorageEvent) => {
      if (e.key !== "openclaw_org_switch" || !e.newValue) return;
      window.location.reload();
    };
    window.addEventListener("storage", handleStorage);
    let channel: BroadcastChannel | null = null;
    if ("BroadcastChannel" in window) {
      channel = new BroadcastChannel("org-switch");
      channel.onmessage = () => window.location.reload();
    }
    return () => {
      window.removeEventListener("storage", handleStorage);
      channel?.close();
    };
  }, []);

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
        className="shrink-0 flex items-center h-16 border-b"
        style={{
          background: "var(--surface)",
          borderColor: "var(--border)",
          WebkitAppRegion: "drag",
        } as React.CSSProperties}
      >
        {/* Traffic-light zone + brand */}
        <div className="flex items-center pl-24 pr-4 shrink-0 w-[220px]">
          {isSignedIn ? (
            <button
              type="button"
              className="mr-3 rounded-md p-1.5 md:hidden"
              style={{
                color: "var(--text-muted)",
                WebkitAppRegion: "no-drag",
              } as React.CSSProperties}
              onClick={toggleSidebar}
              aria-label="Toggle navigation"
            >
              {sidebarOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
            </button>
          ) : null}
          <BrandMark />
        </div>

        {/* Drag spacer */}
        <div className="flex-1" />

        {/* Account menu */}
        <SignedIn>
          <div
            className="flex items-center pr-5"
            style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
          >
            <UserMenu displayName={displayName} displayEmail={displayEmail} />
          </div>
        </SignedIn>
      </header>

      {/* ── Mobile overlay ──────────────────────────────────────────────── */}
      {sidebarOpen ? (
        <div
          className="fixed inset-0 z-40 bg-black/50 md:hidden"
          onClick={toggleSidebar}
          aria-hidden="true"
        />
      ) : null}

      {/* ── Body: isolated scroll context ───────────────────────────────── */}
      <div className="flex flex-1 overflow-hidden">
        {children}
      </div>
    </div>
  );
}

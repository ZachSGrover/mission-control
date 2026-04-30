"use client";

import type { ReactNode } from "react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";

/**
 * Shared chrome for every /usage/* page — keeps signed-in/out gating, the
 * sidebar, and the content max-width consistent in one place.
 */
export function UsagePageShell({
  title,
  subtitle,
  actions,
  children,
  redirectPath,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  redirectPath?: string;
}) {
  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel
          message="Sign in to access Digidle OS"
          forceRedirectUrl={redirectPath ?? "/usage"}
        />
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <main
          className="flex-1 overflow-y-auto"
          style={{ background: "var(--bg)" }}
        >
          <div className="max-w-5xl mx-auto px-6 py-8 space-y-8">
            <header className="flex items-start justify-between gap-4">
              <div>
                <h1
                  className="text-xl font-semibold"
                  style={{ color: "var(--text)" }}
                >
                  {title}
                </h1>
                {subtitle && (
                  <p
                    className="mt-1 text-sm"
                    style={{ color: "var(--text-muted)" }}
                  >
                    {subtitle}
                  </p>
                )}
              </div>
              {actions && <div className="flex items-center gap-2">{actions}</div>}
            </header>
            {children}
          </div>
        </main>
      </SignedIn>
    </DashboardShell>
  );
}

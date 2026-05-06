"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { cn } from "@/lib/utils";

const USAGE_TABS: ReadonlyArray<{ href: string; label: string; exact?: boolean }> = [
  { href: "/usage", label: "Overview", exact: true },
  { href: "/usage/providers", label: "Providers" },
  { href: "/usage/daily", label: "Daily" },
  { href: "/usage/projects", label: "Projects" },
  { href: "/usage/alerts", label: "Alerts" },
  { href: "/usage/settings", label: "Settings" },
];

function UsageSubnav() {
  const pathname = usePathname();
  return (
    <nav
      className="-mx-2 flex flex-wrap items-center gap-1 border-b pb-1"
      style={{ borderColor: "var(--border)" }}
      aria-label="Usage Tracker sections"
    >
      {USAGE_TABS.map((tab) => {
        const active = tab.exact ? pathname === tab.href : pathname.startsWith(tab.href);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm transition-colors",
              active ? "font-medium" : "font-normal",
            )}
            style={
              active
                ? { background: "var(--accent-soft)", color: "var(--accent-strong)" }
                : { color: "var(--text-muted)" }
            }
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}

/**
 * Shared chrome for every /usage/* page — keeps signed-in/out gating, the
 * sidebar, and the content max-width consistent in one place.
 *
 * The sidebar collapses Usage Tracker into a single entry, so this shell
 * renders the cross-section tab strip (Overview / Providers / Daily /
 * Projects / Alerts / Settings) immediately under the page header.
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
            <UsageSubnav />
            {children}
          </div>
        </main>
      </SignedIn>
    </DashboardShell>
  );
}

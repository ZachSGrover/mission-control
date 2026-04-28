"use client";

/**
 * Shared chrome for every OnlyFans Intelligence sub-page.
 *
 * Wraps DashboardShell + DashboardSidebar (matching the rest of Mission
 * Control), then renders a horizontal sub-navigation strip listing every
 * OFI section.  Pages drop their content under `<SectionShell title=…>{…}</SectionShell>`.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { cn } from "@/lib/utils";

const SUB_NAV: ReadonlyArray<{ href: string; label: string }> = [
  { href: "/of-intelligence",                    label: "Overview" },
  { href: "/of-intelligence/accounts",           label: "Accounts" },
  { href: "/of-intelligence/account-intelligence", label: "Account Intelligence" },
  { href: "/of-intelligence/chatters",           label: "Chatters" },
  { href: "/of-intelligence/fans",               label: "Fans" },
  { href: "/of-intelligence/messages",           label: "Messages" },
  { href: "/of-intelligence/revenue",            label: "Revenue" },
  { href: "/of-intelligence/mass-messages",      label: "Mass Messages" },
  { href: "/of-intelligence/posting-insights",   label: "Posting Insights" },
  { href: "/of-intelligence/qc-reports",         label: "QC Reports" },
  { href: "/of-intelligence/alerts",             label: "Alerts" },
  { href: "/of-intelligence/memory-bank",        label: "Memory Bank" },
  { href: "/of-intelligence/settings",           label: "Settings" },
];

export function SectionShell({
  title,
  description,
  actions,
  basePath = "/of-intelligence",
  children,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  basePath?: string;
  children: ReactNode;
}) {
  const pathname = usePathname();

  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel
          message="Sign in to access OnlyFans Intelligence."
          forceRedirectUrl={basePath}
        />
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <main className="flex-1 overflow-y-auto" style={{ background: "var(--bg)" }}>
          <div className="px-6 pt-6 pb-3 border-b" style={{ borderColor: "var(--border)" }}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <p
                  className="text-[11px] font-semibold uppercase tracking-widest"
                  style={{ color: "var(--text-quiet)" }}
                >
                  OnlyFans Intelligence
                </p>
                <h1 className="text-xl font-semibold mt-0.5" style={{ color: "var(--text)" }}>
                  {title}
                </h1>
                {description && (
                  <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
                    {description}
                  </p>
                )}
              </div>
              {actions && <div className="shrink-0">{actions}</div>}
            </div>

            <div className="mt-4 -mb-px flex gap-1 overflow-x-auto">
              {SUB_NAV.map((item) => {
                const active =
                  item.href === "/of-intelligence"
                    ? pathname === item.href
                    : pathname.startsWith(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={cn(
                      "px-3 py-2 text-sm rounded-t-md whitespace-nowrap transition-colors border-b-2",
                      active ? "font-medium" : "font-normal",
                    )}
                    style={
                      active
                        ? { color: "var(--accent-strong)", borderColor: "var(--accent-strong)" }
                        : { color: "var(--text-muted)", borderColor: "transparent" }
                    }
                    onMouseEnter={(e) => {
                      if (!active) (e.currentTarget as HTMLElement).style.color = "var(--text)";
                    }}
                    onMouseLeave={(e) => {
                      if (!active) (e.currentTarget as HTMLElement).style.color = "var(--text-muted)";
                    }}
                  >
                    {item.label}
                  </Link>
                );
              })}
            </div>
          </div>

          <div className="p-6">{children}</div>
        </main>
      </SignedIn>
    </DashboardShell>
  );
}

// ── Reusable atoms used across OFI pages ──────────────────────────────────────

export function StatPill({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div
      className="rounded-xl border p-4"
      style={{ background: "var(--surface)", borderColor: "var(--border)" }}
    >
      <p className="text-[11px] font-semibold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>
        {label}
      </p>
      <p className="mt-1 text-xl font-semibold" style={{ color: "var(--text)" }}>{value}</p>
      {hint && (
        <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
          {hint}
        </p>
      )}
    </div>
  );
}

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const s = (status || "unknown").toLowerCase();
  const palette =
    s === "success" || s === "ok" || s === "operational" || s === "active" || s === "open"
      ? { background: "rgba(16,185,129,0.12)", color: "rgb(5,150,105)" }
      : s === "error" || s === "failed" || s === "critical" || s === "lost" || s === "blocked"
      ? { background: "rgba(244,63,94,0.12)", color: "rgb(225,29,72)" }
      : s === "warn" || s === "warning" || s === "partial" || s === "pending" || s === "running"
      ? { background: "rgba(245,158,11,0.12)", color: "rgb(217,119,6)" }
      : s === "not_available_from_api" || s === "skipped"
      ? { background: "rgba(100,116,139,0.12)", color: "rgb(71,85,105)" }
      : { background: "rgba(100,116,139,0.12)", color: "rgb(71,85,105)" };
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium"
      style={palette}
    >
      {status || "unknown"}
    </span>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div
      className="rounded-xl border p-10 text-center"
      style={{ background: "var(--surface)", borderColor: "var(--border)" }}
    >
      <p className="text-base font-medium" style={{ color: "var(--text)" }}>{title}</p>
      {hint && (
        <p className="text-sm mt-2" style={{ color: "var(--text-muted)" }}>{hint}</p>
      )}
    </div>
  );
}

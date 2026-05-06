"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/hermes",            label: "Overview" },
  { href: "/hermes/incidents",  label: "Active incidents" },
  { href: "/hermes/repair",     label: "Repair center" },
  { href: "/hermes/safety",     label: "Safety rules" },
];

export function HermesSubnav() {
  const pathname = usePathname() ?? "";
  return (
    <nav
      aria-label="Hermes sections"
      className="mb-6 flex flex-wrap gap-1 border-b pb-1"
      style={{ borderColor: "var(--border, rgba(255,255,255,0.08))" }}
    >
      {TABS.map((tab) => {
        const active =
          tab.href === "/hermes"
            ? pathname === "/hermes"
            : pathname.startsWith(tab.href);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className="rounded-md px-3 py-1.5 text-sm font-medium transition-colors"
            style={
              active
                ? {
                    backgroundColor: "var(--surface, rgba(255,255,255,0.05))",
                    color: "var(--foreground)",
                  }
                : { color: "var(--muted-foreground, #94a3b8)" }
            }
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}

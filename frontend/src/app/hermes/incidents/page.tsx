"use client";

export const dynamic = "force-dynamic";

import { useMemo, useState } from "react";

import { useAuth } from "@/auth/clerk";

import { HermesSubnav } from "@/components/hermes/HermesSubnav";
import { IncidentCard } from "@/components/hermes/IncidentCard";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";

import { isActive, severityRank, useHermesIncidents } from "@/lib/hermes-client";
import { useOrganizationMembership } from "@/lib/use-organization-membership";

const FILTERS = [
  { key: "active",   label: "Active" },
  { key: "all",      label: "All" },
  { key: "resolved", label: "Resolved" },
] as const;

type FilterKey = (typeof FILTERS)[number]["key"];

export default function HermesIncidentsPage() {
  const { isSignedIn } = useAuth();
  const { isAdmin } = useOrganizationMembership(isSignedIn);
  const query = useHermesIncidents();

  const [filter, setFilter] = useState<FilterKey>("active");

  const filtered = useMemo(() => {
    const all = query.data?.incidents ?? [];
    const matching =
      filter === "active"
        ? all.filter(isActive)
        : filter === "resolved"
        ? all.filter((i) => i.status === "resolved")
        : all;
    return [...matching].sort((a, b) => {
      const sd = severityRank(b.severity) - severityRank(a.severity);
      if (sd !== 0) return sd;
      return (b.last_fired_at_unix ?? 0) - (a.last_fired_at_unix ?? 0);
    });
  }, [query.data, filter]);

  return (
    <DashboardPageLayout
      signedOut={{
        message: "Sign in to view Hermes incidents.",
        forceRedirectUrl: "/hermes/incidents",
        signUpForceRedirectUrl: "/hermes/incidents",
      }}
      title="Hermes — Active incidents"
      description="Diagnostic alerts surfaced from the Hermes watchdog hooks."
      isAdmin={isAdmin}
      adminOnlyMessage="Only organization owners and admins can view Hermes."
      stickyHeader
    >
      <HermesSubnav />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            onClick={() => setFilter(f.key)}
            className="rounded-md border px-3 py-1 text-xs font-medium transition-colors"
            style={{
              backgroundColor:
                filter === f.key ? "var(--surface, rgba(255,255,255,0.06))" : "transparent",
              borderColor: "var(--border, rgba(255,255,255,0.08))",
              color: "var(--foreground)",
            }}
          >
            {f.label}
          </button>
        ))}
        {query.data?.parse_warnings ? (
          <span className="ml-auto text-xs text-[color:var(--muted-foreground,#94a3b8)]">
            ⚠ {query.data.parse_warnings} state file(s) could not be parsed.
          </span>
        ) : null}
      </div>

      {query.isLoading && (
        <p className="text-sm text-[color:var(--muted-foreground,#94a3b8)]">
          Loading incidents…
        </p>
      )}

      {query.isError && (
        <div
          className="rounded-lg border p-4 text-sm"
          style={{
            backgroundColor: "var(--surface, rgba(255,255,255,0.02))",
            borderColor: "var(--border, rgba(255,255,255,0.08))",
          }}
        >
          The Hermes incidents API is not responding right now.
        </div>
      )}

      {query.data && filtered.length === 0 && (
        <p className="text-sm text-[color:var(--muted-foreground,#94a3b8)]">
          {filter === "active"
            ? "All monitored Hermes systems are currently healthy or no active incident state was found."
            : filter === "resolved"
            ? "No resolved incidents on record."
            : "No incidents on record."}
        </p>
      )}

      <div className="grid gap-4">
        {filtered.map((incident) => (
          <IncidentCard key={incident.alert_id} incident={incident} />
        ))}
      </div>
    </DashboardPageLayout>
  );
}

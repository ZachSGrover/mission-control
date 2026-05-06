"use client";

export const dynamic = "force-dynamic";

import { useAuth } from "@/auth/clerk";

import { HermesSubnav } from "@/components/hermes/HermesSubnav";
import { IncidentCard } from "@/components/hermes/IncidentCard";
import { SeverityBadge } from "@/components/hermes/SeverityBadge";
import { StatusBadge } from "@/components/hermes/StatusBadge";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";

import { formatTimestamp, useHermesStatus } from "@/lib/hermes-client";
import { useOrganizationMembership } from "@/lib/use-organization-membership";

const CARD_STYLE = {
  backgroundColor: "var(--surface, rgba(255,255,255,0.02))",
  borderColor: "var(--border, rgba(255,255,255,0.08))",
};

export default function HermesOverviewPage() {
  const { isSignedIn } = useAuth();
  const { isAdmin } = useOrganizationMembership(isSignedIn);
  const query = useHermesStatus();

  const data = query.data;

  return (
    <DashboardPageLayout
      signedOut={{
        message: "Sign in to view Hermes.",
        forceRedirectUrl: "/hermes",
        signUpForceRedirectUrl: "/hermes",
      }}
      title="Hermes"
      description="Live diagnostic alerts, repair plans, and system safety rules."
      isAdmin={isAdmin}
      adminOnlyMessage="Only organization owners and admins can view Hermes."
      stickyHeader
    >
      <HermesSubnav />

      {query.isLoading && (
        <p className="text-sm text-[color:var(--muted-foreground,#94a3b8)]">Loading Hermes status…</p>
      )}

      {query.isError && (
        <div
          className="rounded-lg border p-4 text-sm"
          style={CARD_STYLE}
        >
          <strong>Hermes status unavailable.</strong> The Hermes API endpoint
          is not responding. The watchdog hooks may still be working — only
          this Mission Control view is offline.
        </div>
      )}

      {data && (
        <div className="space-y-6">
          {/* Founder summary */}
          <section
            className="rounded-lg border p-5"
            style={CARD_STYLE}
          >
            <header className="flex flex-wrap items-center gap-2">
              <h2 className="text-sm font-semibold uppercase tracking-wide">
                Hermes overall
              </h2>
              <StatusBadge status={data.overall} />
            </header>
            <p className="mt-2 text-base leading-relaxed">{data.summary}</p>
            {data.parse_warnings > 0 && (
              <p className="mt-2 text-xs text-[color:var(--muted-foreground,#94a3b8)]">
                ⚠ Some Hermes state files could not be parsed (
                {data.parse_warnings}). They are skipped on display.
              </p>
            )}
            {!data.state_dir_present && (
              <p className="mt-2 text-xs text-[color:var(--muted-foreground,#94a3b8)]">
                No alert state directory found at <code>$MC_STATE_DIR/alerts/</code> yet.
                Once a watchdog fires an alert, incidents will appear here.
              </p>
            )}
          </section>

          {/* Counts */}
          <section className="grid gap-4 sm:grid-cols-3">
            <CountCard label="Active incidents" value={data.active_incident_count} />
            <CountCard label="Repeated issues" value={data.repeated_incident_count} note="3+ failures" />
            <CountCard label="Monitored systems" value={data.systems.length} />
          </section>

          {/* Per-system grid */}
          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide">
              Monitored systems
            </h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {data.systems.map((s) => (
                <div
                  key={s.name}
                  className="rounded-lg border p-4"
                  style={CARD_STYLE}
                >
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm font-semibold">{s.name}</h3>
                    <span className="ml-auto">
                      <StatusBadge status={s.status} />
                    </span>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-[color:var(--muted-foreground,#94a3b8)]">
                    {s.severity && <SeverityBadge severity={s.severity} />}
                    {s.last_alert_at && <span>Last alert: {formatTimestamp(s.last_alert_at)}</span>}
                    {s.note && <span>{s.note}</span>}
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Last alert + last resolved */}
          {(data.last_alert || data.last_resolved) && (
            <section className="grid gap-4 lg:grid-cols-2">
              {data.last_alert && (
                <div>
                  <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide">
                    Last alert
                  </h2>
                  <IncidentCard incident={data.last_alert} />
                </div>
              )}
              {data.last_resolved && (
                <div>
                  <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide">
                    Last resolved
                  </h2>
                  <IncidentCard incident={data.last_resolved} showRepairLink={false} />
                </div>
              )}
            </section>
          )}
        </div>
      )}
    </DashboardPageLayout>
  );
}

function CountCard({ label, value, note }: { label: string; value: number; note?: string }) {
  return (
    <div
      className="rounded-lg border p-4"
      style={CARD_STYLE}
    >
      <div className="text-xs font-semibold uppercase tracking-wide text-[color:var(--muted-foreground,#94a3b8)]">
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      {note && (
        <div className="mt-1 text-xs text-[color:var(--muted-foreground,#94a3b8)]">{note}</div>
      )}
    </div>
  );
}

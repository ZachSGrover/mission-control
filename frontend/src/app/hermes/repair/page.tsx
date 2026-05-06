"use client";

export const dynamic = "force-dynamic";

import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { useAuth } from "@/auth/clerk";

import { CopyButton } from "@/components/hermes/CopyButton";
import { HermesSubnav } from "@/components/hermes/HermesSubnav";
import { SeverityBadge } from "@/components/hermes/SeverityBadge";
import { StatusBadge } from "@/components/hermes/StatusBadge";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";

import { isActive, useHermesIncidents, useHermesRepairPlan } from "@/lib/hermes-client";
import { useOrganizationMembership } from "@/lib/use-organization-membership";

const CARD_STYLE = {
  backgroundColor: "var(--surface, rgba(255,255,255,0.02))",
  borderColor: "var(--border, rgba(255,255,255,0.08))",
};

const SECTION_LABEL =
  "text-xs font-semibold uppercase tracking-wide text-[color:var(--muted-foreground,#94a3b8)]";

export default function HermesRepairPage() {
  const { isSignedIn } = useAuth();
  const { isAdmin } = useOrganizationMembership(isSignedIn);
  const search = useSearchParams();
  const alertId = search.get("id");

  const incidents = useHermesIncidents();
  const plan = useHermesRepairPlan(alertId);
  const incident =
    alertId && incidents.data
      ? incidents.data.incidents.find((i) => i.alert_id === alertId)
      : null;

  return (
    <DashboardPageLayout
      signedOut={{
        message: "Sign in to view Hermes repair plans.",
        forceRedirectUrl: "/hermes/repair",
        signUpForceRedirectUrl: "/hermes/repair",
      }}
      title="Hermes — Repair center"
      description="Read-only repair plans. No automated restarts, no destructive actions."
      isAdmin={isAdmin}
      adminOnlyMessage="Only organization owners and admins can view Hermes."
      stickyHeader
    >
      <HermesSubnav />

      {!alertId ? (
        <RepairIndex incidents={incidents.data?.incidents ?? []} loading={incidents.isLoading} />
      ) : plan.isLoading ? (
        <p className="text-sm text-[color:var(--muted-foreground,#94a3b8)]">
          Loading repair plan…
        </p>
      ) : plan.isError ? (
        <div className="rounded-lg border p-4 text-sm" style={CARD_STYLE}>
          Could not load a repair plan for <code>{alertId}</code>. The alert may
          have been resolved or its state file was cleaned up.
          <div className="mt-3">
            <Link
              href="/hermes/repair"
              className="text-xs underline-offset-2 hover:underline"
              style={{ color: "var(--accent, #60a5fa)" }}
            >
              ← Back to repair index
            </Link>
          </div>
        </div>
      ) : plan.data ? (
        <div className="space-y-6">
          <Link
            href="/hermes/repair"
            className="text-xs underline-offset-2 hover:underline"
            style={{ color: "var(--accent, #60a5fa)" }}
          >
            ← Back to repair index
          </Link>

          <header
            className="flex flex-wrap items-center gap-2 rounded-lg border p-4"
            style={CARD_STYLE}
          >
            {incident && <SeverityBadge severity={incident.severity} />}
            {incident && <StatusBadge status={incident.status} />}
            <h2 className="text-base font-semibold">
              {incident?.system ?? "Incident"}
            </h2>
            <span
              className="ml-auto rounded-md px-2 py-0.5 text-xs font-medium"
              style={{ backgroundColor: "rgba(148, 163, 184, 0.18)", color: "#cbd5e1" }}
            >
              Mode: {plan.data.repair_mode}
            </span>
          </header>

          {/* Recommended next action */}
          <section className="rounded-lg border p-5" style={CARD_STYLE}>
            <h3 className={SECTION_LABEL}>Recommended next action</h3>
            <p className="mt-2 text-sm leading-relaxed">{plan.data.recommended_next_action}</p>
          </section>

          {/* Inspect checklist */}
          <section className="rounded-lg border p-5" style={CARD_STYLE}>
            <div className="flex items-center gap-2">
              <h3 className={SECTION_LABEL}>Safe inspection checklist</h3>
              {plan.data.inspect_checklist.length > 0 && (
                <span className="ml-auto">
                  <CopyButton
                    text={plan.data.inspect_checklist
                      .map((line, i) => `${i + 1}. ${line}`)
                      .join("\n")}
                    label="Copy checklist"
                  />
                </span>
              )}
            </div>
            {plan.data.inspect_checklist.length > 0 ? (
              <ol className="mt-3 list-decimal space-y-1 pl-5 text-sm">
                {plan.data.inspect_checklist.map((line, idx) => (
                  <li key={idx}>{line}</li>
                ))}
              </ol>
            ) : (
              <p className="mt-2 text-sm text-[color:var(--muted-foreground,#94a3b8)]">
                No structured inspect checklist for this alert. See the repair
                prompt below.
              </p>
            )}
          </section>

          {/* Claude repair prompt */}
          <section className="rounded-lg border p-5" style={CARD_STYLE}>
            <div className="flex items-center gap-2">
              <h3 className={SECTION_LABEL}>Copy/paste repair prompt</h3>
              <span className="ml-auto">
                <CopyButton text={plan.data.claude_prompt} label="Copy prompt" />
              </span>
            </div>
            <pre
              className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap rounded-md p-3 text-xs leading-relaxed"
              style={{
                backgroundColor: "var(--surface-2, rgba(0,0,0,0.25))",
                border: "1px solid var(--border, rgba(255,255,255,0.08))",
              }}
            >
              {plan.data.claude_prompt}
            </pre>
          </section>

          {/* Approval + blocked actions */}
          <section className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-lg border p-5" style={CARD_STYLE}>
              <h3 className={SECTION_LABEL}>Approval required</h3>
              <p className="mt-2 text-sm">
                {plan.data.approval_required
                  ? "Yes — Zach must approve any restart, deploy, or destructive action."
                  : "Not required for the actions in this plan."}
              </p>
            </div>
            <div className="rounded-lg border p-5" style={CARD_STYLE}>
              <h3 className={SECTION_LABEL}>Blocked actions</h3>
              {plan.data.blocked_actions.length > 0 ? (
                <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
                  {plan.data.blocked_actions.map((a, i) => (
                    <li key={i}>{a}</li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-sm text-[color:var(--muted-foreground,#94a3b8)]">
                  No system-specific blocks beyond the global safety rules.
                </p>
              )}
            </div>
          </section>

          {/* Disabled action buttons (visual placeholders) */}
          <section className="rounded-lg border p-5" style={CARD_STYLE}>
            <h3 className={SECTION_LABEL}>Actions</h3>
            <p className="mt-2 text-xs text-[color:var(--muted-foreground,#94a3b8)]">
              Auto-repair is disabled in this slice. Restart, redeploy, and
              rollback actions require manual approval and are run by Zach
              from a terminal.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <DisabledActionButton label="Auto-restart affected service" />
              <DisabledActionButton label="Trigger redeploy" />
              <DisabledActionButton label="Run rollback" />
            </div>
          </section>

          {/* Rollback notes */}
          <section className="rounded-lg border p-5" style={CARD_STYLE}>
            <h3 className={SECTION_LABEL}>Rollback notes</h3>
            <p className="mt-2 text-sm leading-relaxed">{plan.data.rollback_notes}</p>
          </section>
        </div>
      ) : null}
    </DashboardPageLayout>
  );
}

function DisabledActionButton({ label }: { label: string }) {
  return (
    <button
      type="button"
      disabled
      title="Disabled — manual approval only in this slice"
      className="rounded-md border px-3 py-1.5 text-xs font-medium opacity-60"
      style={{
        borderColor: "var(--border, rgba(255,255,255,0.08))",
        color: "var(--muted-foreground, #94a3b8)",
        cursor: "not-allowed",
      }}
    >
      {label} (disabled)
    </button>
  );
}

function RepairIndex({
  incidents,
  loading,
}: {
  incidents: Array<{ alert_id: string; system: string; status: string; severity: string }>;
  loading: boolean;
}) {
  const active = incidents.filter((i) =>
    isActive({
      ...i,
      evidence: [],
      exact_issue: "",
      likely_cause: "",
      business_impact: "",
      recommended_fix: "",
      claude_prompt: "",
    } as never),
  );

  if (loading) {
    return (
      <p className="text-sm text-[color:var(--muted-foreground,#94a3b8)]">
        Loading active incidents…
      </p>
    );
  }

  if (active.length === 0) {
    return (
      <p className="text-sm text-[color:var(--muted-foreground,#94a3b8)]">
        All monitored Hermes systems are currently healthy or no active
        incident state was found. Nothing to repair right now.
      </p>
    );
  }

  return (
    <ul className="grid gap-3">
      {active.map((i) => (
        <li
          key={i.alert_id}
          className="rounded-lg border p-4"
          style={CARD_STYLE}
        >
          <div className="flex flex-wrap items-center gap-2">
            <SeverityBadge severity={i.severity as never} />
            <StatusBadge status={i.status as never} />
            <span className="font-semibold">{i.system}</span>
            <Link
              href={`/hermes/repair?id=${encodeURIComponent(i.alert_id)}`}
              className="ml-auto text-xs font-medium underline-offset-2 hover:underline"
              style={{ color: "var(--accent, #60a5fa)" }}
            >
              View repair plan →
            </Link>
          </div>
        </li>
      ))}
    </ul>
  );
}

"use client";

export const dynamic = "force-dynamic";

import { useAuth } from "@/auth/clerk";

import { HermesSubnav } from "@/components/hermes/HermesSubnav";
import { DashboardPageLayout } from "@/components/templates/DashboardPageLayout";

import { useHermesSafety } from "@/lib/hermes-client";
import { useOrganizationMembership } from "@/lib/use-organization-membership";

const CARD_STYLE = {
  backgroundColor: "var(--surface, rgba(255,255,255,0.02))",
  borderColor: "var(--border, rgba(255,255,255,0.08))",
};

const ROW_LABELS: Array<[keyof RuleData, string]> = [
  ["auto_inspect",       "Auto-inspect"],
  ["auto_restart",       "Auto-restart"],
  ["auto_commit",        "Auto-commit"],
  ["auto_push",          "Auto-push"],
  ["auto_deploy",        "Auto-deploy"],
  ["secret_rotation",    "Secret rotation"],
  ["database_writes",    "Database writes"],
  ["onlyfans_writes",    "OnlyFans writes"],
  ["onlymonster_writes", "OnlyMonster writes"],
  ["browser_automation", "Browser automation"],
  ["restarts",           "Service restarts"],
];

interface RuleData {
  auto_inspect: string;
  auto_restart: string;
  auto_commit: string;
  auto_push: string;
  auto_deploy: string;
  secret_rotation: string;
  database_writes: string;
  onlyfans_writes: string;
  onlymonster_writes: string;
  browser_automation: string;
  restarts: string;
}

function ruleTone(value: string): { fg: string; bg: string } {
  const v = value.toLowerCase();
  if (v.includes("never") || v.includes("blocked") || v.includes("disabled")) {
    return { fg: "#f87171", bg: "rgba(239, 68, 68, 0.15)" };
  }
  if (v.includes("approval")) {
    return { fg: "#facc15", bg: "rgba(234, 179, 8, 0.15)" };
  }
  if (v.includes("manual")) {
    return { fg: "#fb923c", bg: "rgba(249, 115, 22, 0.15)" };
  }
  if (v.includes("future")) {
    return { fg: "#94a3b8", bg: "rgba(148, 163, 184, 0.15)" };
  }
  return { fg: "#94a3b8", bg: "rgba(148, 163, 184, 0.15)" };
}

export default function HermesSafetyPage() {
  const { isSignedIn } = useAuth();
  const { isAdmin } = useOrganizationMembership(isSignedIn);
  const query = useHermesSafety();

  return (
    <DashboardPageLayout
      signedOut={{
        message: "Sign in to view Hermes safety rules.",
        forceRedirectUrl: "/hermes/safety",
        signUpForceRedirectUrl: "/hermes/safety",
      }}
      title="Hermes — Safety rules"
      description="The constraints that prevent Hermes from taking destructive action automatically."
      isAdmin={isAdmin}
      adminOnlyMessage="Only organization owners and admins can view Hermes."
      stickyHeader
    >
      <HermesSubnav />

      <p className="mb-4 text-sm leading-relaxed text-[color:var(--muted-foreground,#94a3b8)]">
        Read-only. These rules are enforced in code; this page is the
        operator-facing reflection of them. Changing them requires editing
        the Hermes scripts and a code review.
      </p>

      {query.isLoading && (
        <p className="text-sm text-[color:var(--muted-foreground,#94a3b8)]">Loading…</p>
      )}

      {query.isError && (
        <div className="rounded-lg border p-4 text-sm" style={CARD_STYLE}>
          The Hermes safety endpoint is not responding right now.
        </div>
      )}

      {query.data && (
        <div className="overflow-hidden rounded-lg border" style={CARD_STYLE}>
          <table className="w-full text-sm">
            <thead>
              <tr
                className="text-left text-xs font-semibold uppercase tracking-wide"
                style={{
                  backgroundColor: "var(--surface-2, rgba(0,0,0,0.15))",
                  color: "var(--muted-foreground, #94a3b8)",
                }}
              >
                <th className="px-4 py-2.5">Rule</th>
                <th className="px-4 py-2.5">Setting</th>
              </tr>
            </thead>
            <tbody>
              {ROW_LABELS.map(([key, label]) => {
                const value = query.data![key];
                const tone = ruleTone(value);
                return (
                  <tr
                    key={key}
                    className="border-t"
                    style={{ borderColor: "var(--border, rgba(255,255,255,0.08))" }}
                  >
                    <td className="px-4 py-2.5 font-medium">{label}</td>
                    <td className="px-4 py-2.5">
                      <span
                        className="inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium"
                        style={{ color: tone.fg, backgroundColor: tone.bg }}
                      >
                        {value}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </DashboardPageLayout>
  );
}

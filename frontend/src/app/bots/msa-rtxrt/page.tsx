"use client";

export const dynamic = "force-dynamic";

import { useCallback, useState } from "react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import {
  MsaRtxrtControlPanel,
  type JobKind,
  type MsaRtxrtJob,
  type RunnerStatus,
} from "@/components/bots/MsaRtxrtControlPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { useRole } from "@/hooks/use-role";

// MSA RT/X Automation Bot — Mission Control control panel page.
//
// This route is the "Bots → MSA RT/X Automation Bot" detail surface. The
// backend job bridge that lets the Claw runner actually pick up queued jobs
// is NOT in this PR (see the local-runners README). Until it lands, the
// page renders in `runnerStatus: "offline"` mode and every submit returns
// a "no backend bridge yet" error to the user via the standard control
// panel state. The component is fully role-gated.

function MsaRtxrtPageContent() {
  // The runner status / recent jobs come from the (not-yet-implemented)
  // backend bridge. Until then this is a stable "offline" view.
  const [runnerStatus, setRunnerStatus] = useState<RunnerStatus>("offline");
  const [recentJobs] = useState<MsaRtxrtJob[]>([]);

  const { realRole } = useRole();
  const isOwner = realRole === "owner";

  const handleSubmitJob = useCallback(async (_kind: JobKind) => {
    // Backend bridge not connected yet — surface the same "offline"
    // posture the panel shows so we don't lie to the operator. Once the
    // bridge lands this becomes a fetchWithAuth POST to the job endpoint.
    return Promise.reject(
      new Error(
        "MSA RT/X backend bridge is not connected yet. The Claw runner must be online and the backend job endpoint must be live before jobs can be enqueued.",
      ),
    );
  }, []);

  const handleRefresh = useCallback(async () => {
    // No backend bridge yet — refresh is a no-op that keeps the badge
    // in "offline" state until the bridge ships.
    setRunnerStatus("offline");
  }, []);

  return (
    <main
      className="flex-1 overflow-y-auto"
      style={{ background: "var(--bg)" }}
    >
      <div className="mx-auto max-w-3xl px-6 py-10">
        <MsaRtxrtControlPanel
          runnerStatus={runnerStatus}
          recentJobs={recentJobs}
          isOwner={isOwner}
          onSubmitJob={handleSubmitJob}
          onRefresh={handleRefresh}
        />
      </div>
    </main>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function MsaRtxrtBotPage() {
  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel
          message="Sign in to access the MSA RT/X bot control panel"
          forceRedirectUrl="/bots/msa-rtxrt"
        />
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <RoleGuard
          require="operator"
          denied={
            <main
              className="flex-1 flex items-center justify-center"
              style={{ background: "var(--bg)" }}
            >
              <p className="text-sm" style={{ color: "var(--text-quiet)" }}>
                Operator access required.
              </p>
            </main>
          }
        >
          <MsaRtxrtPageContent />
        </RoleGuard>
      </SignedIn>
    </DashboardShell>
  );
}

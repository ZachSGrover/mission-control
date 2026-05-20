"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useRef, useState } from "react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import {
  deriveRunnerStatus,
  jobBodyForKind,
  rowsToJobs,
  type BackendJobRow,
  type BackendRunnerHeartbeat,
  type BackendRunnerStatus,
} from "@/components/bots/MsaRtxrtClient";
import type {
  JobKind,
  MsaRtxrtJob,
  RunnerStatus,
} from "@/components/bots/MsaRtxrtControlPanel";
import { MsaRtxrtDashboard } from "@/components/bots/MsaRtxrtDashboard";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import { useRole } from "@/hooks/use-role";
import { getApiBaseUrl } from "@/lib/api-base";

// MSA RT/X Automation Bot — Mission Control control panel page.
//
// The page is the *control panel*. It enqueues jobs via the backend and
// reads back recent rows. The real automation runs on the Claw computer
// via the local Python runner; this UI never directly drives external
// services. Live-one is owner-gated client-side and re-checked server-side.

const MAX_JOBS = 10;

function MsaRtxrtPageContent() {
  const [runnerStatus, setRunnerStatus] = useState<RunnerStatus>("unknown");
  const [recentJobs, setRecentJobs] = useState<MsaRtxrtJob[]>([]);
  // Multi-runner: keep the full heartbeat snapshot so the selector
  // dropdown can list every known runner, not just "any online".
  const [runners, setRunners] = useState<BackendRunnerHeartbeat[]>([]);
  // The operator's currently-selected target runner. ``null`` means no
  // selection — run buttons disable until the operator picks one. We
  // sticky-select the first online runner on initial load so the page
  // works out-of-the-box for the common single-runner case (claw-1).
  const [selectedRunnerId, setSelectedRunnerId] = useState<string | null>(null);
  // Track whether we've auto-selected once so we don't override a
  // deliberate operator choice on subsequent refreshes.
  const autoSelectedRef = useRef(false);

  const { realRole } = useRole();
  const isOwner = realRole === "owner";

  const { fetchWithAuth } = useAuthFetch();
  // Stable ref so the callbacks below don't re-create on every render.
  const fetchRef = useRef(fetchWithAuth);
  useEffect(() => {
    fetchRef.current = fetchWithAuth;
  }, [fetchWithAuth]);

  const refresh = useCallback(async () => {
    // Fire both fetches in parallel — the bridge supplies one for jobs
    // (the source of truth for "busy") and one for runner heartbeat
    // (the source of truth for "online vs offline").
    const apiBase = getApiBaseUrl();
    try {
      const [jobsRes, statusRes] = await Promise.all([
        fetchRef.current(`${apiBase}/api/v1/msa-rtxrt/jobs?limit=${MAX_JOBS}`),
        fetchRef.current(`${apiBase}/api/v1/msa-rtxrt/runner/status`),
      ]);

      let rows: BackendJobRow[] = [];
      if (jobsRes.ok) {
        const data = (await jobsRes.json()) as { items?: unknown };
        rows = Array.isArray(data.items) ? (data.items as BackendJobRow[]) : [];
        setRecentJobs(rowsToJobs(rows));
      }

      let heartbeat: BackendRunnerStatus | null = null;
      if (statusRes.ok) {
        const data = (await statusRes.json()) as Partial<BackendRunnerStatus>;
        if (Array.isArray(data.runners) && typeof data.any_online === "boolean") {
          heartbeat = data as BackendRunnerStatus;
          setRunners(heartbeat.runners);
          // First-time auto-select: the first online runner (typically
          // claw-1 in the single-runner deploy). Skip if the operator
          // already picked one, or if there are no online runners.
          if (!autoSelectedRef.current && selectedRunnerId === null) {
            const firstOnline = heartbeat.runners.find(
              (r) => r.status === "online",
            );
            if (firstOnline) {
              setSelectedRunnerId(firstOnline.runner_id);
              autoSelectedRef.current = true;
            }
          }
        }
      }

      // Heartbeat is the preferred signal; falls back to job-derived
      // status if /runner/status was unavailable (graceful degradation).
      // Multi-runner-aware: the pill reflects the selected runner's
      // online state, not "any runner online".
      setRunnerStatus(
        deriveRunnerStatus(rows, heartbeat, undefined, undefined, selectedRunnerId),
      );
    } catch {
      // Network / auth fail → behave like the runner is offline so run
      // buttons stay gated.
      setRunnerStatus("offline");
    }
  }, [selectedRunnerId]);

  // Initial load. The refresh callback writes to state; that's the only
  // way to surface backend data on mount, so we keep the rule-eslint
  // disable consistent with the existing pattern in
  // frontend/src/app/chat/page.tsx.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  const handleSubmitJob = useCallback(
    async (kind: JobKind, targetRunnerId: string | null) => {
      const res = await fetchRef.current(`${getApiBaseUrl()}/api/v1/msa-rtxrt/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(jobBodyForKind(kind, targetRunnerId)),
      });
      if (!res.ok) {
        // Surface the backend's privacy-safe detail message if present.
        const body = (await res.json().catch(() => null)) as
          | { detail?: string }
          | null;
        throw new Error(body?.detail ?? `HTTP ${res.status}`);
      }
      // Optimistic refresh so the new row appears in run history.
      await refresh();
    },
    [refresh],
  );

  return (
    <MsaRtxrtDashboard
      runnerStatus={runnerStatus}
      recentJobs={recentJobs}
      isOwner={isOwner}
      runners={runners}
      selectedRunnerId={selectedRunnerId}
      onSelectRunner={setSelectedRunnerId}
      onSubmitJob={handleSubmitJob}
      onRefresh={refresh}
    />
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

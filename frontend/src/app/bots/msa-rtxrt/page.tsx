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

  const { realRole } = useRole();
  const isOwner = realRole === "owner";

  const { fetchWithAuth } = useAuthFetch();
  // Stable ref so the callbacks below don't re-create on every render.
  const fetchRef = useRef(fetchWithAuth);
  useEffect(() => {
    fetchRef.current = fetchWithAuth;
  }, [fetchWithAuth]);

  const refresh = useCallback(async () => {
    try {
      const res = await fetchRef.current(
        `${getApiBaseUrl()}/api/v1/msa-rtxrt/jobs?limit=${MAX_JOBS}`,
      );
      if (!res.ok) {
        setRunnerStatus("offline");
        return;
      }
      const data = (await res.json()) as { items?: unknown };
      const rows = Array.isArray(data.items) ? (data.items as BackendJobRow[]) : [];
      setRecentJobs(rowsToJobs(rows));
      setRunnerStatus(deriveRunnerStatus(rows));
    } catch {
      // Network / auth fail → behave like the runner is offline. The
      // UI gates run buttons accordingly.
      setRunnerStatus("offline");
    }
  }, []);

  // Initial load. The refresh callback writes to state; that's the only
  // way to surface backend data on mount, so we keep the rule-eslint
  // disable consistent with the existing pattern in
  // frontend/src/app/chat/page.tsx.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  const handleSubmitJob = useCallback(
    async (kind: JobKind) => {
      const res = await fetchRef.current(`${getApiBaseUrl()}/api/v1/msa-rtxrt/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(jobBodyForKind(kind)),
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

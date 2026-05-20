// MSA RT/X client-side helpers — pure functions for JSON⇄UI mapping
// and the `runnerStatus` derivation. Pulled out of the page so they're
// trivially unit-testable without rendering anything.

import type {
  JobKind,
  JobStatus,
  MsaRtxrtJob,
  RunnerStatus,
} from "./MsaRtxrtControlPanel";

/** Shape returned by `GET /api/v1/msa-rtxrt/jobs` (and the poll/patch APIs). */
export interface BackendJobRow {
  id: string;
  kind: string;
  status: string;
  requested_by_user_id: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  summary: string | null;
  stdout_excerpt: string | null;
  error_excerpt: string | null;
  /** Runner that *claimed* the job. ``null`` while still queued. */
  runner_id: string | null;
  /**
   * Runner the job was *targeted at* by the operator when enqueued.
   * ``null`` means "any runner may claim it" — back-compat with rows
   * created before multi-runner targeting. May be present even before
   * the job is claimed.
   */
  target_runner_id: string | null;
  dry_run: boolean;
  live_one: boolean;
  max_test_actions: number;
}

const VALID_KINDS: ReadonlySet<JobKind> = new Set<JobKind>([
  "smoke",
  "dry_run_blast",
  "dry_run_dm",
  "dry_run_repost",
  "dry_run_builder",
  "dry_run_scan",
  "live_one_blast",
  "live_one_dm",
  "live_one_repost",
  "live_one_builder",
  "live_one_scan",
]);

const VALID_STATUSES: ReadonlySet<JobStatus> = new Set<JobStatus>([
  "queued",
  "running",
  "succeeded",
  "failed",
  "blocked",
]);

function safeKind(value: string): JobKind | null {
  return VALID_KINDS.has(value as JobKind) ? (value as JobKind) : null;
}

function safeStatus(value: string): JobStatus | null {
  // The backend also uses "cancelled" — the UI groups that under failed
  // for status-icon rendering since the run history shape only knows
  // about queued/running/succeeded/failed/blocked.
  if (value === "cancelled") return "failed";
  return VALID_STATUSES.has(value as JobStatus) ? (value as JobStatus) : null;
}

/** Map a backend row → the UI's `MsaRtxrtJob`. Returns null if the kind/status are unknown. */
export function rowToJob(row: BackendJobRow): MsaRtxrtJob | null {
  const kind = safeKind(row.kind);
  const status = safeStatus(row.status);
  if (kind === null || status === null) return null;

  // Privacy-safe summary preference: explicit summary > error excerpt
  // (when failed/blocked) > stdout excerpt. Each is server-truncated.
  let summary: string | undefined;
  if (row.summary) summary = row.summary;
  else if (row.error_excerpt && (row.status === "failed" || row.status === "blocked")) {
    summary = row.error_excerpt;
  } else if (row.stdout_excerpt) {
    summary = row.stdout_excerpt;
  }

  return {
    id: row.id,
    kind,
    status,
    createdAt: row.created_at,
    finishedAt: row.finished_at ?? undefined,
    summary,
    runnerId: row.runner_id ?? undefined,
    targetRunnerId: row.target_runner_id ?? undefined,
  };
}

export function rowsToJobs(rows: BackendJobRow[]): MsaRtxrtJob[] {
  const mapped: MsaRtxrtJob[] = [];
  for (const row of rows) {
    const job = rowToJob(row);
    if (job !== null) mapped.push(job);
  }
  return mapped;
}

/** What body to POST to `/api/v1/msa-rtxrt/jobs` for a given kind.
 *
 * Multi-runner targeting: when ``targetRunnerId`` is provided, it's
 * passed through to the backend so only that runner can claim the
 * row. The UI populates this from the selected-runner dropdown on
 * every click. When omitted (or empty), the backend treats the row
 * as any-runner (back-compat for tests + the very first deploy).
 */
export function jobBodyForKind(
  kind: JobKind,
  targetRunnerId?: string | null,
): {
  kind: JobKind;
  confirm_live?: "YES";
  max_test_actions?: 1;
  target_runner_id?: string;
} {
  const cleaned = (targetRunnerId ?? "").trim();
  const targetBody = cleaned ? { target_runner_id: cleaned } : {};
  if (kind.startsWith("live_one_")) {
    // The UI's owner-only two-step Confirm flow is what gates this — the
    // operator never sees the path that produces this body without
    // re-confirming. The server re-checks owner + flags on every call.
    return { kind, confirm_live: "YES", max_test_actions: 1, ...targetBody };
  }
  return { kind, ...targetBody };
}

/** Shape returned by `GET /api/v1/msa-rtxrt/runner/status`. */
export interface BackendRunnerHeartbeat {
  runner_id: string;
  last_seen_at: string;
  seconds_since_seen: number;
  status: "online" | "offline";
  last_status: "idle" | "busy";
  /** Optional in older deploys; back-compat default is ``false``. */
  can_accept_jobs?: boolean;
  /** Optional in older deploys; back-compat default is ``0``. */
  jobs_recently_handled?: number;
}

export interface BackendRunnerStatus {
  runners: BackendRunnerHeartbeat[];
  any_online: boolean;
  freshness_seconds: number;
}

/** Find a runner row by ID, case-insensitively trimming as the API does. */
export function findHeartbeatById(
  heartbeat: BackendRunnerStatus | null,
  runnerId: string | null,
): BackendRunnerHeartbeat | null {
  if (heartbeat === null || runnerId === null) return null;
  const key = runnerId.trim();
  if (!key) return null;
  for (const r of heartbeat.runners) {
    if (r.runner_id === key) return r;
  }
  return null;
}

/**
 * Derive the runner-status badge from BOTH the heartbeat snapshot AND
 * the most-recent job rows. Heartbeat is the source of truth for
 * online/offline; jobs are the source of truth for busy.
 *
 * Multi-runner: when a ``selectedRunnerId`` is passed, we narrow the
 * decision to that runner's heartbeat row, not "any runner online" —
 * because in v2 the UI's run buttons target one specific runner. If
 * the selected runner has no heartbeat row, the pill reads offline
 * (Luis hasn't started his runner yet, etc.).
 *
 *   busy    → any job is currently `running` (irrespective of
 *             which runner — the pill is for the whole bridge)
 *   idle    → selected runner's heartbeat is online (and no job is running),
 *             OR — when no runner selected — any runner online
 *   offline → otherwise
 *
 * When `heartbeat` is null (e.g. the /runner/status endpoint failed,
 * which can happen during deploy windows or transient 5xx), the function
 * falls back to the legacy jobs-only derivation in
 * `deriveRunnerStatusFromJobs` so the UI degrades gracefully rather
 * than locking.
 */
export function deriveRunnerStatus(
  rows: BackendJobRow[],
  heartbeat: BackendRunnerStatus | null = null,
  now: Date = new Date(),
  freshnessMs = 90_000,
  selectedRunnerId: string | null = null,
): RunnerStatus {
  const anyRunning = Array.isArray(rows) && rows.some((r) => r.status === "running");
  if (heartbeat !== null) {
    if (anyRunning) return "busy";
    if (selectedRunnerId !== null && selectedRunnerId.trim() !== "") {
      const row = findHeartbeatById(heartbeat, selectedRunnerId);
      return row !== null && row.status === "online" ? "idle" : "offline";
    }
    return heartbeat.any_online ? "idle" : "offline";
  }
  return deriveRunnerStatusFromJobs(rows, now, freshnessMs);
}

/** Legacy jobs-only derivation. Public for the fallback path + back-compat tests. */
export function deriveRunnerStatusFromJobs(
  rows: BackendJobRow[],
  now: Date = new Date(),
  freshnessMs = 90_000,
): RunnerStatus {
  if (!Array.isArray(rows) || rows.length === 0) return "offline";

  const anyRunning = rows.some((r) => r.status === "running");
  if (anyRunning) return "busy";

  // Find the most recent finished_at timestamp.
  let mostRecentFinish = -Infinity;
  for (const row of rows) {
    if (!row.finished_at) continue;
    const ts = Date.parse(row.finished_at);
    if (!Number.isNaN(ts) && ts > mostRecentFinish) mostRecentFinish = ts;
  }
  if (mostRecentFinish === -Infinity) return "offline";

  const ageMs = now.getTime() - mostRecentFinish;
  return ageMs <= freshnessMs ? "idle" : "offline";
}

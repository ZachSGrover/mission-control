"use client";

// MSA RT/X Automation Bot — Mission Control control panel.
//
// Architecture (Mission Control split):
//   1. This UI is the control panel. It NEVER drives AdsPower, Playwright,
//      or browsers directly. It only enqueues jobs.
//   2. A backend job table receives the job. (Not implemented in this PR.)
//   3. A local runner on Zach's Claw computer (tools/local-runners/
//      msa_rtxrt_runner.py) polls the queue, runs the appropriate
//      Python script inside the imported Luis MSA RT/X folder, and
//      writes status back.
//
// Until the backend bridge lands, this panel renders in "Claw runner
// offline" mode. All run buttons are disabled. The component is
// presentational and accepts state via props so the page-level component
// (or future tests) can drive the UI without hitting any network.

import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  ExternalLink,
  Loader2,
  Lock,
  PlayCircle,
  RefreshCw,
  ShieldAlert,
  TerminalSquare,
} from "lucide-react";

// ── Types ────────────────────────────────────────────────────────────────────
//
// The shape mirrors what the (not-yet-implemented) backend job model will
// return. Keep these props small so the panel can be wired up to a query
// later without changing markup.

export type RunnerStatus = "offline" | "idle" | "busy" | "unknown";

export type JobKind =
  | "smoke"
  | "dry_run_blast"
  | "dry_run_dm"
  | "dry_run_repost"
  | "dry_run_builder"
  | "dry_run_scan"
  | "live_one_blast"
  | "live_one_dm"
  | "live_one_repost"
  | "live_one_builder"
  | "live_one_scan";

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "blocked";

export interface MsaRtxrtJob {
  id: string;
  kind: JobKind;
  status: JobStatus;
  createdAt: string;
  finishedAt?: string;
  /** Short, privacy-safe summary line (no fan data, no message bodies). */
  summary?: string;
  /** Runner that actually claimed + ran this job (undefined while queued). */
  runnerId?: string;
  /** Runner the operator targeted at enqueue time (undefined = any runner). */
  targetRunnerId?: string;
}

export interface MsaRtxrtControlPanelProps {
  runnerStatus: RunnerStatus;
  /** Last 10 jobs the runner reported. */
  recentJobs: MsaRtxrtJob[];
  /**
   * True iff the current viewer can run live-one (Operator+). Prior to
   * 2026-05-20 this prop was named ``isOwner`` and meant owner-only;
   * now it's operator+ to match the role-expansion change.
   */
  canRunLiveOne: boolean;
  /**
   * Called when the operator hits a dry-run or live-one button. Returns the
   * server-side promise so the button can render a spinner. Until the
   * backend bridge lands, the page passes a stub that resolves with a
   * "no backend yet" message.
   */
  onSubmitJob: (kind: JobKind) => Promise<void>;
  /** Refresh button calls this (e.g. to re-poll runner status). */
  onRefresh: () => Promise<void> | void;
}

// ── Status badge ─────────────────────────────────────────────────────────────

function RunnerStatusBadge({ status }: { status: RunnerStatus }) {
  const map: Record<
    RunnerStatus,
    { label: string; tone: "ok" | "pending" | "warn" | "muted" }
  > = {
    offline: { label: "Claw runner offline", tone: "warn" },
    idle: { label: "Claw runner online", tone: "ok" },
    busy: { label: "Claw runner busy", tone: "pending" },
    unknown: { label: "Status unknown", tone: "muted" },
  };
  const colors: Record<"ok" | "pending" | "warn" | "muted", string> = {
    ok: "bg-emerald-500",
    pending: "bg-yellow-400 animate-pulse",
    warn: "bg-amber-500",
    muted: "bg-slate-400",
  };
  const { label, tone } = map[status];
  return (
    <span
      className="flex items-center gap-1.5 text-xs"
      style={{ color: "var(--text-muted)" }}
      data-testid="runner-status"
      data-status={status}
    >
      <span className={`inline-block h-2 w-2 rounded-full ${colors[tone]}`} />
      {label}
    </span>
  );
}

// ── Run button ───────────────────────────────────────────────────────────────

function RunButton({
  kind,
  label,
  description,
  tone = "muted",
  disabled,
  busy,
  onClick,
  testId,
  icon: Icon = PlayCircle,
}: {
  kind: JobKind;
  label: string;
  description: string;
  tone?: "muted" | "accent" | "warn";
  disabled?: boolean;
  busy?: boolean;
  onClick: () => void;
  testId: string;
  icon?: React.ElementType;
}) {
  const toneStyles: Record<"muted" | "accent" | "warn", React.CSSProperties> = {
    muted: {
      background: "var(--surface-strong)",
      border: "1px solid var(--border)",
      color: "var(--text-muted)",
    },
    accent: {
      background: "var(--accent-soft)",
      border: "1px solid var(--border)",
      color: "var(--accent-strong)",
    },
    warn: {
      background: "rgba(245, 158, 11, 0.1)",
      border: "1px solid rgba(245, 158, 11, 0.3)",
      color: "rgb(217, 119, 6)",
    },
  };
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || busy}
      data-testid={testId}
      data-kind={kind}
      title={description}
      aria-label={label}
      className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs transition-opacity disabled:opacity-50"
      style={toneStyles[tone]}
    >
      {busy ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" />
      ) : (
        <Icon className="h-3.5 w-3.5 shrink-0" />
      )}
      <span className="truncate text-left">{label}</span>
    </button>
  );
}

// ── Recent jobs list ─────────────────────────────────────────────────────────

function statusIcon(s: JobStatus) {
  switch (s) {
    case "succeeded":
      return <CheckCircle2 className="h-3.5 w-3.5" />;
    case "running":
      return <Loader2 className="h-3.5 w-3.5 animate-spin" />;
    case "queued":
      return <CircleDashed className="h-3.5 w-3.5" />;
    case "failed":
      return <AlertTriangle className="h-3.5 w-3.5" />;
    case "blocked":
      return <Lock className="h-3.5 w-3.5" />;
  }
}

function RecentJobsBlock({ jobs }: { jobs: MsaRtxrtJob[] }) {
  if (jobs.length === 0) {
    return (
      <p
        className="text-xs italic"
        style={{ color: "var(--text-quiet)" }}
        data-testid="run-history-empty"
      >
        No runs yet. Start with a Smoke test once the Claw runner is online.
      </p>
    );
  }
  return (
    <ul
      className="space-y-1.5"
      data-testid="run-history-list"
    >
      {jobs.map((job) => (
        <li
          key={job.id}
          className="flex items-start gap-2 rounded-md px-2.5 py-1.5 text-[11px]"
          style={{
            background: "var(--surface-strong)",
            border: "1px solid var(--border)",
            color: "var(--text-muted)",
          }}
          data-testid={`job-${job.id}`}
        >
          <span className="mt-0.5 shrink-0">{statusIcon(job.status)}</span>
          <div className="min-w-0 flex-1">
            <p className="font-mono text-[10px] truncate" style={{ color: "var(--text)" }}>
              {job.kind} · {job.status}
            </p>
            <p className="text-[10px]" style={{ color: "var(--text-quiet)" }}>
              {new Date(job.createdAt).toLocaleString()}
            </p>
            {job.summary && (
              <p className="mt-0.5 text-[10px] leading-snug">{job.summary}</p>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

// ── Main panel ───────────────────────────────────────────────────────────────

export function MsaRtxrtControlPanel({
  runnerStatus,
  recentJobs,
  canRunLiveOne,
  onSubmitJob,
  onRefresh,
}: MsaRtxrtControlPanelProps) {
  const [busyKind, setBusyKind] = useState<JobKind | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [liveOneArmed, setLiveOneArmed] = useState(false);
  const [liveOneKind, setLiveOneKind] = useState<JobKind | null>(null);

  const offline = runnerStatus === "offline" || runnerStatus === "unknown";
  const runnerHard = offline;

  const handleSubmit = async (kind: JobKind) => {
    if (busyKind) return;
    setBusyKind(kind);
    try {
      await onSubmitJob(kind);
    } finally {
      setBusyKind(null);
    }
  };

  const handleRefresh = async () => {
    if (refreshing) return;
    setRefreshing(true);
    try {
      await Promise.resolve(onRefresh());
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div className="space-y-6" data-testid="msa-rtxrt-panel">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold" style={{ color: "var(--text)" }}>
            MSA RT/X Automation Bot
          </h2>
          <p className="mt-1 text-sm" style={{ color: "var(--text-muted)" }}>
            Mission Control is the control panel. The Python automation runs on
            Zach&apos;s Claw computer via the local runner.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <RunnerStatusBadge status={runnerStatus} />
          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshing}
            className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs disabled:opacity-50"
            style={{
              background: "var(--surface-strong)",
              border: "1px solid var(--border)",
              color: "var(--text-muted)",
            }}
            data-testid="refresh-button"
          >
            {refreshing ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            Refresh
          </button>
        </div>
      </div>

      {/* Runner offline notice */}
      {offline && (
        <div
          className="rounded-xl p-4 text-sm"
          style={{
            background: "rgba(245, 158, 11, 0.1)",
            border: "1px solid rgba(245, 158, 11, 0.3)",
            color: "rgb(180, 83, 9)",
          }}
          data-testid="runner-offline-notice"
        >
          <p className="font-medium">
            The MSA RT/X local runner is not connected.
          </p>
          <p className="mt-1 text-xs leading-relaxed">
            All run buttons stay disabled until the runner is started on the
            Claw computer. The runner script is at{" "}
            <code className="font-mono">tools/local-runners/msa_rtxrt_runner.py</code>{" "}
            in the repo.
          </p>
        </div>
      )}

      {/* Configuration block */}
      <section
        className="rounded-xl p-4"
        style={{
          background: "var(--surface-strong)",
          border: "1px solid var(--border)",
        }}
        data-testid="configuration-block"
      >
        <h3
          className="text-xs font-semibold uppercase tracking-widest"
          style={{ color: "var(--text-quiet)" }}
        >
          Configuration
        </h3>
        <dl className="mt-3 grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
          <ConfigRow
            label="Source branch"
            value="coo/import-luis-msa"
            mono
          />
          <ConfigRow
            label="Runtime folder"
            value="incoming/luis-msa-import/MSA/Monthly revenue/Automation [RTxRT]"
            mono
          />
          <ConfigRow label="Runtime host" value="Claw computer (local)" />
          <ConfigRow label="Default mode" value="DRY_RUN=true" mono />
          <ConfigRow
            label="Live mode"
            value="ALLOW_LIVE_EXTERNAL_ACTIONS=false (locked)"
            mono
          />
          <ConfigRow
            label="Live-one gate"
            value="CONFIRM_LIVE_TEST=YES · MAX_TEST_ACTIONS=1 · owner only"
          />
        </dl>
      </section>

      {/* Smoke test */}
      <section className="space-y-2">
        <h3
          className="text-xs font-semibold uppercase tracking-widest"
          style={{ color: "var(--text-quiet)" }}
        >
          Smoke test
        </h3>
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          Confirms the runner can reach the bot folder, env, and Python deps.
          Never connects to any external platform.
        </p>
        <RunButton
          kind="smoke"
          label="Run smoke test"
          description="Verify runner ↔ bot wiring without touching external services."
          tone="accent"
          icon={TerminalSquare}
          disabled={runnerHard}
          busy={busyKind === "smoke"}
          onClick={() => void handleSubmit("smoke")}
          testId="run-smoke"
        />
      </section>

      {/* Dry-run controls */}
      <section className="space-y-2">
        <h3
          className="text-xs font-semibold uppercase tracking-widest"
          style={{ color: "var(--text-quiet)" }}
        >
          Dry-run actions (no external sends)
        </h3>
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          Each runs the bot in dry-run mode. No DMs sent, no posts, no scrapes,
          no logins — outputs go to stdout / local logs.
        </p>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {DRY_RUN_BUTTONS.map((b) => (
            <RunButton
              key={b.kind}
              kind={b.kind}
              label={b.label}
              description={b.description}
              tone="muted"
              disabled={runnerHard}
              busy={busyKind === b.kind}
              onClick={() => void handleSubmit(b.kind)}
              testId={`run-${b.kind}`}
            />
          ))}
        </div>
      </section>

      {/* Live-one controls (owner only, two-step confirmation) */}
      <section
        className="rounded-xl p-4"
        style={{
          background: "rgba(239, 68, 68, 0.08)",
          border: "1px solid rgba(239, 68, 68, 0.25)",
        }}
      >
        <div className="flex items-start gap-2">
          <ShieldAlert
            className="mt-0.5 h-4 w-4 shrink-0"
            style={{ color: "rgb(220, 38, 38)" }}
          />
          <div className="flex-1">
            <h3
              className="text-xs font-semibold uppercase tracking-widest"
              style={{ color: "rgb(185, 28, 28)" }}
            >
              Live-one test (Operator/Admin)
            </h3>
            <p
              className="mt-1 text-xs leading-relaxed"
              style={{ color: "var(--text-muted)" }}
            >
              Runs a single live action (MAX_TEST_ACTIONS=1) against the
              chosen surface. Requires Operator (or higher) role,
              explicit two-step confirmation, and the runner&apos;s
              live-mode environment.
            </p>

            {!canRunLiveOne ? (
              <p
                className="mt-3 text-xs italic"
                style={{ color: "var(--text-quiet)" }}
                data-testid="live-one-locked-insufficient-role"
              >
                Operator/Admin access required to use live-one.
              </p>
            ) : !liveOneArmed ? (
              <button
                type="button"
                onClick={() => setLiveOneArmed(true)}
                disabled={runnerHard}
                className="mt-3 inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs disabled:opacity-50"
                style={{
                  background: "rgba(239, 68, 68, 0.15)",
                  border: "1px solid rgba(239, 68, 68, 0.4)",
                  color: "rgb(185, 28, 28)",
                }}
                data-testid="live-one-arm"
              >
                <Lock className="h-3.5 w-3.5" />
                Arm live-one
              </button>
            ) : (
              <div
                className="mt-3 space-y-2"
                data-testid="live-one-confirm-block"
              >
                <select
                  value={liveOneKind ?? ""}
                  onChange={(e) =>
                    setLiveOneKind(
                      (e.target.value || null) as JobKind | null,
                    )
                  }
                  className="w-full rounded-md px-2 py-1 text-xs"
                  style={{
                    background: "var(--surface)",
                    border: "1px solid var(--border)",
                    color: "var(--text)",
                  }}
                  data-testid="live-one-kind-select"
                >
                  <option value="">Choose action…</option>
                  {LIVE_ONE_BUTTONS.map((b) => (
                    <option key={b.kind} value={b.kind}>
                      {b.label}
                    </option>
                  ))}
                </select>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      if (!liveOneKind) return;
                      void handleSubmit(liveOneKind);
                      setLiveOneArmed(false);
                      setLiveOneKind(null);
                    }}
                    disabled={!liveOneKind || runnerHard || busyKind !== null}
                    className="flex-1 rounded-md px-3 py-1.5 text-xs disabled:opacity-50"
                    style={{
                      background: "rgb(220, 38, 38)",
                      color: "white",
                    }}
                    data-testid="live-one-confirm"
                  >
                    Confirm live-one
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setLiveOneArmed(false);
                      setLiveOneKind(null);
                    }}
                    className="rounded-md px-3 py-1.5 text-xs"
                    style={{
                      background: "var(--surface-strong)",
                      border: "1px solid var(--border)",
                      color: "var(--text-muted)",
                    }}
                    data-testid="live-one-cancel"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* Run history */}
      <section className="space-y-2">
        <h3
          className="text-xs font-semibold uppercase tracking-widest"
          style={{ color: "var(--text-quiet)" }}
        >
          Run history
        </h3>
        <RecentJobsBlock jobs={recentJobs} />
      </section>

      {/* Footer note */}
      <p
        className="text-[11px] leading-relaxed"
        style={{ color: "var(--text-quiet)" }}
      >
        <span className="inline-flex items-center gap-1">
          <ExternalLink className="h-3 w-3" />
          The Claw runner script lives at{" "}
          <code className="font-mono">tools/local-runners/msa_rtxrt_runner.py</code>.
        </span>
      </p>
    </div>
  );
}

// ── Small helpers ────────────────────────────────────────────────────────────

function ConfigRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <dt
        className="text-[10px] font-semibold uppercase tracking-widest"
        style={{ color: "var(--text-quiet)" }}
      >
        {label}
      </dt>
      <dd
        className={`mt-0.5 text-xs ${mono ? "font-mono" : ""}`}
        style={{ color: "var(--text)" }}
      >
        {value}
      </dd>
    </div>
  );
}

const DRY_RUN_BUTTONS: { kind: JobKind; label: string; description: string }[] = [
  {
    kind: "dry_run_blast",
    label: "Dry-run blast",
    description: "Run blast_bot.py with DRY_RUN=true. No live DMs.",
  },
  {
    kind: "dry_run_dm",
    label: "Dry-run DM",
    description: "Run dm_bot.py with DRY_RUN=true. No live DMs.",
  },
  {
    kind: "dry_run_repost",
    label: "Dry-run repost",
    description: "Run repost_bot.py with DRY_RUN=true. No live reposts.",
  },
  {
    kind: "dry_run_builder",
    label: "Dry-run builder",
    description: "Run builder_bot.py with DRY_RUN=true. No live actions.",
  },
  {
    kind: "dry_run_scan",
    label: "Dry-run scan",
    description: "Run scan_test.py with DRY_RUN=true. No external requests.",
  },
];

const LIVE_ONE_BUTTONS: { kind: JobKind; label: string }[] = [
  { kind: "live_one_blast", label: "Live-one blast (1 action)" },
  { kind: "live_one_dm", label: "Live-one DM (1 action)" },
  { kind: "live_one_repost", label: "Live-one repost (1 action)" },
  { kind: "live_one_builder", label: "Live-one builder (1 action)" },
  { kind: "live_one_scan", label: "Live-one scan (1 action)" },
];

"use client";

// MSA RT/X Automation Bot — purple-themed parity dashboard.
//
// Mirrors the panel structure of Luis's three working local dashboards
// (xdashboard.html, blast_dashboard.html, models-dashboard.html) without
// copying any of their HTML. The actual creator data + per-account stats
// stay on the Claw computer; this surface only renders what the backend
// bridge already exposes via /api/v1/msa-rtxrt/jobs.
//
// Anything live (account chats, recipient databases, follower lists)
// renders as an info card with a deep link to the Claw-local dashboard at
// http://localhost:8765/xdashboard rather than pretending to host it.
//
// Hard rules carried over from MsaRtxrtControlPanel:
//   - All dry-run + smoke controls are disabled when the runner is offline.
//   - Live-one is owner-only with a two-step Arm → Confirm flow.
//   - No mass-live buttons. The kind catalog is hard-coded; you cannot
//     submit any string that contains live_all / live_mass / live_batch.

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  CircleDashed,
  ExternalLink,
  Hammer,
  Inbox,
  Layers,
  Loader2,
  Lock,
  MessageSquare,
  PlayCircle,
  RefreshCw,
  Repeat,
  Settings,
  ShieldAlert,
  ShieldCheck,
  Signal,
  TerminalSquare,
  Users,
} from "lucide-react";

import { CopyButton } from "@/components/hermes/CopyButton";

import type { BackendRunnerHeartbeat } from "./MsaRtxrtClient";
import type {
  JobKind,
  JobStatus,
  MsaRtxrtJob,
  RunnerStatus,
} from "./MsaRtxrtControlPanel";

// ── Props ───────────────────────────────────────────────────────────────────
//
// Same data shape as the existing MsaRtxrtControlPanel — this lets the page
// drop one in for the other without changing the page-level data fetch.
//
// Multi-runner additions (v2):
//   - ``runners`` is the heartbeat snapshot from /api/v1/msa-rtxrt/runner/status
//     so the selector knows which IDs to render + each one's online state.
//   - ``selectedRunnerId`` + ``onSelectRunner`` drive the dropdown.
//   - ``onSubmitJob`` receives the target runner the operator chose so
//     the POST body carries it through.

export interface MsaRtxrtDashboardProps {
  runnerStatus: RunnerStatus;
  recentJobs: MsaRtxrtJob[];
  /**
   * Whether the viewer can run / arm / confirm a controlled live-one
   * job. Operator+ (owner or operator). Prior to 2026-05-20 this was
   * named ``isOwner`` and equaled ``realRole === "owner"`` — that was
   * too restrictive for the day-to-day bot operator (Luis), who runs
   * the bot from Mission Control. Builders / viewers still cannot
   * run live-one (the backend enforces this via ``OPERATOR_DEP``).
   */
  canRunLiveOne: boolean;
  /** Heartbeat snapshot — drives the runner selector. May be empty list. */
  runners?: BackendRunnerHeartbeat[];
  /** Currently selected runner id, or ``null`` if the operator hasn't picked one. */
  selectedRunnerId?: string | null;
  /** Operator picks a runner from the selector. */
  onSelectRunner?: (runnerId: string | null) => void;
  onSubmitJob: (kind: JobKind, targetRunnerId: string | null) => Promise<void>;
  onRefresh: () => Promise<void> | void;
}

// ── Public constants ────────────────────────────────────────────────────────

/** Local dashboard URL that only resolves on the Claw computer running the
 *  bot folder. We surface it as a link + copy button — the URL itself is
 *  not sensitive (it's loopback), but it only works on the runner host. */
export const LOCAL_DASHBOARD_URL = "http://localhost:8765/xdashboard";

/** Latest safe Luis-bot commit. Surfaced read-only as a reference. */
export const LUIS_BOT_REFERENCE_COMMIT = "5f77dfeb";

/** Source branch where the actual bot code lives (not on main). */
export const LUIS_BOT_SOURCE_BRANCH = "coo/import-luis-msa";

// ── Tab catalog ─────────────────────────────────────────────────────────────

type TabId =
  | "all-chats"
  | "recipient-database"
  | "new-database"
  | "promo-repost"
  | "runner-status"
  | "run-history"
  | "setup";

interface TabDef {
  id: TabId;
  label: string;
  Icon: React.ElementType;
}

const TABS: TabDef[] = [
  { id: "all-chats", label: "All Chats", Icon: MessageSquare },
  { id: "recipient-database", label: "Recipient Database", Icon: Inbox },
  { id: "new-database", label: "New Database", Icon: Layers },
  { id: "promo-repost", label: "Promo Repost", Icon: Repeat },
  { id: "runner-status", label: "Runner Status", Icon: Signal },
  { id: "run-history", label: "Run History", Icon: CircleDashed },
  { id: "setup", label: "Setup", Icon: Settings },
];

// ── Theme tokens ────────────────────────────────────────────────────────────
//
// Luis's dashboard is on a deep-purple gradient palette. We mirror it via
// inline style — Mission Control's global CSS vars stay untouched.

const THEME = {
  bg: "#0f0f1a",
  topBar: "linear-gradient(135deg,#1a0a2e 0%,#2d1b4e 100%)",
  topBarBorder: "#3d2a6e",
  sidebarBg: "#0c0918",
  sidebarBorder: "#2d1b4e",
  cardBg: "#1a1030",
  cardBorder: "#2d1b4e",
  cardSoftBg: "#0f0a1e",
  text: "#e2e8f0",
  textSoft: "#a78bfa",
  textMuted: "#c4b5fd",
  textQuiet: "#7c6aa6",
  accentFrom: "#7c3aed",
  accentTo: "#db2777",
  ok: "#86efac",
  okBg: "#0a1f12",
  okBorder: "#14532d",
  warn: "#fbbf24",
  err: "#fca5a5",
  errBg: "#1a0010",
  errBorder: "#7f1d1d",
} as const;

// ── Account rail ────────────────────────────────────────────────────────────
//
// We do NOT have an account-list endpoint in the bridge — and that data
// shouldn't leave the Claw computer anyway (it would include real X / OF
// handles tied to creators). Instead, we group recent jobs by `runner_id`
// to surface a privacy-safe "which runners are working" rail. If there's
// no signal at all (zero recent jobs), the rail explains why and points
// at the local dashboard.

interface RunnerLane {
  runnerId: string;
  jobCount: number;
  lastSeen: string | undefined;
}

function deriveRunnerLanes(jobs: MsaRtxrtJob[]): RunnerLane[] {
  // The shared MsaRtxrtJob shape doesn't carry runner_id (the backend row
  // has it, but the UI's typed shape doesn't expose it). We expose runner
  // ids only when the row is shape-extended — here we simply group by the
  // job kind to give Luis something familiar in the rail without
  // inventing data we don't have.
  if (jobs.length === 0) return [];
  const byKind = new Map<string, RunnerLane>();
  for (const job of jobs) {
    const key = job.kind;
    const existing = byKind.get(key);
    if (existing) {
      existing.jobCount += 1;
      if (job.createdAt > (existing.lastSeen ?? "")) {
        existing.lastSeen = job.createdAt;
      }
    } else {
      byKind.set(key, {
        runnerId: key,
        jobCount: 1,
        lastSeen: job.createdAt,
      });
    }
  }
  return Array.from(byKind.values()).sort((a, b) => b.jobCount - a.jobCount);
}

function AccountRail({
  lanes,
  selectedId,
  onSelect,
}: {
  lanes: RunnerLane[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}) {
  return (
    <aside
      className="hidden md:flex md:flex-col"
      style={{
        width: 280,
        flexShrink: 0,
        background: THEME.sidebarBg,
        borderRight: `1px solid ${THEME.sidebarBorder}`,
        maxHeight: "calc(100vh - 4rem)",
        overflowY: "auto",
      }}
      data-testid="account-rail"
    >
      <div
        className="flex items-center justify-between px-3 py-4"
        style={{ borderBottom: `1px solid ${THEME.sidebarBorder}` }}
      >
        <span
          className="text-[10px] font-bold uppercase tracking-widest"
          style={{ color: THEME.textSoft }}
        >
          Runners
        </span>
        <span
          className="rounded-full px-2.5 py-1 text-xs font-bold"
          style={{
            color: THEME.ok,
            background: THEME.okBg,
            border: `1px solid ${THEME.okBorder}`,
            fontVariantNumeric: "tabular-nums",
          }}
          data-testid="account-rail-count"
        >
          {lanes.reduce((acc, l) => acc + l.jobCount, 0)}
        </span>
      </div>

      <div className="flex flex-col gap-2 px-3 py-3">
        {lanes.length === 0 ? (
          <div
            className="rounded-lg p-3 text-xs leading-relaxed"
            style={{
              background: THEME.cardSoftBg,
              border: `1px solid ${THEME.cardBorder}`,
              color: THEME.textQuiet,
            }}
            data-testid="account-rail-empty"
          >
            No runner activity yet. Real account data lives on the Claw
            computer — open the local dashboard from the Setup tab to see
            the full creator list with stats.
          </div>
        ) : (
          lanes.map((lane) => {
            const selected = selectedId === lane.runnerId;
            return (
              <button
                key={lane.runnerId}
                type="button"
                onClick={() =>
                  onSelect(selected ? null : lane.runnerId)
                }
                data-testid={`runner-lane-${lane.runnerId}`}
                className="flex items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors"
                style={{
                  background: selected ? "#160d2c" : "#11091f",
                  border: `1px solid ${selected ? THEME.accentFrom : THEME.sidebarBorder}`,
                }}
              >
                <div
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-bold"
                  style={{
                    background: `linear-gradient(135deg,${THEME.accentFrom},${THEME.accentTo})`,
                    color: "#fff",
                  }}
                  aria-hidden
                >
                  {lane.runnerId.charAt(0).toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <p
                    className="truncate text-sm font-semibold"
                    style={{ color: THEME.text }}
                  >
                    {lane.runnerId}
                  </p>
                  <p
                    className="font-mono text-[10px]"
                    style={{ color: THEME.textQuiet }}
                  >
                    {lane.lastSeen
                      ? `last ${new Date(lane.lastSeen).toLocaleString()}`
                      : "no runs"}
                  </p>
                </div>
                <span
                  className="rounded-full px-2.5 py-0.5 text-xs font-bold"
                  style={{
                    color: lane.jobCount > 0 ? THEME.ok : THEME.textQuiet,
                    background: lane.jobCount > 0 ? THEME.okBg : THEME.cardSoftBg,
                    border: `1px solid ${lane.jobCount > 0 ? THEME.okBorder : THEME.cardBorder}`,
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {lane.jobCount}
                </span>
              </button>
            );
          })
        )}
      </div>
    </aside>
  );
}

// ── Runner selector (multi-runner v2) ───────────────────────────────────────
//
// Renders a small dropdown of every runner the backend's heartbeat
// snapshot knows about, plus the "no runner picked" sentinel. The dashboard
// uses this to decide which runner each Submit Job goes to.
//
// The selector is intentionally tiny and self-contained — it only takes
// the heartbeat list + selection state. It does NOT itself fetch
// (the page-level component does that, then passes the data down).

interface RunnerSelectorProps {
  runners: BackendRunnerHeartbeat[];
  selectedRunnerId: string | null;
  onSelect: (runnerId: string | null) => void;
}

function RunnerSelector({
  runners,
  selectedRunnerId,
  onSelect,
}: RunnerSelectorProps) {
  const value = selectedRunnerId ?? "";
  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const next = e.target.value;
    onSelect(next === "" ? null : next);
  };
  // Friendly label per row: "claw-1 · online · idle" or "luis-pc-1 · offline".
  const labelFor = (r: BackendRunnerHeartbeat) => {
    if (r.status === "online") {
      return `${r.runner_id} · online · ${r.last_status}`;
    }
    return `${r.runner_id} · offline`;
  };
  return (
    <label
      className="inline-flex items-center gap-2 rounded-md px-2 py-1 text-xs"
      style={{
        background: THEME.cardBg,
        border: `1px solid ${THEME.cardBorder}`,
        color: THEME.textMuted,
      }}
      data-testid="runner-selector-wrap"
    >
      <span style={{ color: THEME.textSoft }}>Runner:</span>
      <select
        value={value}
        onChange={handleChange}
        data-testid="runner-selector"
        className="bg-transparent outline-none"
        style={{ color: THEME.text, minWidth: 160 }}
        aria-label="Target runner for new jobs"
      >
        <option value="">— pick a runner —</option>
        {runners.map((r) => (
          <option
            key={r.runner_id}
            value={r.runner_id}
            data-testid={`runner-option-${r.runner_id}`}
          >
            {labelFor(r)}
          </option>
        ))}
      </select>
    </label>
  );
}

// ── Status pill ─────────────────────────────────────────────────────────────

function RunnerStatusPill({ status }: { status: RunnerStatus }) {
  const map: Record<
    RunnerStatus,
    { label: string; color: string; pulse: boolean }
  > = {
    offline: { label: "Runner offline", color: THEME.warn, pulse: false },
    idle: { label: "Runner online", color: "#22c55e", pulse: false },
    busy: { label: "Runner busy", color: THEME.warn, pulse: true },
    unknown: { label: "Status unknown", color: THEME.textQuiet, pulse: false },
  };
  const { label, color, pulse } = map[status];
  return (
    <span
      className="inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold"
      style={{
        background: THEME.cardSoftBg,
        border: `1px solid ${THEME.cardBorder}`,
        color: THEME.textMuted,
      }}
      data-testid="dashboard-runner-status"
      data-status={status}
    >
      <span
        className="inline-block h-2.5 w-2.5 rounded-full"
        style={{
          background: color,
          boxShadow: `0 0 8px ${color}88`,
          animation: pulse ? "pulse 1.4s infinite" : undefined,
        }}
      />
      {label}
    </span>
  );
}

// ── Run button ──────────────────────────────────────────────────────────────

function RunButton({
  kind,
  label,
  description,
  disabled,
  busy,
  onClick,
  testId,
  icon: Icon = PlayCircle,
}: {
  kind: JobKind;
  label: string;
  description: string;
  disabled?: boolean;
  busy?: boolean;
  onClick: () => void;
  testId: string;
  icon?: React.ElementType;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || busy}
      data-testid={testId}
      data-kind={kind}
      title={description}
      aria-label={label}
      className="inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition-opacity disabled:opacity-50"
      style={{
        background: `linear-gradient(135deg,${THEME.accentFrom},${THEME.accentTo})`,
        color: "#fff",
        boxShadow: `0 2px 12px ${THEME.accentFrom}44`,
      }}
    >
      {busy ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : (
        <Icon className="h-4 w-4" />
      )}
      {label}
    </button>
  );
}

// ── Numbered card (mirrors Luis's "card h2 .num" pattern) ──────────────────

function NumberedCard({
  n,
  title,
  children,
}: {
  n: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section
      className="rounded-xl p-5 mb-4"
      style={{
        background: THEME.cardBg,
        border: `1px solid ${THEME.cardBorder}`,
      }}
    >
      <h3
        className="mb-3 flex items-center gap-2 text-sm font-bold"
        style={{ color: THEME.textMuted }}
      >
        <span
          className="inline-flex h-6 w-6 items-center justify-center rounded-full text-xs"
          style={{
            background: THEME.accentFrom,
            color: "#fff",
          }}
        >
          {n}
        </span>
        {title}
      </h3>
      {children}
    </section>
  );
}

function HintBox({
  icon: Icon,
  children,
}: {
  icon: React.ElementType;
  children: React.ReactNode;
}) {
  return (
    <div
      className="mb-4 flex items-start gap-3 rounded-lg p-3 text-xs leading-relaxed"
      style={{
        background: "#1a0a2e",
        border: `1px solid ${THEME.topBarBorder}`,
        color: "#9ca3af",
      }}
    >
      <Icon
        className="mt-0.5 h-4 w-4 shrink-0"
        style={{ color: THEME.textSoft }}
      />
      <div>{children}</div>
    </div>
  );
}

// ── Tab body: bot-action panes (All Chats / Recipient / New / Promo) ───────

interface BotActionTabProps {
  intro: string;
  hint: string;
  primaryKind: JobKind;
  primaryLabel: string;
  primaryIcon: React.ElementType;
  runnerOffline: boolean;
  /** True iff the operator has not picked a runner from the selector. */
  noRunnerSelected: boolean;
  /** True iff the selected runner's heartbeat says offline. */
  selectedRunnerOffline: boolean;
  busyKind: JobKind | null;
  onRun: (kind: JobKind) => void;
  testIdPrefix: string;
}

function BotActionTab({
  intro,
  hint,
  primaryKind,
  primaryLabel,
  primaryIcon,
  runnerOffline,
  noRunnerSelected,
  selectedRunnerOffline,
  busyKind,
  onRun,
  testIdPrefix,
}: BotActionTabProps) {
  const disabled = runnerOffline || noRunnerSelected || selectedRunnerOffline;
  const disabledReason = noRunnerSelected
    ? "Pick a runner from the selector above before enqueuing a job."
    : selectedRunnerOffline
      ? "The selected runner is offline — start its local runner before enqueuing a job."
      : null;
  return (
    <div data-testid={`tab-pane-${testIdPrefix}`}>
      <HintBox icon={Inbox}>{hint}</HintBox>

      <NumberedCard n={1} title="What this does">
        <p
          className="text-sm leading-relaxed"
          style={{ color: THEME.text }}
        >
          {intro}
        </p>
        <p
          className="mt-3 text-xs leading-relaxed"
          style={{ color: THEME.textQuiet }}
        >
          Real account data, recipient lists, and follower handles stay on the
          Claw computer. Mission Control only enqueues the run and shows the
          summary — the local dashboard at{" "}
          <code style={{ color: THEME.textSoft }}>
            {LOCAL_DASHBOARD_URL}
          </code>{" "}
          is where you pick accounts and review per-recipient progress.
        </p>
      </NumberedCard>

      <NumberedCard n={2} title="Dry-run from Mission Control">
        <p
          className="mb-3 text-xs"
          style={{ color: THEME.textQuiet }}
        >
          Runs the matching bot script with{" "}
          <code style={{ color: THEME.textSoft }}>DRY_RUN=true</code>. No DMs
          sent, no posts, no scrapes — output goes to local logs and a
          privacy-safe summary lands in the run history.
        </p>
        <RunButton
          kind={primaryKind}
          label={primaryLabel}
          description={`Enqueue ${primaryKind} for the selected runner.`}
          disabled={disabled}
          busy={busyKind === primaryKind}
          onClick={() => onRun(primaryKind)}
          testId={`run-${primaryKind}`}
          icon={primaryIcon}
        />
        {disabledReason && (
          <p
            className="mt-2 text-[11px] leading-relaxed"
            style={{ color: THEME.warn }}
            data-testid={`tab-pane-${testIdPrefix}-disabled-reason`}
          >
            {disabledReason}
          </p>
        )}
      </NumberedCard>
    </div>
  );
}

// ── Tab body: Runner Status ────────────────────────────────────────────────

function RunnerStatusTab({
  runnerStatus,
  busyKind,
  onRun,
  runners,
  selectedRunnerId,
  noRunnerSelected,
  selectedRunnerOffline,
}: {
  runnerStatus: RunnerStatus;
  busyKind: JobKind | null;
  onRun: (kind: JobKind) => void;
  runners: BackendRunnerHeartbeat[];
  selectedRunnerId: string | null;
  noRunnerSelected: boolean;
  selectedRunnerOffline: boolean;
}) {
  const offline = runnerStatus === "offline" || runnerStatus === "unknown";
  const disabled = offline || noRunnerSelected || selectedRunnerOffline;
  return (
    <div data-testid="tab-pane-runner-status">
      <HintBox icon={Signal}>
        Mission Control is the control panel. The Python automation runs on
        the Claw computer via{" "}
        <code style={{ color: THEME.textSoft }}>
          tools/local-runners/msa_rtxrt_runner.py
        </code>
        . Start it with <code style={{ color: THEME.textSoft }}>--poll</code>{" "}
        on the runner host to connect.
      </HintBox>

      <NumberedCard n={1} title="Status">
        <RunnerStatusPill status={runnerStatus} />
        {offline && (
          <p
            className="mt-3 text-xs leading-relaxed"
            style={{ color: THEME.err }}
          >
            No runner is online. All run buttons stay disabled until at
            least one runner starts polling.
          </p>
        )}
        {!offline && noRunnerSelected && (
          <p
            className="mt-3 text-xs leading-relaxed"
            style={{ color: THEME.warn }}
            data-testid="status-tab-no-runner-warning"
          >
            Pick a runner from the selector in the top bar before
            enqueuing a job.
          </p>
        )}
        {!offline && !noRunnerSelected && selectedRunnerOffline && (
          <p
            className="mt-3 text-xs leading-relaxed"
            style={{ color: THEME.warn }}
            data-testid="status-tab-selected-offline-warning"
          >
            The selected runner ({selectedRunnerId}) is offline. Start
            its local runner before enqueuing a job, or pick a runner
            that&apos;s online.
          </p>
        )}
      </NumberedCard>

      <NumberedCard n={2} title="Connected runners">
        {runners.length === 0 ? (
          <p
            className="text-xs leading-relaxed"
            style={{ color: THEME.textQuiet }}
            data-testid="connected-runners-empty"
          >
            No runners have polled yet. Start a local runner on the Claw
            computer (or Luis&apos;s Windows PC) and refresh this page.
          </p>
        ) : (
          <ul
            className="space-y-1.5"
            data-testid="connected-runners-list"
          >
            {runners.map((r) => (
              <li
                key={r.runner_id}
                className="flex items-center justify-between rounded-md px-3 py-2 font-mono text-xs"
                style={{
                  background: THEME.cardSoftBg,
                  border: `1px solid ${THEME.cardBorder}`,
                  color: THEME.text,
                }}
                data-testid={`connected-runner-${r.runner_id}`}
              >
                <span>
                  <span style={{ color: THEME.textSoft }}>{r.runner_id}</span>
                  {selectedRunnerId === r.runner_id && (
                    <span
                      className="ml-2 rounded-full px-1.5 py-0.5 text-[10px]"
                      style={{
                        background: THEME.accentFrom,
                        color: "#fff",
                      }}
                    >
                      selected
                    </span>
                  )}
                </span>
                <span style={{ color: r.status === "online" ? THEME.ok : THEME.warn }}>
                  {r.status === "online"
                    ? `online · ${r.last_status}`
                    : `offline · ${r.seconds_since_seen}s`}
                </span>
              </li>
            ))}
          </ul>
        )}
      </NumberedCard>

      <NumberedCard n={3} title="Smoke test">
        <p
          className="mb-3 text-xs"
          style={{ color: THEME.textQuiet }}
        >
          Verifies runner ↔ bot wiring on the selected runner without
          touching any external service. Always safe to run.
        </p>
        <RunButton
          kind="smoke"
          label="Run smoke test"
          description="Verify runner ↔ bot wiring."
          disabled={disabled}
          busy={busyKind === "smoke"}
          onClick={() => onRun("smoke")}
          testId="run-smoke"
          icon={TerminalSquare}
        />
      </NumberedCard>

      <NumberedCard n={4} title="Other dry-run actions">
        <div className="flex flex-wrap gap-2">
          {OTHER_DRY_RUN_BUTTONS.map((b) => (
            <RunButton
              key={b.kind}
              kind={b.kind}
              label={b.label}
              description={b.description}
              disabled={disabled}
              busy={busyKind === b.kind}
              onClick={() => onRun(b.kind)}
              testId={`run-${b.kind}`}
              icon={b.icon}
            />
          ))}
        </div>
      </NumberedCard>
    </div>
  );
}

// ── Tab body: Run History ──────────────────────────────────────────────────

const STATUS_ICON: Record<JobStatus, React.ElementType> = {
  queued: CircleDashed,
  running: Loader2,
  succeeded: CheckCircle2,
  failed: AlertTriangle,
  blocked: Lock,
};

function RunHistoryTab({ jobs }: { jobs: MsaRtxrtJob[] }) {
  return (
    <div data-testid="tab-pane-run-history">
      <HintBox icon={CircleDashed}>
        The 10 most recent jobs across all runners. Summaries are
        server-truncated and never include fan handles, DM bodies, AdsPower
        IDs, or any creator-side runtime data.
      </HintBox>

      {jobs.length === 0 ? (
        <NumberedCard n={1} title="No runs yet">
          <p
            className="text-sm leading-relaxed"
            style={{ color: THEME.textQuiet }}
            data-testid="run-history-empty"
          >
            Once the Claw runner picks up a job, rows appear here with their
            final status and a privacy-safe summary.
          </p>
        </NumberedCard>
      ) : (
        <ul
          className="space-y-2"
          data-testid="run-history-list"
        >
          {jobs.map((job) => {
            const Icon = STATUS_ICON[job.status];
            return (
              <li
                key={job.id}
                className="flex items-start gap-3 rounded-lg p-3"
                style={{
                  background: THEME.cardSoftBg,
                  border: `1px solid ${THEME.cardBorder}`,
                }}
                data-testid={`history-row-${job.id}`}
              >
                <Icon
                  className={`mt-0.5 h-4 w-4 shrink-0 ${
                    job.status === "running" ? "animate-spin" : ""
                  }`}
                  style={{
                    color:
                      job.status === "succeeded"
                        ? "#22c55e"
                        : job.status === "failed"
                          ? "#ef4444"
                          : job.status === "blocked"
                            ? THEME.warn
                            : THEME.textSoft,
                  }}
                />
                <div className="min-w-0 flex-1">
                  <p
                    className="font-mono text-xs"
                    style={{ color: THEME.text }}
                  >
                    {job.kind} · {job.status}
                  </p>
                  <p
                    className="text-[11px]"
                    style={{ color: THEME.textQuiet }}
                  >
                    {new Date(job.createdAt).toLocaleString()}
                    {(job.runnerId || job.targetRunnerId) && (
                      <>
                        {" · "}
                        <span
                          data-testid={`history-row-runner-${job.id}`}
                          style={{ color: THEME.textSoft }}
                        >
                          {job.runnerId ??
                            (job.targetRunnerId
                              ? `→ ${job.targetRunnerId}`
                              : "—")}
                        </span>
                      </>
                    )}
                  </p>
                  {job.summary && (
                    <p
                      className="mt-1 text-xs leading-relaxed"
                      style={{ color: THEME.textMuted }}
                    >
                      {job.summary}
                    </p>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// ── Tab body: Setup ─────────────────────────────────────────────────────────

function SetupTab({ canRunLiveOne }: { canRunLiveOne: boolean }) {
  return (
    <div data-testid="tab-pane-setup">
      <HintBox icon={Settings}>
        Configuration the Claw operator must complete before the bridge is
        useful. None of these values live in Mission Control — they all live
        on the Claw computer&apos;s local environment.
      </HintBox>

      <NumberedCard n={1} title="Source code reference (read-only)">
        <dl
          className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2"
          data-testid="setup-source-info"
        >
          <SetupRow
            label="Source branch"
            value={LUIS_BOT_SOURCE_BRANCH}
            mono
          />
          <SetupRow
            label="Latest safe commit"
            value={LUIS_BOT_REFERENCE_COMMIT}
            mono
          />
          <SetupRow
            label="Runtime folder"
            value="incoming/luis-msa-import/MSA/Monthly revenue/Automation [RTxRT]"
            mono
          />
          <SetupRow label="Runtime host" value="Claw computer (local only)" />
        </dl>
      </NumberedCard>

      <NumberedCard n={2} title="Add another runner computer">
        <p
          className="text-xs leading-relaxed"
          style={{ color: THEME.textMuted }}
          data-testid="setup-add-runner-intro"
        >
          MSA RT/X supports multiple runner machines (claw-1, luis-pc-1,
          zach-laptop-1, mac-mini-1, …). Each runs its own local Python
          runner with its own ID, its own bot folder, its own AdsPower
          install, and its own config files. Luis runs on Windows; Zach
          runs on macOS. Mission Control routes jobs to whichever runner
          the operator picks in the top-bar selector.
        </p>
        <ol
          className="mt-3 list-decimal space-y-1.5 pl-5 text-xs leading-relaxed"
          style={{ color: THEME.textMuted }}
          data-testid="setup-add-runner-steps"
        >
          <li>Clone the repo (or copy the runner package) onto the new computer.</li>
          <li>
            Install Python deps:{" "}
            <code style={{ color: THEME.textSoft }}>
              python3 -m pip install --user requests playwright
            </code>
            .
          </li>
          <li>
            Place the bot folder locally (e.g.{" "}
            <code style={{ color: THEME.textSoft }}>
              ~/msa-rtxrt-bot/Automation [RTxRT]
            </code>
            ).
          </li>
          <li>
            Create a local{" "}
            <code style={{ color: THEME.textSoft }}>
              .msa-rtxrt-runner.env
            </code>{" "}
            file with{" "}
            <code style={{ color: THEME.textSoft }}>chmod 600</code>{" "}
            permissions; set <code>MSA_RTXRT_BACKEND_URL</code>,{" "}
            <code>MSA_RTXRT_RUNNER_TOKEN</code> (same token as Render env),{" "}
            <code>MSA_RTXRT_RUNNER_ID</code> (unique per computer:{" "}
            <code>luis-pc-1</code>, <code>zach-laptop-1</code>, …), and{" "}
            <code>MSA_RTXRT_BOT_DIR</code>.
          </li>
          <li>Optional: add ADSPOWER_API_KEY when AdsPower is being used live.</li>
          <li>
            Run preflight first:{" "}
            <code style={{ color: THEME.textSoft }}>
              python3 tools/local-runners/msa_rtxrt_runner.py --preflight
            </code>
            .
          </li>
          <li>
            Start the poll loop:{" "}
            <code style={{ color: THEME.textSoft }}>
              python3 tools/local-runners/msa_rtxrt_runner.py --poll
            </code>
            .
          </li>
          <li>
            Refresh this page — the new runner appears in the top-bar
            selector within 5 seconds.
          </li>
        </ol>
        <p
          className="mt-3 text-[11px] italic"
          style={{ color: THEME.textQuiet }}
        >
          Full guide: <code>docs/operations/msa-rtxrt-multi-runner.md</code>
        </p>
      </NumberedCard>

      <NumberedCard n={3} title="Required env on each runner computer">
        <ul
          className="space-y-2 text-xs"
          style={{ color: THEME.textMuted }}
          data-testid="setup-env-checklist"
        >
          {REQUIRED_ENV_VARS.map((row) => (
            <li
              key={row.name}
              className="flex items-start gap-2 rounded-md p-2"
              style={{
                background: THEME.cardSoftBg,
                border: `1px solid ${THEME.cardBorder}`,
              }}
            >
              <Circle
                className="mt-0.5 h-3 w-3 shrink-0"
                style={{ color: THEME.textSoft }}
              />
              <div>
                <p
                  className="font-mono"
                  style={{ color: THEME.text }}
                >
                  {row.name}
                </p>
                <p
                  className="mt-0.5 leading-relaxed"
                  style={{ color: THEME.textQuiet }}
                >
                  {row.note}
                </p>
              </div>
            </li>
          ))}
        </ul>
      </NumberedCard>

      <NumberedCard n={4} title="Safety posture">
        <ul
          className="space-y-1.5 text-xs leading-relaxed"
          style={{ color: THEME.textMuted }}
          data-testid="setup-safety"
        >
          <li>
            Dry-run is the default. <code>DRY_RUN=true</code>{" "}
            <code>ALLOW_LIVE_EXTERNAL_ACTIONS=false</code>.
          </li>
          <li>
            Live-one runs require <code>CONFIRM_LIVE_TEST=YES</code>{" "}
            <code>MAX_TEST_ACTIONS=1</code> AND the owner role.
          </li>
          <li>
            Mass-live runs are blocked outright in three places: the UI has
            no button, the backend service rejects the kind, and the runner
            refuses to even build the subprocess command.
          </li>
        </ul>
      </NumberedCard>

      <NumberedCard n={5} title="Required external accounts (notice)">
        <ul
          className="space-y-2 text-xs leading-relaxed"
          style={{ color: THEME.textMuted }}
          data-testid="setup-external-notice"
        >
          <li className="flex items-start gap-2">
            <ShieldAlert
              className="mt-0.5 h-3.5 w-3.5 shrink-0"
              style={{ color: THEME.warn }}
            />
            <span>
              <b style={{ color: THEME.warn }}>AdsPower</b> must be running on
              the Claw computer with the target profile open. The runner
              connects to AdsPower&apos;s local API; AdsPower keys NEVER
              leave the Claw machine.
            </span>
          </li>
          <li className="flex items-start gap-2">
            <ShieldAlert
              className="mt-0.5 h-3.5 w-3.5 shrink-0"
              style={{ color: THEME.warn }}
            />
            <span>
              <b style={{ color: THEME.warn }}>X / Twitter profile</b> must be
              logged in inside the chosen AdsPower profile (cookies +
              session). Mission Control does not store or forward those
              session cookies.
            </span>
          </li>
          {canRunLiveOne && (
            <li
              className="flex items-start gap-2"
              data-testid="setup-live-one-notice"
            >
              <ShieldAlert
                className="mt-0.5 h-3.5 w-3.5 shrink-0"
                style={{ color: THEME.err }}
              />
              <span>
                <b style={{ color: THEME.err }}>Live-one</b> requires you to
                set the three local env vars before the runner will execute.
                Even an operator with full UI access cannot bypass the
                runner-side gate.
              </span>
            </li>
          )}
        </ul>
      </NumberedCard>

      <NumberedCard n={6} title="Working local dashboard">
        <p
          className="mb-3 text-xs leading-relaxed"
          style={{ color: THEME.textMuted }}
        >
          The full Luis-built dashboard with per-account chats, recipient
          lists, and follower scrapers runs locally on the Claw computer.
          Mission Control never reaches into it — open the URL below from
          the Claw host&apos;s browser.
        </p>
        <div
          className="flex flex-wrap items-center gap-2 rounded-lg p-3"
          style={{
            background: THEME.cardSoftBg,
            border: `1px solid ${THEME.cardBorder}`,
          }}
          data-testid="local-dashboard-url-block"
        >
          <code
            className="break-all text-xs"
            style={{ color: THEME.textMuted }}
          >
            {LOCAL_DASHBOARD_URL}
          </code>
          <div className="ml-auto flex gap-2">
            <a
              href={LOCAL_DASHBOARD_URL}
              target="_blank"
              rel="noopener noreferrer"
              data-testid="local-dashboard-open"
              className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-semibold"
              style={{
                background: THEME.cardBg,
                border: `1px solid ${THEME.cardBorder}`,
                color: THEME.textSoft,
              }}
            >
              <ExternalLink className="h-3.5 w-3.5" />
              Open Working Dashboard
            </a>
            <CopyButton
              text={LOCAL_DASHBOARD_URL}
              label="Copy URL"
              ariaLabel="Copy local dashboard URL"
            />
          </div>
        </div>
        <p
          className="mt-2 text-[11px] leading-relaxed"
          style={{ color: THEME.textQuiet }}
          data-testid="local-dashboard-note"
        >
          This URL only resolves on the Claw computer. Clicking it from any
          other machine — including from <code>hq.digidle.com</code> on
          another laptop — will not work. That is by design.
        </p>
      </NumberedCard>

      <NumberedCard n={8} title="AdsPower checklist (Claw computer)">
        <ChecklistRow label="AdsPower app running locally" />
        <ChecklistRow label={(<><code>http://local.adspower.net:50325</code> reachable</>) as React.ReactNode} />
        <ChecklistRow label={(<><code>ADSPOWER_API_KEY</code> set in the Claw shell (never committed)</>) as React.ReactNode} />
        <ChecklistRow label="AdsPower profile IDs configured for each X account" />
        <ChecklistRow label="X is logged in on each AdsPower profile" />
        <p
          className="mt-3 text-[11px] leading-relaxed"
          style={{ color: THEME.textQuiet }}
          data-testid="adspower-note"
        >
          The runner exposes <code>python3 tools/local-runners/msa_rtxrt_runner.py
          --check-adspower</code> for a no-side-effects probe of the local
          API. It only hits the user-list endpoint; it never opens a
          profile or touches X.
        </p>
      </NumberedCard>

      <NumberedCard n={9} title="Config files (Claw computer, never committed)">
        <p
          className="text-[12px] leading-relaxed"
          style={{ color: THEME.textSoft }}
        >
          Copy each example to its non-example name in the bot folder
          and fill in. The repo&apos;s exclude rules keep these from
          ever being staged for git.
        </p>
        <div className="mt-3 space-y-2">
          <ChecklistRow label={(<><code>auftrag.json</code> &larr; copied from <code>auftrag.example.json</code></>) as React.ReactNode} />
          <ChecklistRow label={(<><code>contacts.json</code> &larr; copied from <code>contacts.example.json</code></>) as React.ReactNode} />
          <ChecklistRow label={(<><code>blast_auftrag.json</code> if running blast bot</>) as React.ReactNode} />
          <ChecklistRow label={(<><code>repost_auftrag.json</code> if running repost bot</>) as React.ReactNode} />
        </div>
        <HintBox icon={ShieldCheck}>
          Never commit any of these files. They may contain real recipient
          handles, AdsPower profile IDs, and other client data that must
          stay on the Claw computer.
        </HintBox>
      </NumberedCard>

      <NumberedCard n={10} title="Runner control commands (Claw computer)">
        <p
          className="text-[12px] leading-relaxed"
          style={{ color: THEME.textSoft }}
        >
          Copy-paste into a terminal on the Claw computer.
        </p>

        <div className="mt-3 space-y-3">
          <div
            className="rounded-md p-3"
            style={{
              background: THEME.cardBg,
              border: `1px solid ${THEME.cardBorder}`,
            }}
          >
            <div className="flex items-center justify-between gap-2">
              <p
                className="text-[10px] font-semibold uppercase tracking-wider"
                style={{ color: THEME.textQuiet }}
              >
                Start / restart the runner
              </p>
              <CopyButton
                text="cd /Users/zachary/mission-control-postmerge-main && ./.start-msa-rtxrt-runner.sh"
                label="Copy"
                ariaLabel="Copy restart command"
              />
            </div>
            <code
              className="mt-2 block break-all text-[11px]"
              style={{ color: THEME.text }}
              data-testid="restart-command"
            >
              cd /Users/zachary/mission-control-postmerge-main && ./.start-msa-rtxrt-runner.sh
            </code>
          </div>

          <div
            className="rounded-md p-3"
            style={{
              background: THEME.cardBg,
              border: `1px solid ${THEME.cardBorder}`,
            }}
          >
            <div className="flex items-center justify-between gap-2">
              <p
                className="text-[10px] font-semibold uppercase tracking-wider"
                style={{ color: THEME.textQuiet }}
              >
                Stop the runner
              </p>
              <CopyButton
                text='kill "$(cat /Users/zachary/mission-control-postmerge-main/.msa-rtxrt-runner.pid)"'
                label="Copy"
                ariaLabel="Copy stop command"
              />
            </div>
            <code
              className="mt-2 block break-all text-[11px]"
              style={{ color: THEME.text }}
              data-testid="stop-command"
            >
              {'kill "$(cat /Users/zachary/mission-control-postmerge-main/.msa-rtxrt-runner.pid)"'}
            </code>
          </div>

          <div
            className="rounded-md p-3"
            style={{
              background: THEME.cardBg,
              border: `1px solid ${THEME.cardBorder}`,
            }}
          >
            <div className="flex items-center justify-between gap-2">
              <p
                className="text-[10px] font-semibold uppercase tracking-wider"
                style={{ color: THEME.textQuiet }}
              >
                Preflight (no side effects)
              </p>
              <CopyButton
                text="cd /Users/zachary/mission-control-postmerge-main && set -a && . ./.msa-rtxrt-runner.env && set +a && python3 tools/local-runners/msa_rtxrt_runner.py --preflight"
                label="Copy"
                ariaLabel="Copy preflight command"
              />
            </div>
            <code
              className="mt-2 block break-all text-[11px]"
              style={{ color: THEME.text }}
              data-testid="preflight-command"
            >
              ./.msa-rtxrt-runner.env + python3 tools/local-runners/msa_rtxrt_runner.py --preflight
            </code>
          </div>
        </div>
      </NumberedCard>

      <NumberedCard n={11} title="What Luis can do vs what only Zach can do">
        <div className="space-y-3">
          <div>
            <p
              className="text-[10px] font-semibold uppercase tracking-wider"
              style={{ color: THEME.textQuiet }}
            >
              Luis (operator/admin role) — fully operates the bot
            </p>
            <ul
              className="mt-2 list-disc pl-5 space-y-1 text-[12px] leading-relaxed"
              style={{ color: THEME.textSoft }}
              data-testid="luis-can-do"
            >
              <li>Open Mission Control from phone or computer</li>
              <li>Select which runner to target (luis-pc-1, etc.)</li>
              <li>View runner status</li>
              <li>Run smoke test</li>
              <li>Run dry-run actions</li>
              <li>
                <b>Arm and run a controlled live-one</b> (with the three
                safety flags + runner-side env)
              </li>
              <li>See run history</li>
              <li>Edit local configs on his runner machine</li>
              <li>
                Iterate on bot code on feature branches (
                <code>coo/*</code>, <code>feat/*</code>, <code>fix/*</code>
                ) and open PRs
              </li>
            </ul>
          </div>
          <div>
            <p
              className="text-[10px] font-semibold uppercase tracking-wider"
              style={{ color: THEME.textQuiet }}
            >
              Zach / owner only — production + security
            </p>
            <ul
              className="mt-2 list-disc pl-5 space-y-1 text-[12px] leading-relaxed"
              style={{ color: THEME.textSoft }}
              data-testid="owner-only"
            >
              <li>Push directly to <code>main</code> / merge PRs</li>
              <li>Change Render / Vercel / Clerk / DNS / billing</li>
              <li>Change Cloudflare / auth / security policy</li>
              <li>Rotate the runner token</li>
              <li>Assign Mission Control roles to other users</li>
              <li>
                Add a new <code>live_one_*</code> kind or relax the
                safety gate (mass-live remains blocked at four layers)
              </li>
            </ul>
          </div>
          <HintBox icon={ShieldCheck}>
            Mass-live actions do not exist anywhere in the system and are
            blocked at four independent layers (UI, backend validator,
            runner gate, bot&apos;s own safety_guard). Luis can run
            controlled live-one with operator role; the bot still
            refuses unless the three local env vars are set on the
            calling runner machine.
          </HintBox>
        </div>
      </NumberedCard>
    </div>
  );
}

function ChecklistRow({ label }: { label: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2">
      <span
        className="mt-[3px] inline-block h-3 w-3 rounded-sm"
        style={{
          border: `1.5px solid ${THEME.cardBorder}`,
          background: "transparent",
        }}
        aria-hidden="true"
      />
      <span
        className="text-[12px] leading-snug"
        style={{ color: THEME.textSoft }}
      >
        {label}
      </span>
    </div>
  );
}

function SetupRow({
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
        className="text-[10px] font-bold uppercase tracking-widest"
        style={{ color: THEME.textQuiet }}
      >
        {label}
      </dt>
      <dd
        className={`mt-0.5 text-xs ${mono ? "font-mono" : ""} break-all`}
        style={{ color: THEME.text }}
      >
        {value}
      </dd>
    </div>
  );
}

// ── Live-one card (operator+, two-step Arm → Confirm) ─────────────────────
//
// As of 2026-05-20 this is no longer owner-only. Operator+ can arm /
// confirm / run a live-one provided the three safety flags are set and a
// runner is selected. Builders / viewers still cannot — the backend
// enforces this via ``OPERATOR_DEP`` on POST /jobs.

function LiveOneCard({
  canRunLiveOne,
  runnerOffline,
  noRunnerSelected,
  selectedRunnerOffline,
  selectedRunnerId,
  busyKind,
  onRun,
}: {
  canRunLiveOne: boolean;
  runnerOffline: boolean;
  noRunnerSelected: boolean;
  selectedRunnerOffline: boolean;
  selectedRunnerId: string | null;
  busyKind: JobKind | null;
  onRun: (kind: JobKind) => void;
}) {
  const disabled =
    runnerOffline || noRunnerSelected || selectedRunnerOffline;
  const [armed, setArmed] = useState(false);
  const [kind, setKind] = useState<JobKind | "">("");

  return (
    <section
      className="rounded-xl p-5 mt-6"
      style={{
        background: "rgba(239, 68, 68, 0.08)",
        border: "1px solid rgba(239, 68, 68, 0.25)",
      }}
    >
      <div className="flex items-start gap-2">
        <ShieldAlert
          className="mt-0.5 h-4 w-4 shrink-0"
          style={{ color: "#dc2626" }}
        />
        <div className="flex-1">
          <h3
            className="text-xs font-bold uppercase tracking-widest"
            style={{ color: "#b91c1c" }}
          >
            Live-one test (Operator/Admin)
          </h3>
          <p
            className="mt-1 text-xs leading-relaxed"
            style={{ color: THEME.textMuted }}
          >
            Runs a single live action with{" "}
            <code>MAX_TEST_ACTIONS=1</code> on the selected runner.
            Requires Operator (or higher) role, two-step confirmation,
            and the three local env vars set on the runner machine.
          </p>

          {!canRunLiveOne ? (
            <p
              className="mt-3 text-xs italic"
              style={{ color: THEME.textQuiet }}
              data-testid="live-one-locked-insufficient-role"
            >
              Operator/Admin access required.
            </p>
          ) : !armed ? (
            <button
              type="button"
              onClick={() => setArmed(true)}
              disabled={disabled}
              data-testid="live-one-arm"
              className="mt-3 inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs disabled:opacity-50"
              style={{
                background: "rgba(239, 68, 68, 0.15)",
                border: "1px solid rgba(239, 68, 68, 0.4)",
                color: "#b91c1c",
              }}
            >
              <Lock className="h-3.5 w-3.5" />
              Arm live-one
            </button>
          ) : (
            <div
              className="mt-3 space-y-2"
              data-testid="live-one-confirm-block"
            >
              <p
                className="text-[11px]"
                style={{ color: THEME.textQuiet }}
                data-testid="live-one-targeting"
              >
                Targeting runner:{" "}
                <code style={{ color: THEME.textSoft }}>
                  {selectedRunnerId ?? "—"}
                </code>
              </p>
              <select
                value={kind}
                onChange={(e) => setKind(e.target.value as JobKind | "")}
                className="w-full rounded-md px-2 py-1 text-xs"
                style={{
                  background: THEME.cardBg,
                  border: `1px solid ${THEME.cardBorder}`,
                  color: THEME.text,
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
                    if (!kind) return;
                    onRun(kind);
                    setArmed(false);
                    setKind("");
                  }}
                  disabled={!kind || disabled || busyKind !== null}
                  className="flex-1 rounded-md px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
                  style={{
                    background: "#dc2626",
                    color: "#fff",
                  }}
                  data-testid="live-one-confirm"
                >
                  Confirm live-one
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setArmed(false);
                    setKind("");
                  }}
                  className="rounded-md px-3 py-1.5 text-xs"
                  style={{
                    background: THEME.cardBg,
                    border: `1px solid ${THEME.cardBorder}`,
                    color: THEME.textMuted,
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
  );
}

// ── Main dashboard ──────────────────────────────────────────────────────────

export function MsaRtxrtDashboard({
  runnerStatus,
  recentJobs,
  canRunLiveOne,
  runners = [],
  selectedRunnerId = null,
  onSelectRunner,
  onSubmitJob,
  onRefresh,
}: MsaRtxrtDashboardProps) {
  const [activeTab, setActiveTab] = useState<TabId>("all-chats");
  const [selectedLane, setSelectedLane] = useState<string | null>(null);
  const [busyKind, setBusyKind] = useState<JobKind | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  // Internal selection state — used only when the parent doesn't supply
  // ``onSelectRunner``. The page-level component always supplies it;
  // tests that pass ``selectedRunnerId`` directly without an
  // ``onSelectRunner`` callback still get their value respected.
  const [internalSelectedRunner, setInternalSelectedRunner] = useState<
    string | null
  >(selectedRunnerId);
  // The effective selection is:
  //   - the prop value when the parent passes ``onSelectRunner`` (fully
  //     controlled — page level)
  //   - the prop value if it's non-null (controlled snapshot in tests)
  //   - the internal state otherwise
  const effectiveSelected = onSelectRunner
    ? selectedRunnerId
    : selectedRunnerId !== null
      ? selectedRunnerId
      : internalSelectedRunner;
  const setSelected = (next: string | null) => {
    if (onSelectRunner) onSelectRunner(next);
    else setInternalSelectedRunner(next);
  };

  const lanes = useMemo(() => deriveRunnerLanes(recentJobs), [recentJobs]);
  const runnerOffline =
    runnerStatus === "offline" || runnerStatus === "unknown";
  // Multi-runner v2: the run buttons need BOTH a selected runner AND
  // the runner pill to show idle (== online + not currently busy).
  // ``noRunnerSelected`` is exposed to the tab components so they can
  // render a precise reason-for-disable.
  const noRunnerSelected = !effectiveSelected;
  // If the selected runner is offline (per heartbeat list), block the
  // buttons too — otherwise the operator could enqueue a job that never
  // gets claimed.
  const selectedRunnerOffline =
    !!effectiveSelected &&
    runners.length > 0 &&
    !runners.some(
      (r) => r.runner_id === effectiveSelected && r.status === "online",
    );
  const buttonsDisabled =
    runnerOffline || noRunnerSelected || selectedRunnerOffline;

  const handleRun = async (kind: JobKind) => {
    if (busyKind) return;
    if (buttonsDisabled) return;
    setBusyKind(kind);
    try {
      await onSubmitJob(kind, effectiveSelected);
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
    <div
      className="flex flex-1 flex-col"
      style={{ background: THEME.bg, color: THEME.text }}
      data-testid="msa-rtxrt-dashboard"
    >
      {/* Top bar */}
      <header
        className="flex flex-wrap items-center gap-3 px-6 py-3"
        style={{
          background: THEME.topBar,
          borderBottom: `1px solid ${THEME.topBarBorder}`,
        }}
      >
        <h1
          className="text-base font-bold"
          style={{ color: "#e2d9f3" }}
        >
          MSA RT/X Dashboard
        </h1>
        <span
          className="rounded-full px-2 py-0.5 text-[10px] font-bold"
          style={{
            background: THEME.accentFrom,
            color: "#fff",
          }}
        >
          Mission Control bridge
        </span>
        <div className="ml-auto flex items-center gap-2">
          <RunnerSelector
            runners={runners}
            selectedRunnerId={effectiveSelected}
            onSelect={setSelected}
          />
          <RunnerStatusPill status={runnerStatus} />
          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshing}
            data-testid="dashboard-refresh"
            className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs disabled:opacity-50"
            style={{
              background: THEME.cardBg,
              border: `1px solid ${THEME.cardBorder}`,
              color: THEME.textMuted,
            }}
          >
            {refreshing ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            Refresh
          </button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <AccountRail
          lanes={lanes}
          selectedId={selectedLane}
          onSelect={setSelectedLane}
        />

        <main className="flex-1 overflow-y-auto px-6 py-6">
          <div className="mx-auto max-w-3xl">
            {/* Tab nav */}
            <nav
              className="mb-5 flex flex-wrap gap-1 rounded-lg p-1"
              style={{
                background: THEME.cardBg,
                border: `1px solid ${THEME.cardBorder}`,
              }}
              role="tablist"
              data-testid="dashboard-tabs"
            >
              {TABS.map((tab) => {
                const active = activeTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    data-testid={`tab-${tab.id}`}
                    onClick={() => setActiveTab(tab.id)}
                    className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold"
                    style={{
                      background: active
                        ? `linear-gradient(135deg,${THEME.accentFrom},${THEME.accentTo})`
                        : "transparent",
                      color: active ? "#fff" : THEME.textSoft,
                      boxShadow: active
                        ? `0 2px 12px ${THEME.accentFrom}44`
                        : undefined,
                    }}
                  >
                    <tab.Icon className="h-3.5 w-3.5" />
                    {tab.label}
                  </button>
                );
              })}
            </nav>

            {activeTab === "all-chats" && (
              <BotActionTab
                testIdPrefix="all-chats"
                hint="RTxRT mode — sends a DM to every chat in the inbox of the selected account. AdsPower must be running and the X profile logged in. 24h filter applies."
                intro="Replicates Luis's All Chats tab. Mission Control enqueues a dry-run DM sweep; the selected runner walks the inbox of whichever account is active on its side."
                primaryKind="dry_run_dm"
                primaryLabel="Dry-run DM sweep"
                primaryIcon={MessageSquare}
                runnerOffline={runnerOffline}
                noRunnerSelected={noRunnerSelected}
                selectedRunnerOffline={selectedRunnerOffline}
                busyKind={busyKind}
                onRun={handleRun}
              />
            )}

            {activeTab === "recipient-database" && (
              <BotActionTab
                testIdPrefix="recipient-database"
                hint="Cross-account blast — pulls an existing recipient list (contacts.json on the Claw computer) and DMs it from one or more sender accounts. Rate-limited."
                intro="Replicates Luis's Recipient Database tab. The actual recipient list and sender selection happens in the local dashboard; this control panel only kicks off the dry-run from Mission Control."
                primaryKind="dry_run_blast"
                primaryLabel="Dry-run blast"
                primaryIcon={Inbox}
                runnerOffline={runnerOffline}
                noRunnerSelected={noRunnerSelected}
                selectedRunnerOffline={selectedRunnerOffline}
                busyKind={busyKind}
                onRun={handleRun}
              />
            )}

            {activeTab === "new-database" && (
              <BotActionTab
                testIdPrefix="new-database"
                hint="Builds a new recipient list for the selected account — scrolls inbox or scrapes followers into contacts.json / follower_lists.json. Sends nothing."
                intro="Replicates Luis's New Database tab (builder_bot.py). The dry-run here builds against synthetic data so the runner wiring + folder structure are correct."
                primaryKind="dry_run_builder"
                primaryLabel="Dry-run builder"
                primaryIcon={Hammer}
                runnerOffline={runnerOffline}
                noRunnerSelected={noRunnerSelected}
                selectedRunnerOffline={selectedRunnerOffline}
                busyKind={busyKind}
                onRun={handleRun}
              />
            )}

            {activeTab === "promo-repost" && (
              <BotActionTab
                testIdPrefix="promo-repost"
                hint="Cross-account repost — promotes a post via cooperating accounts. Schedule + groups live on the Claw computer."
                intro="Replicates Luis's Promo Repost tab (repost_bot.py). Mission Control fires the dry-run; no real reposts happen."
                primaryKind="dry_run_repost"
                primaryLabel="Dry-run repost"
                primaryIcon={Repeat}
                runnerOffline={runnerOffline}
                noRunnerSelected={noRunnerSelected}
                selectedRunnerOffline={selectedRunnerOffline}
                busyKind={busyKind}
                onRun={handleRun}
              />
            )}

            {activeTab === "runner-status" && (
              <RunnerStatusTab
                runnerStatus={runnerStatus}
                busyKind={busyKind}
                onRun={handleRun}
                runners={runners}
                selectedRunnerId={effectiveSelected}
                noRunnerSelected={noRunnerSelected}
                selectedRunnerOffline={selectedRunnerOffline}
              />
            )}

            {activeTab === "run-history" && (
              <RunHistoryTab jobs={recentJobs} />
            )}

            {activeTab === "setup" && (
              <SetupTab canRunLiveOne={canRunLiveOne} />
            )}

            {/* Live-one section lives on every tab — operator should be
                able to escalate from anywhere. Operator+ gated + two-step
                Arm → Confirm. */}
            <LiveOneCard
              canRunLiveOne={canRunLiveOne}
              runnerOffline={runnerOffline}
              noRunnerSelected={noRunnerSelected}
              selectedRunnerOffline={selectedRunnerOffline}
              selectedRunnerId={effectiveSelected}
              busyKind={busyKind}
              onRun={handleRun}
            />
          </div>
        </main>
      </div>

      <style>{`@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}`}</style>
    </div>
  );
}

// ── Static catalogs ─────────────────────────────────────────────────────────

const OTHER_DRY_RUN_BUTTONS: {
  kind: JobKind;
  label: string;
  description: string;
  icon: React.ElementType;
}[] = [
  { kind: "dry_run_blast", label: "Dry-run blast", description: "blast_bot --dry-run", icon: Inbox },
  { kind: "dry_run_dm", label: "Dry-run DM", description: "dm_bot --dry-run", icon: MessageSquare },
  { kind: "dry_run_repost", label: "Dry-run repost", description: "repost_bot --dry-run", icon: Repeat },
  { kind: "dry_run_builder", label: "Dry-run builder", description: "builder_bot --dry-run", icon: Hammer },
  { kind: "dry_run_scan", label: "Dry-run scan", description: "scan_test --dry-run", icon: Users },
];

const LIVE_ONE_BUTTONS: { kind: JobKind; label: string }[] = [
  { kind: "live_one_blast", label: "Live-one blast (1 action)" },
  { kind: "live_one_dm", label: "Live-one DM (1 action)" },
  { kind: "live_one_repost", label: "Live-one repost (1 action)" },
  { kind: "live_one_builder", label: "Live-one builder (1 action)" },
  { kind: "live_one_scan", label: "Live-one scan (1 action)" },
];

const REQUIRED_ENV_VARS: { name: string; note: string }[] = [
  {
    name: "MSA_RTXRT_BACKEND_URL",
    note: "Mission Control backend URL the runner polls (e.g. https://api.mc...).",
  },
  {
    name: "MSA_RTXRT_RUNNER_TOKEN",
    note: "Shared-secret token. Must match the value the operator set in Mission Control's backend env. NEVER lands in the repo.",
  },
  {
    name: "MSA_RTXRT_RUNNER_ID",
    note: "Stable name this runner reports back (e.g. claw-1).",
  },
  {
    name: "MSA_RTXRT_BOT_DIR",
    note: "Path to incoming/luis-msa-import/MSA/Monthly revenue/Automation [RTxRT] on the Claw computer.",
  },
  {
    name: "ALLOW_LIVE_EXTERNAL_ACTIONS",
    note: "Must equal 'true' for live-one. Defaults to unset → live-one is refused by the runner's safety gate.",
  },
  {
    name: "CONFIRM_LIVE_TEST",
    note: "Must equal 'YES' for live-one. Case-sensitive.",
  },
  {
    name: "MAX_TEST_ACTIONS",
    note: "Must equal 1 for live-one. Higher values are refused by the runner.",
  },
];

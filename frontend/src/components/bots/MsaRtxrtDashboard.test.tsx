import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  LOCAL_DASHBOARD_URL,
  LUIS_BOT_REFERENCE_COMMIT,
  LUIS_BOT_SOURCE_BRANCH,
  MsaRtxrtDashboard,
  type MsaRtxrtDashboardProps,
} from "./MsaRtxrtDashboard";
import type { JobKind, MsaRtxrtJob } from "./MsaRtxrtControlPanel";

/** Default test runner the multi-runner-v2 dashboard pre-selects when the
 *  caller passes ``runnerStatus: "idle"`` or ``"busy"``. */
const TEST_RUNNER_ID = "claw-1";

function makeProps(
  overrides: Partial<MsaRtxrtDashboardProps> = {},
): MsaRtxrtDashboardProps {
  const runnerStatus = overrides.runnerStatus ?? "offline";
  // When the caller wants buttons enabled (idle / busy), default the
  // multi-runner props to a single online runner that's already
  // selected — that preserves the v1 "buttons are clickable when
  // idle" contract for legacy tests that don't care about targeting.
  const defaultsForLive =
    runnerStatus === "idle" || runnerStatus === "busy"
      ? {
          runners: [
            {
              runner_id: TEST_RUNNER_ID,
              last_seen_at: "2026-05-20T12:00:00Z",
              seconds_since_seen: 0,
              status: "online" as const,
              last_status: "idle" as const,
              can_accept_jobs: true,
              jobs_recently_handled: 0,
            },
          ],
          selectedRunnerId: TEST_RUNNER_ID,
        }
      : {};
  return {
    runnerStatus,
    recentJobs: [],
    isOwner: false,
    onSubmitJob: vi.fn().mockResolvedValue(undefined),
    onRefresh: vi.fn().mockResolvedValue(undefined),
    ...defaultsForLive,
    ...overrides,
  };
}

const ALL_TABS = [
  "all-chats",
  "recipient-database",
  "new-database",
  "promo-repost",
  "runner-status",
  "run-history",
  "setup",
] as const;

// ── Top-level layout ─────────────────────────────────────────────────────────

describe("MsaRtxrtDashboard — layout", () => {
  it("renders the purple-themed dashboard shell and runner badge", () => {
    render(<MsaRtxrtDashboard {...makeProps()} />);
    const root = screen.getByTestId("msa-rtxrt-dashboard");
    expect(root).toBeInTheDocument();
    // The runner badge in the top bar exposes the current status.
    const badge = screen.getByTestId("dashboard-runner-status");
    expect(badge).toHaveAttribute("data-status", "offline");
    expect(badge.textContent).toMatch(/Runner offline/i);
  });

  it("renders the left account / runner rail", () => {
    render(<MsaRtxrtDashboard {...makeProps()} />);
    const rail = screen.getByTestId("account-rail");
    expect(rail).toBeInTheDocument();
    // Empty state when there are no jobs.
    expect(screen.getByTestId("account-rail-empty")).toBeInTheDocument();
  });

  it("populates the rail from recent jobs grouped by kind (privacy-safe)", () => {
    const jobs: MsaRtxrtJob[] = [
      { id: "a", kind: "smoke", status: "succeeded", createdAt: "2026-05-13T10:00:00Z" },
      { id: "b", kind: "smoke", status: "succeeded", createdAt: "2026-05-13T11:00:00Z" },
      { id: "c", kind: "dry_run_blast", status: "queued", createdAt: "2026-05-13T12:00:00Z" },
    ];
    render(<MsaRtxrtDashboard {...makeProps({ recentJobs: jobs })} />);
    // Count badge sums the jobs.
    expect(screen.getByTestId("account-rail-count").textContent).toBe("3");
    // Lanes show as buttons keyed by kind.
    expect(screen.getByTestId("runner-lane-smoke")).toBeInTheDocument();
    expect(screen.getByTestId("runner-lane-dry_run_blast")).toBeInTheDocument();
    // No invented PII in the rail — only the kind names appear.
    expect(rail()).not.toMatch(/@/); // no @handles
  });

  function rail(): string {
    return screen.getByTestId("account-rail").textContent || "";
  }
});

// ── Tabs ────────────────────────────────────────────────────────────────────

describe("MsaRtxrtDashboard — tabs", () => {
  it("renders all seven tab buttons by testid", () => {
    render(<MsaRtxrtDashboard {...makeProps()} />);
    for (const tabId of ALL_TABS) {
      expect(screen.getByTestId(`tab-${tabId}`)).toBeInTheDocument();
    }
  });

  it("shows the All Chats tab by default", () => {
    render(<MsaRtxrtDashboard {...makeProps()} />);
    expect(screen.getByTestId("tab-pane-all-chats")).toBeInTheDocument();
    expect(screen.queryByTestId("tab-pane-recipient-database")).toBeNull();
  });

  it("switches panes when clicking each tab", () => {
    render(<MsaRtxrtDashboard {...makeProps()} />);
    for (const tabId of ALL_TABS) {
      fireEvent.click(screen.getByTestId(`tab-${tabId}`));
      expect(screen.getByTestId(`tab-pane-${tabId}`)).toBeInTheDocument();
    }
  });
});

// ── Run buttons (smoke + dry-run) ────────────────────────────────────────────

describe("MsaRtxrtDashboard — run buttons", () => {
  it("Smoke posts a 'smoke' job", () => {
    const onSubmitJob = vi.fn().mockResolvedValue(undefined);
    render(
      <MsaRtxrtDashboard
        {...makeProps({ runnerStatus: "idle", onSubmitJob })}
      />,
    );
    // Smoke lives on the Runner Status tab.
    fireEvent.click(screen.getByTestId("tab-runner-status"));
    fireEvent.click(screen.getByTestId("run-smoke"));
    expect(onSubmitJob).toHaveBeenCalledWith("smoke", TEST_RUNNER_ID);
  });

  it.each([
    ["all-chats", "dry_run_dm"],
    ["recipient-database", "dry_run_blast"],
    ["new-database", "dry_run_builder"],
    ["promo-repost", "dry_run_repost"],
  ] as Array<[string, JobKind]>)(
    "the %s tab fires the %s job",
    (tabId, kind) => {
      const onSubmitJob = vi.fn().mockResolvedValue(undefined);
      render(
        <MsaRtxrtDashboard
          {...makeProps({ runnerStatus: "idle", onSubmitJob })}
        />,
      );
      fireEvent.click(screen.getByTestId(`tab-${tabId}`));
      fireEvent.click(screen.getByTestId(`run-${kind}`));
      expect(onSubmitJob).toHaveBeenCalledWith(kind, TEST_RUNNER_ID);
    },
  );

  it("disables every dry-run + smoke button when the runner is offline", () => {
    render(<MsaRtxrtDashboard {...makeProps({ runnerStatus: "offline" })} />);
    fireEvent.click(screen.getByTestId("tab-all-chats"));
    expect(screen.getByTestId("run-dry_run_dm")).toBeDisabled();
    fireEvent.click(screen.getByTestId("tab-runner-status"));
    expect(screen.getByTestId("run-smoke")).toBeDisabled();
    expect(screen.getByTestId("run-dry_run_blast")).toBeDisabled();
    expect(screen.getByTestId("run-dry_run_dm")).toBeDisabled();
    expect(screen.getByTestId("run-dry_run_repost")).toBeDisabled();
    expect(screen.getByTestId("run-dry_run_builder")).toBeDisabled();
    expect(screen.getByTestId("run-dry_run_scan")).toBeDisabled();
  });
});

// ── No mass-live anywhere ───────────────────────────────────────────────────

describe("MsaRtxrtDashboard — mass-live safety", () => {
  it("does not render any mass-live button (no testid contains live_all / live_mass / live_batch / live_many)", () => {
    render(<MsaRtxrtDashboard {...makeProps({ runnerStatus: "idle", isOwner: true })} />);
    // Open the live-one section so the kind dropdown is rendered.
    fireEvent.click(screen.getByTestId("live-one-arm"));
    const select = screen.getByTestId("live-one-kind-select");
    const options = within(select).getAllByRole("option");
    for (const opt of options) {
      const v = (opt as HTMLOptionElement).value;
      expect(v).not.toMatch(/live_all|live_mass|live_batch|live_many/i);
    }
    // And no run-* testid exists anywhere for a mass-live kind.
    for (const dangerous of [
      "run-live_all_blast",
      "run-live_mass_dm",
      "run-live_batch_repost",
      "run-live_many",
    ]) {
      expect(screen.queryByTestId(dangerous)).toBeNull();
    }
  });
});

// ── Live-one gating ─────────────────────────────────────────────────────────

describe("MsaRtxrtDashboard — live-one gating", () => {
  it("non-owner sees the locked notice and no arm button", () => {
    render(
      <MsaRtxrtDashboard
        {...makeProps({ runnerStatus: "idle", isOwner: false })}
      />,
    );
    expect(screen.getByTestId("live-one-locked-not-owner")).toBeInTheDocument();
    expect(screen.queryByTestId("live-one-arm")).toBeNull();
    expect(screen.queryByTestId("live-one-confirm")).toBeNull();
  });

  it("owner sees an arm button before any live-one is offered", () => {
    render(
      <MsaRtxrtDashboard
        {...makeProps({ runnerStatus: "idle", isOwner: true })}
      />,
    );
    expect(screen.getByTestId("live-one-arm")).toBeInTheDocument();
    expect(screen.queryByTestId("live-one-confirm")).toBeNull();
  });

  it("two-step confirm: Arm → pick kind → Confirm fires the right kind", () => {
    const onSubmitJob = vi.fn().mockResolvedValue(undefined);
    render(
      <MsaRtxrtDashboard
        {...makeProps({ runnerStatus: "idle", isOwner: true, onSubmitJob })}
      />,
    );
    fireEvent.click(screen.getByTestId("live-one-arm"));
    fireEvent.change(screen.getByTestId("live-one-kind-select"), {
      target: { value: "live_one_dm" },
    });
    fireEvent.click(screen.getByTestId("live-one-confirm"));

    expect(onSubmitJob).toHaveBeenCalledWith("live_one_dm", TEST_RUNNER_ID);
    // Disarms back to the Arm button.
    expect(screen.getByTestId("live-one-arm")).toBeInTheDocument();
  });

  it("Cancel disarms without firing", () => {
    const onSubmitJob = vi.fn().mockResolvedValue(undefined);
    render(
      <MsaRtxrtDashboard
        {...makeProps({ runnerStatus: "idle", isOwner: true, onSubmitJob })}
      />,
    );
    fireEvent.click(screen.getByTestId("live-one-arm"));
    fireEvent.change(screen.getByTestId("live-one-kind-select"), {
      target: { value: "live_one_blast" },
    });
    fireEvent.click(screen.getByTestId("live-one-cancel"));
    expect(onSubmitJob).not.toHaveBeenCalled();
    expect(screen.getByTestId("live-one-arm")).toBeInTheDocument();
  });
});

// ── Setup tab content ───────────────────────────────────────────────────────

describe("MsaRtxrtDashboard — setup tab", () => {
  function openSetup() {
    render(<MsaRtxrtDashboard {...makeProps()} />);
    fireEvent.click(screen.getByTestId("tab-setup"));
  }

  it("surfaces the source branch, latest safe commit, and runtime folder", () => {
    openSetup();
    expect(screen.getByText(LUIS_BOT_SOURCE_BRANCH)).toBeInTheDocument();
    expect(screen.getByText(LUIS_BOT_REFERENCE_COMMIT)).toBeInTheDocument();
    // The "Automation [RTxRT]" path appears twice (runtime folder + env
    // var note) — scope the assertion to the source-info block.
    const sourceInfo = screen.getByTestId("setup-source-info");
    expect(sourceInfo.textContent).toMatch(
      /incoming\/luis-msa-import.*Automation \[RTxRT\]/,
    );
  });

  it("renders the env checklist with the required vars", () => {
    openSetup();
    const checklist = screen.getByTestId("setup-env-checklist");
    expect(within(checklist).getByText("MSA_RTXRT_BACKEND_URL")).toBeInTheDocument();
    expect(within(checklist).getByText("MSA_RTXRT_RUNNER_TOKEN")).toBeInTheDocument();
    expect(within(checklist).getByText("MSA_RTXRT_BOT_DIR")).toBeInTheDocument();
    expect(
      within(checklist).getByText("ALLOW_LIVE_EXTERNAL_ACTIONS"),
    ).toBeInTheDocument();
    expect(within(checklist).getByText("CONFIRM_LIVE_TEST")).toBeInTheDocument();
    expect(within(checklist).getByText("MAX_TEST_ACTIONS")).toBeInTheDocument();
  });

  it("renders the AdsPower + X logged-in notice", () => {
    openSetup();
    const notice = screen.getByTestId("setup-external-notice");
    expect(notice.textContent).toMatch(/AdsPower/i);
    expect(notice.textContent).toMatch(/logged in/i);
  });

  it("renders the working local dashboard URL block with the Open + Copy controls", () => {
    openSetup();
    expect(screen.getByText(LOCAL_DASHBOARD_URL)).toBeInTheDocument();
    const openBtn = screen.getByTestId("local-dashboard-open");
    expect(openBtn).toHaveAttribute("href", LOCAL_DASHBOARD_URL);
    expect(
      screen.getByRole("button", { name: /copy local dashboard url/i }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("local-dashboard-note").textContent).toMatch(
      /only resolves on the Claw computer/i,
    );
  });

  it("renders the safety posture summary", () => {
    openSetup();
    const safety = screen.getByTestId("setup-safety");
    expect(safety.textContent).toMatch(/DRY_RUN=true/);
    expect(safety.textContent).toMatch(/ALLOW_LIVE_EXTERNAL_ACTIONS=false/);
    expect(safety.textContent).toMatch(/Mass-live runs are blocked outright/i);
  });
});

// ── Run history tab ─────────────────────────────────────────────────────────

describe("MsaRtxrtDashboard — run history tab", () => {
  it("shows the empty-state when there are no jobs", () => {
    render(<MsaRtxrtDashboard {...makeProps()} />);
    fireEvent.click(screen.getByTestId("tab-run-history"));
    expect(screen.getByTestId("run-history-empty")).toBeInTheDocument();
  });

  it("renders one history row per job with status + kind + summary", () => {
    const jobs: MsaRtxrtJob[] = [
      {
        id: "j-1",
        kind: "smoke",
        status: "succeeded",
        createdAt: "2026-05-13T10:00:00Z",
        summary: "Smoke OK",
      },
      {
        id: "j-2",
        kind: "dry_run_blast",
        status: "failed",
        createdAt: "2026-05-13T11:00:00Z",
        summary: "Bot folder missing",
      },
    ];
    render(<MsaRtxrtDashboard {...makeProps({ recentJobs: jobs })} />);
    fireEvent.click(screen.getByTestId("tab-run-history"));
    expect(screen.getByTestId("history-row-j-1")).toBeInTheDocument();
    expect(screen.getByTestId("history-row-j-2")).toBeInTheDocument();
    expect(screen.getByText("Smoke OK")).toBeInTheDocument();
    expect(screen.getByText("Bot folder missing")).toBeInTheDocument();
  });
});

// ── Runner offline state on runner-status tab ───────────────────────────────

describe("MsaRtxrtDashboard — runner status tab", () => {
  it("shows an explicit offline notice when runner is offline", () => {
    render(<MsaRtxrtDashboard {...makeProps()} />);
    fireEvent.click(screen.getByTestId("tab-runner-status"));
    const pane = screen.getByTestId("tab-pane-runner-status");
    // Copy updated in multi-runner v2: "No runner is online" replaces
    // the single-runner-specific "Claw runner is not connected".
    expect(pane.textContent).toMatch(/No runner is online/i);
  });

  it("flips to the online label when status is idle", () => {
    render(<MsaRtxrtDashboard {...makeProps({ runnerStatus: "idle" })} />);
    fireEvent.click(screen.getByTestId("tab-runner-status"));
    const pane = screen.getByTestId("tab-pane-runner-status");
    expect(pane.textContent).toMatch(/Runner online/i);
  });
});

// ── Refresh wiring ──────────────────────────────────────────────────────────

describe("MsaRtxrtDashboard — refresh", () => {
  it("calls onRefresh when the dashboard refresh button is clicked", () => {
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    render(<MsaRtxrtDashboard {...makeProps({ onRefresh })} />);
    fireEvent.click(screen.getByTestId("dashboard-refresh"));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });
});

// ── No-secrets contract ─────────────────────────────────────────────────────

describe("MsaRtxrtDashboard — no secrets", () => {
  it("never renders raw API-key / cookie / session strings in any tab", () => {
    // The bridge UI should never receive such material from the backend
    // either. This guard ensures we don't accidentally bake one into the
    // dashboard's static catalog (env checklist, hints, notices).
    render(<MsaRtxrtDashboard {...makeProps({ runnerStatus: "idle", isOwner: true })} />);
    for (const tabId of ALL_TABS) {
      fireEvent.click(screen.getByTestId(`tab-${tabId}`));
      const root = screen.getByTestId("msa-rtxrt-dashboard");
      const text = root.textContent || "";
      expect(text).not.toMatch(/sk_(live|test)_[A-Za-z0-9]{16,}/);
      expect(text).not.toMatch(/pk_(live|test)_[A-Za-z0-9]{16,}/);
      expect(text).not.toMatch(/eyJhbGciO/); // JWT prefix
      expect(text).not.toMatch(/Bearer [A-Za-z0-9._-]{20,}/);
      expect(text.toLowerCase()).not.toMatch(/cookie:\s*[a-z]/);
    }
  });
});

// ── Setup tab additions (heartbeat-aware UX, restart/stop, AdsPower + configs)

describe("SetupTab — new operational sections", () => {
  function openSetup() {
    render(<MsaRtxrtDashboard {...makeProps()} />);
    fireEvent.click(screen.getByTestId("tab-setup"));
  }

  it("renders the AdsPower checklist with the local API URL", () => {
    openSetup();
    const note = screen.getByTestId("adspower-note");
    expect(note).toBeInTheDocument();
    // The local API URL appears at least once somewhere in setup content.
    const setupPane = screen.getByTestId("tab-pane-setup");
    expect(setupPane.textContent || "").toMatch(/local\.adspower\.net:50325/);
  });

  it("renders the config-files checklist by name (no contents)", () => {
    openSetup();
    expect(screen.getByText(/auftrag\.example\.json/)).toBeInTheDocument();
    expect(screen.getByText(/contacts\.example\.json/)).toBeInTheDocument();
  });

  it("exposes restart, stop, and preflight commands with copy buttons", () => {
    openSetup();
    expect(screen.getByTestId("restart-command")).toBeInTheDocument();
    expect(screen.getByTestId("stop-command")).toBeInTheDocument();
    expect(screen.getByTestId("preflight-command")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /copy restart command/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /copy stop command/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /copy preflight command/i }),
    ).toBeInTheDocument();
  });

  it("renders the 'Luis vs Zach' role separation, with no mass-live affordance", () => {
    openSetup();
    expect(screen.getByTestId("luis-can-do")).toBeInTheDocument();
    expect(screen.getByTestId("owner-only")).toBeInTheDocument();
    const ownerText = screen.getByTestId("owner-only").textContent ?? "";
    expect(ownerText).not.toMatch(/run mass[- ]live/i);
  });
});

// ── Heartbeat-enabled smoke gate (the chicken-and-egg fix) ──────────────────

describe("Smoke button is enabled by heartbeat-derived idle even with no jobs", () => {
  it("Smoke is enabled when runnerStatus === 'idle' and recentJobs === [] (with a selected online runner)", () => {
    render(<MsaRtxrtDashboard {...makeProps({ runnerStatus: "idle" })} />);
    fireEvent.click(screen.getByTestId("tab-runner-status"));
    const smoke = screen.getByTestId("run-smoke") as HTMLButtonElement;
    expect(smoke.disabled).toBe(false);
  });

  it("Smoke is disabled when runnerStatus === 'offline'", () => {
    render(
      <MsaRtxrtDashboard
        runnerStatus="offline"
        recentJobs={[]}
        isOwner={false}
        onSubmitJob={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("tab-runner-status"));
    const smoke = screen.getByTestId("run-smoke") as HTMLButtonElement;
    expect(smoke.disabled).toBe(true);
  });

  it("Live-one stays owner-gated regardless of heartbeat-driven idle", () => {
    render(
      <MsaRtxrtDashboard
        runnerStatus="idle"
        recentJobs={[]}
        isOwner={false}
        onSubmitJob={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("tab-runner-status"));
    expect(screen.queryByTestId("live-one-arm")).toBeNull();
  });
});

// ── Multi-runner v2 ─────────────────────────────────────────────────────────

describe("MsaRtxrtDashboard — multi-runner selector", () => {
  const TWO_RUNNERS = [
    {
      runner_id: "claw-1",
      last_seen_at: "2026-05-20T12:00:00Z",
      seconds_since_seen: 0,
      status: "online" as const,
      last_status: "idle" as const,
      can_accept_jobs: true,
      jobs_recently_handled: 0,
    },
    {
      runner_id: "luis-pc-1",
      last_seen_at: "2026-05-20T11:50:00Z",
      seconds_since_seen: 600,
      status: "offline" as const,
      last_status: "idle" as const,
      can_accept_jobs: false,
      jobs_recently_handled: 0,
    },
  ];

  it("runner selector renders one <option> per known runner", () => {
    render(
      <MsaRtxrtDashboard
        {...makeProps({
          runnerStatus: "idle",
          runners: TWO_RUNNERS,
          selectedRunnerId: "claw-1",
        })}
      />,
    );
    const select = screen.getByTestId("runner-selector") as HTMLSelectElement;
    expect(within(select).getAllByRole("option").length).toBe(1 + TWO_RUNNERS.length);
    // The disabled-by-default sentinel is the first option.
    expect(
      (within(select).getAllByRole("option")[0] as HTMLOptionElement).value,
    ).toBe("");
  });

  it("buttons disabled when no runner is selected (even if a runner is online)", () => {
    render(
      <MsaRtxrtDashboard
        {...makeProps({
          runnerStatus: "idle",
          runners: TWO_RUNNERS,
          selectedRunnerId: null,
        })}
      />,
    );
    fireEvent.click(screen.getByTestId("tab-runner-status"));
    expect((screen.getByTestId("run-smoke") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("status-tab-no-runner-warning")).toBeInTheDocument();
  });

  it("buttons disabled when the selected runner is offline", () => {
    render(
      <MsaRtxrtDashboard
        {...makeProps({
          runnerStatus: "offline",
          runners: TWO_RUNNERS,
          selectedRunnerId: "luis-pc-1",
        })}
      />,
    );
    fireEvent.click(screen.getByTestId("tab-runner-status"));
    expect((screen.getByTestId("run-smoke") as HTMLButtonElement).disabled).toBe(true);
  });

  it("smoke job sends the selected runner_id through to onSubmitJob", () => {
    const onSubmitJob = vi.fn().mockResolvedValue(undefined);
    render(
      <MsaRtxrtDashboard
        {...makeProps({
          runnerStatus: "idle",
          runners: TWO_RUNNERS,
          selectedRunnerId: "claw-1",
          onSubmitJob,
        })}
      />,
    );
    fireEvent.click(screen.getByTestId("tab-runner-status"));
    fireEvent.click(screen.getByTestId("run-smoke"));
    expect(onSubmitJob).toHaveBeenCalledWith("smoke", "claw-1");
  });

  it("dry-run job sends the selected runner_id through to onSubmitJob", () => {
    const onSubmitJob = vi.fn().mockResolvedValue(undefined);
    render(
      <MsaRtxrtDashboard
        {...makeProps({
          runnerStatus: "idle",
          runners: TWO_RUNNERS,
          selectedRunnerId: "claw-1",
          onSubmitJob,
        })}
      />,
    );
    fireEvent.click(screen.getByTestId("tab-all-chats"));
    fireEvent.click(screen.getByTestId("run-dry_run_dm"));
    expect(onSubmitJob).toHaveBeenCalledWith("dry_run_dm", "claw-1");
  });

  it("changing the selected runner threads through onSelectRunner", () => {
    const onSelectRunner = vi.fn();
    render(
      <MsaRtxrtDashboard
        {...makeProps({
          runnerStatus: "idle",
          runners: TWO_RUNNERS,
          selectedRunnerId: "claw-1",
          onSelectRunner,
        })}
      />,
    );
    fireEvent.change(screen.getByTestId("runner-selector"), {
      target: { value: "luis-pc-1" },
    });
    expect(onSelectRunner).toHaveBeenCalledWith("luis-pc-1");
  });

  it("run history rows show the runner_id (or target_runner_id with arrow)", () => {
    const jobs: MsaRtxrtJob[] = [
      {
        id: "j1",
        kind: "smoke",
        status: "succeeded",
        createdAt: "2026-05-20T11:50:00Z",
        finishedAt: "2026-05-20T11:50:30Z",
        runnerId: "claw-1",
        targetRunnerId: "claw-1",
      },
      {
        id: "j2",
        kind: "dry_run_dm",
        status: "queued",
        createdAt: "2026-05-20T11:51:00Z",
        targetRunnerId: "luis-pc-1",
      },
    ];
    render(
      <MsaRtxrtDashboard
        {...makeProps({
          runnerStatus: "idle",
          recentJobs: jobs,
        })}
      />,
    );
    fireEvent.click(screen.getByTestId("tab-run-history"));
    expect(screen.getByTestId("history-row-runner-j1").textContent).toBe("claw-1");
    // Queued + no claimer yet → render the target with the arrow prefix.
    expect(screen.getByTestId("history-row-runner-j2").textContent).toBe("→ luis-pc-1");
  });

  it("live-one stays owner-gated AND requires a selected online runner", () => {
    // No runner selected → live-one arm button stays disabled even for owner.
    render(
      <MsaRtxrtDashboard
        {...makeProps({
          runnerStatus: "idle",
          isOwner: true,
          runners: TWO_RUNNERS,
          selectedRunnerId: null,
        })}
      />,
    );
    const arm = screen.getByTestId("live-one-arm") as HTMLButtonElement;
    expect(arm.disabled).toBe(true);
  });

  it("setup tab includes the 'Add another runner computer' panel", () => {
    render(<MsaRtxrtDashboard {...makeProps()} />);
    fireEvent.click(screen.getByTestId("tab-setup"));
    expect(screen.getByTestId("setup-add-runner-intro")).toBeInTheDocument();
    expect(screen.getByTestId("setup-add-runner-steps")).toBeInTheDocument();
    // No secrets in the copy.
    const pane = screen.getByTestId("tab-pane-setup");
    expect(pane.textContent).not.toMatch(/api[_ -]?key\s*[:=]/i);
  });

  it("connected-runners list renders every runner with status", () => {
    render(
      <MsaRtxrtDashboard
        {...makeProps({
          runnerStatus: "idle",
          runners: TWO_RUNNERS,
          selectedRunnerId: "claw-1",
        })}
      />,
    );
    fireEvent.click(screen.getByTestId("tab-runner-status"));
    expect(screen.getByTestId("connected-runner-claw-1")).toBeInTheDocument();
    expect(screen.getByTestId("connected-runner-luis-pc-1")).toBeInTheDocument();
  });
});

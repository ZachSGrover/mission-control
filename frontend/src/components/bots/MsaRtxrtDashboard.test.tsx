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
    canRunLiveOne: false,
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
  "campaign",
  "runner-status",
  "run-history",
  "logs",
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
  it("renders all nine tab buttons by testid (parity v1: + Campaign + Logs)", () => {
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
    render(<MsaRtxrtDashboard {...makeProps({ runnerStatus: "idle", canRunLiveOne: true })} />);
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
  it("builder / viewer (canRunLiveOne=false) sees the locked notice and no arm button", () => {
    render(
      <MsaRtxrtDashboard
        {...makeProps({ runnerStatus: "idle", canRunLiveOne: false })}
      />,
    );
    expect(
      screen.getByTestId("live-one-locked-insufficient-role"),
    ).toBeInTheDocument();
    // Copy reads Operator/Admin, NOT Owner only (post 2026-05-20).
    expect(
      screen.getByTestId("live-one-locked-insufficient-role").textContent,
    ).toMatch(/Operator\/Admin access required/i);
    expect(screen.queryByTestId("live-one-arm")).toBeNull();
    expect(screen.queryByTestId("live-one-confirm")).toBeNull();
  });

  it("operator+ (canRunLiveOne=true) sees an arm button before any live-one is offered", () => {
    render(
      <MsaRtxrtDashboard
        {...makeProps({ runnerStatus: "idle", canRunLiveOne: true })}
      />,
    );
    expect(screen.getByTestId("live-one-arm")).toBeInTheDocument();
    expect(screen.queryByTestId("live-one-confirm")).toBeNull();
  });

  it("two-step confirm: Arm → pick kind → Confirm fires the right kind", () => {
    const onSubmitJob = vi.fn().mockResolvedValue(undefined);
    render(
      <MsaRtxrtDashboard
        {...makeProps({ runnerStatus: "idle", canRunLiveOne: true, onSubmitJob })}
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
        {...makeProps({ runnerStatus: "idle", canRunLiveOne: true, onSubmitJob })}
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

  it("renders the Luis Local Dashboard card with the Open + Copy controls", () => {
    openSetup();
    expect(screen.getByText(LOCAL_DASHBOARD_URL)).toBeInTheDocument();
    const openBtn = screen.getByTestId("local-dashboard-open");
    expect(openBtn).toHaveAttribute("href", LOCAL_DASHBOARD_URL);
    expect(openBtn.textContent).toMatch(/Open Local Dashboard/);
    expect(
      screen.getByRole("button", { name: /copy local dashboard url/i }),
    ).toBeInTheDocument();
    // Intro explains the deep-link, not-a-proxy posture.
    expect(screen.getByTestId("local-dashboard-intro").textContent).toMatch(
      /deep link, not a proxy/i,
    );
  });

  it("explains localhost semantics across machines (luis-pc-1 / Zach / phone)", () => {
    openSetup();
    const semantics = screen.getByTestId("local-dashboard-semantics");
    expect(semantics.textContent).toMatch(/luis-pc-1/);
    // Zach's machine: localhost is Zach's own, not Luis's.
    expect(semantics.textContent).toMatch(/Zach/);
    expect(semantics.textContent).toMatch(/own computer, not Luis/i);
    // Phone / remote: needs a tunnel; not building one yet.
    expect(semantics.textContent).toMatch(/phone|remote/i);
    expect(semantics.textContent).toMatch(/tunnel|proxy|bridge/i);
  });

  it("renders the Current Status card with all six checks", () => {
    openSetup();
    const status = screen.getByTestId("local-dashboard-current-status");
    expect(status.textContent).toMatch(/Current status/i);
    expect(screen.getByTestId("status-runner-connected").textContent).toMatch(
      /luis-pc-1.*connected/i,
    );
    expect(screen.getByTestId("status-smoke-verified").textContent).toMatch(/smoke/i);
    expect(screen.getByTestId("status-dry-runs-verified").textContent).toMatch(
      /dry-runs verified/i,
    );
    expect(screen.getByTestId("status-live-one-gated").textContent).toMatch(
      /live-one gated/i,
    );
    expect(screen.getByTestId("status-mass-live-blocked").textContent).toMatch(
      /mass-live blocked/i,
    );
    expect(screen.getByTestId("status-bridge-added").textContent).toMatch(
      /bridge added/i,
    );
  });

  it("renders the ownership note naming Zach as owner and Luis as builder", () => {
    openSetup();
    const note = screen.getByTestId("ownership-note");
    expect(note.textContent).toMatch(/Zach/);
    expect(note.textContent).toMatch(/Digidle OS/);
    expect(note.textContent).toMatch(/Modern Sales Agency/);
    expect(note.textContent).toMatch(/Luis/);
    expect(note.textContent).toMatch(/builder/i);
    expect(note.textContent).toMatch(/operator/i);
    expect(note.textContent).toMatch(/source of truth/i);
    // Runner machines — current + planned future.
    expect(note.textContent).toMatch(/luis-pc-1/);
    expect(note.textContent).toMatch(/claw-1/);
    expect(note.textContent).toMatch(/zach-laptop-1/);
    expect(note.textContent).toMatch(/mac-mini-1/);
    expect(note.textContent).toMatch(/mac-mini-2/);
  });

  it("renders the editing model: bot logic edits direct vs Mission Control via PR", () => {
    openSetup();
    const model = screen.getByTestId("editing-model");
    const bot = screen.getByTestId("editing-model-bot");
    expect(bot.textContent).toMatch(/Bot logic changes/i);
    expect(bot.textContent).toMatch(/bot folder/i);
    expect(bot.textContent).toMatch(/no deploy|next job/i);
    const ui = screen.getByTestId("editing-model-ui");
    expect(ui.textContent).toMatch(/Digidle OS interface/i);
    expect(ui.textContent).toMatch(/PR/);
    expect(ui.textContent).toMatch(/checks/i);
    expect(ui.textContent).toMatch(/merge/i);
    // The model card lives inside the same NumberedCard.
    expect(model).toBeInTheDocument();
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
    render(<MsaRtxrtDashboard {...makeProps({ runnerStatus: "idle", canRunLiveOne: true })} />);
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
    const luis = screen.getByTestId("luis-can-do");
    const ownerOnly = screen.getByTestId("owner-only");
    expect(luis).toBeInTheDocument();
    expect(ownerOnly).toBeInTheDocument();
    // Post 2026-05-20: Luis can run controlled live-one (operator role).
    expect(luis.textContent ?? "").toMatch(/controlled live-one/i);
    // Owner-only column should still exist for production / security.
    expect(ownerOnly.textContent ?? "").toMatch(/main/i);
    // No mass-live affordance anywhere.
    expect(ownerOnly.textContent ?? "").not.toMatch(/run mass[- ]live/i);
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
        canRunLiveOne={false}
        onSubmitJob={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("tab-runner-status"));
    const smoke = screen.getByTestId("run-smoke") as HTMLButtonElement;
    expect(smoke.disabled).toBe(true);
  });

  it("Live-one stays role-gated (Operator+) regardless of heartbeat-driven idle", () => {
    render(
      <MsaRtxrtDashboard
        runnerStatus="idle"
        recentJobs={[]}
        canRunLiveOne={false}
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

  it("live-one stays role-gated AND requires a selected online runner", () => {
    // No runner selected → live-one arm button stays disabled even when
    // canRunLiveOne is true (operator+).
    render(
      <MsaRtxrtDashboard
        {...makeProps({
          runnerStatus: "idle",
          canRunLiveOne: true,
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

// ── Parity v1: status header, Campaign + Logs tabs, wired/roadmap ──────────
//
// These cover the parity-sprint additions:
//   * Top-of-dashboard status header with 4 chips
//   * Campaign + Logs placeholder tabs (clearly labelled, no fake actions)
//   * "What is wired now" matrix on Setup
//   * Dashboard parity roadmap on Setup
//   * Existing dry-run controls still render
//   * No mass-live kinds exposed in the static catalogs

describe("MsaRtxrtDashboard — parity v1 status header", () => {
  it("renders the dashboard status header with all four chips", () => {
    render(<MsaRtxrtDashboard {...makeProps({ runnerStatus: "idle" })} />);
    const header = screen.getByTestId("dashboard-status-header");
    expect(header).toBeInTheDocument();
    expect(screen.getByTestId("dashboard-status-local-bridge").textContent).toMatch(
      /Local dashboard bridge/i,
    );
    expect(screen.getByTestId("dashboard-status-dry-runs").textContent).toMatch(
      /Dry-runs/i,
    );
    expect(screen.getByTestId("dashboard-status-dry-runs").textContent).toMatch(
      /verified/i,
    );
    expect(screen.getByTestId("dashboard-status-live-one").textContent).toMatch(
      /Live-one.*gated/i,
    );
    expect(screen.getByTestId("dashboard-status-mass-live").textContent).toMatch(
      /Mass-live.*blocked/i,
    );
  });
});

describe("MsaRtxrtDashboard — parity v1 Campaign tab", () => {
  it("renders the Campaign placeholder pane with the Local-only status", () => {
    render(<MsaRtxrtDashboard {...makeProps({ runnerStatus: "idle" })} />);
    fireEvent.click(screen.getByTestId("tab-campaign"));
    const pane = screen.getByTestId("tab-pane-campaign");
    expect(pane).toBeInTheDocument();
    expect(screen.getByTestId("campaign-status-text").textContent).toMatch(
      /local dashboard.*Campaign tab/i,
    );
    expect(screen.getByTestId("campaign-planned-list").textContent).toMatch(
      /dry_run_campaign/i,
    );
    expect(screen.getByTestId("campaign-planned-list").textContent).toMatch(
      /live_one_campaign/i,
    );
    // Does NOT render a clickable run button for an unwired kind.
    expect(screen.queryByTestId("run-dry_run_campaign")).toBeNull();
    expect(screen.queryByTestId("run-live_one_campaign")).toBeNull();
  });
});

describe("MsaRtxrtDashboard — parity v1 Logs tab", () => {
  it("renders the Logs placeholder pane and the privacy rationale", () => {
    render(<MsaRtxrtDashboard {...makeProps({ runnerStatus: "idle" })} />);
    fireEvent.click(screen.getByTestId("tab-logs"));
    expect(screen.getByTestId("tab-pane-logs")).toBeInTheDocument();
    expect(screen.getByTestId("logs-status-text").textContent).toMatch(
      /local dashboard/i,
    );
    const rationale = screen.getByTestId("logs-rationale-list");
    expect(rationale.textContent).toMatch(/recipient handles/i);
    expect(rationale.textContent).toMatch(/Run History/i);
  });
});

describe("MsaRtxrtDashboard — parity v1 Setup additions", () => {
  function openSetup() {
    render(<MsaRtxrtDashboard {...makeProps({ runnerStatus: "idle" })} />);
    fireEvent.click(screen.getByTestId("tab-setup"));
  }

  it("renders the 'What is wired now' matrix with all expected rows", () => {
    openSetup();
    const matrix = screen.getByTestId("wired-now-matrix");
    expect(matrix).toBeInTheDocument();
    // Wired kinds.
    expect(screen.getByTestId("wired-now-row-smoke").textContent).toMatch(/smoke/);
    expect(screen.getByTestId("wired-now-row-dry_run_dm").textContent).toMatch(/dry_run_dm/);
    expect(screen.getByTestId("wired-now-row-dry_run_repost").textContent).toMatch(/dry_run_repost/);
    expect(screen.getByTestId("wired-now-row-dry_run_blast").textContent).toMatch(/dry_run_blast/);
    expect(screen.getByTestId("wired-now-row-dry_run_builder").textContent).toMatch(/dry_run_builder/);
    expect(screen.getByTestId("wired-now-row-live_one_repost").textContent).toMatch(/1×1 capped/);
    // Local-only.
    expect(screen.getByTestId("wired-now-row-dry_run_scan")).toBeInTheDocument();
    expect(screen.getByTestId("wired-now-row-campaign")).toBeInTheDocument();
    // Planned.
    expect(screen.getByTestId("wired-now-row-logs")).toBeInTheDocument();
  });

  it("renders the dashboard parity roadmap with the next 8 rebuild items", () => {
    openSetup();
    const roadmap = screen.getByTestId("parity-roadmap-list");
    expect(roadmap).toBeInTheDocument();
    [
      "all-chats",
      "recipient-database",
      "promo-repost",
      "new-database",
      "campaign",
      "adspower",
      "schedule",
      "secure-bridge",
    ].forEach((id) => {
      expect(screen.getByTestId(`parity-roadmap-row-${id}`)).toBeInTheDocument();
    });
    expect(screen.getByTestId("parity-roadmap-note").textContent).toMatch(
      /runner adapter|job-kind/i,
    );
  });
});

describe("MsaRtxrtDashboard — parity v1 honesty", () => {
  it("never exposes mass-live / bulk kinds in any clickable element", () => {
    render(
      <MsaRtxrtDashboard {...makeProps({ runnerStatus: "idle", canRunLiveOne: true })} />,
    );
    for (const tabId of ALL_TABS) {
      fireEvent.click(screen.getByTestId(`tab-${tabId}`));
      // Loop over all buttons + anchors. None of their data-kind attrs may
      // contain a mass-live token, and none of their visible text may
      // promise a mass-live action.
      const root = screen.getByTestId("msa-rtxrt-dashboard");
      const interactive = [
        ...root.querySelectorAll("button"),
        ...root.querySelectorAll("a"),
      ];
      for (const el of interactive) {
        const kind = (el as HTMLElement).getAttribute("data-kind") || "";
        expect(kind).not.toMatch(/live_all_|live_mass_|live_batch_|live_many_/);
        const label = (el.textContent || "").toLowerCase();
        expect(label).not.toMatch(/mass\s*live\s*run/);
      }
    }
  });

  it("still exposes the dry-run controls (regression guard for parity-v1 reshuffle)", () => {
    render(
      <MsaRtxrtDashboard {...makeProps({ runnerStatus: "idle" })} />,
    );
    // From the Runner Status tab, smoke is still there.
    fireEvent.click(screen.getByTestId("tab-runner-status"));
    expect(screen.getByTestId("run-smoke")).toBeInTheDocument();
    // From each tab that owns a dry-run kind, the primary button still
    // exists with the same data-kind so wiring tests upstream don't break.
    fireEvent.click(screen.getByTestId("tab-all-chats"));
    expect(screen.getByTestId("run-dry_run_dm")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("tab-recipient-database"));
    expect(screen.getByTestId("run-dry_run_blast")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("tab-new-database"));
    expect(screen.getByTestId("run-dry_run_builder")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("tab-promo-repost"));
    expect(screen.getByTestId("run-dry_run_repost")).toBeInTheDocument();
  });

  it("Live-one gated copy still renders in the live-one card", () => {
    render(
      <MsaRtxrtDashboard {...makeProps({ runnerStatus: "idle", canRunLiveOne: true })} />,
    );
    // The live-one card title still mentions Operator/Admin and references
    // the three local env vars on the runner machine.
    const root = screen.getByTestId("msa-rtxrt-dashboard");
    expect(root.textContent || "").toMatch(/Live-one test/);
    expect(root.textContent || "").toMatch(/three local env vars/);
  });
});

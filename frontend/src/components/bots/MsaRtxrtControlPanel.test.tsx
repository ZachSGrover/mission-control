import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  MsaRtxrtControlPanel,
  type JobKind,
  type MsaRtxrtControlPanelProps,
  type MsaRtxrtJob,
} from "./MsaRtxrtControlPanel";

function makeProps(
  overrides: Partial<MsaRtxrtControlPanelProps> = {},
): MsaRtxrtControlPanelProps {
  return {
    runnerStatus: "offline",
    recentJobs: [],
    isOwner: false,
    onSubmitJob: vi.fn().mockResolvedValue(undefined),
    onRefresh: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

const ALL_DRY_RUN_KINDS: JobKind[] = [
  "smoke",
  "dry_run_blast",
  "dry_run_dm",
  "dry_run_repost",
  "dry_run_builder",
  "dry_run_scan",
];

// ── Header + runner-status badge ─────────────────────────────────────────────

describe("MsaRtxrtControlPanel — runner status", () => {
  it("shows 'Claw runner offline' and the offline notice in default state", () => {
    render(<MsaRtxrtControlPanel {...makeProps()} />);
    expect(screen.getByTestId("runner-status")).toHaveAttribute(
      "data-status",
      "offline",
    );
    expect(screen.getByText(/Claw runner offline/i)).toBeInTheDocument();
    expect(screen.getByTestId("runner-offline-notice")).toBeInTheDocument();
  });

  it("shows 'Claw runner online' when status is idle and hides the offline notice", () => {
    render(<MsaRtxrtControlPanel {...makeProps({ runnerStatus: "idle" })} />);
    expect(screen.getByText(/Claw runner online/i)).toBeInTheDocument();
    expect(screen.queryByTestId("runner-offline-notice")).toBeNull();
  });
});

// ── Run buttons (dry-run + smoke) ────────────────────────────────────────────

describe("MsaRtxrtControlPanel — dry-run buttons", () => {
  it("disables every dry-run + smoke button when the runner is offline", () => {
    render(<MsaRtxrtControlPanel {...makeProps({ runnerStatus: "offline" })} />);
    for (const kind of ALL_DRY_RUN_KINDS) {
      const btn = screen.getByTestId(`run-${kind}`);
      expect(btn).toBeDisabled();
    }
  });

  it("enables dry-run + smoke buttons when the runner is online", () => {
    render(<MsaRtxrtControlPanel {...makeProps({ runnerStatus: "idle" })} />);
    for (const kind of ALL_DRY_RUN_KINDS) {
      expect(screen.getByTestId(`run-${kind}`)).not.toBeDisabled();
    }
  });

  it("calls onSubmitJob with the right kind when a dry-run button is clicked", async () => {
    const onSubmitJob = vi.fn().mockResolvedValue(undefined);
    render(
      <MsaRtxrtControlPanel
        {...makeProps({ runnerStatus: "idle", onSubmitJob })}
      />,
    );
    fireEvent.click(screen.getByTestId("run-dry_run_blast"));
    expect(onSubmitJob).toHaveBeenCalledWith("dry_run_blast");
  });
});

// ── Live-one section (owner gating + two-step confirm) ───────────────────────

describe("MsaRtxrtControlPanel — live-one gating", () => {
  it("non-owner sees the locked notice and no arm button", () => {
    render(
      <MsaRtxrtControlPanel {...makeProps({ runnerStatus: "idle", isOwner: false })} />,
    );
    expect(screen.getByTestId("live-one-locked-not-owner")).toBeInTheDocument();
    expect(screen.queryByTestId("live-one-arm")).toBeNull();
    expect(screen.queryByTestId("live-one-confirm")).toBeNull();
  });

  it("owner sees an arm button before any live-one is offered", () => {
    render(
      <MsaRtxrtControlPanel {...makeProps({ runnerStatus: "idle", isOwner: true })} />,
    );
    expect(screen.getByTestId("live-one-arm")).toBeInTheDocument();
    expect(screen.queryByTestId("live-one-confirm")).toBeNull();
    expect(screen.queryByTestId("live-one-kind-select")).toBeNull();
  });

  it("arming reveals the kind picker + Confirm/Cancel; Confirm is disabled until a kind is chosen", () => {
    render(
      <MsaRtxrtControlPanel {...makeProps({ runnerStatus: "idle", isOwner: true })} />,
    );
    fireEvent.click(screen.getByTestId("live-one-arm"));

    const select = screen.getByTestId("live-one-kind-select");
    expect(select).toBeInTheDocument();
    const confirm = screen.getByTestId("live-one-confirm");
    expect(confirm).toBeDisabled();

    fireEvent.change(select, { target: { value: "live_one_dm" } });
    expect(confirm).not.toBeDisabled();
  });

  it("Confirm calls onSubmitJob with the chosen live-one kind and disarms the section", () => {
    const onSubmitJob = vi.fn().mockResolvedValue(undefined);
    render(
      <MsaRtxrtControlPanel
        {...makeProps({ runnerStatus: "idle", isOwner: true, onSubmitJob })}
      />,
    );
    fireEvent.click(screen.getByTestId("live-one-arm"));
    fireEvent.change(screen.getByTestId("live-one-kind-select"), {
      target: { value: "live_one_repost" },
    });
    fireEvent.click(screen.getByTestId("live-one-confirm"));

    expect(onSubmitJob).toHaveBeenCalledWith("live_one_repost");
    // After confirm, the section disarms back to the arm button.
    expect(screen.getByTestId("live-one-arm")).toBeInTheDocument();
    expect(screen.queryByTestId("live-one-confirm")).toBeNull();
  });

  it("Cancel disarms without submitting", () => {
    const onSubmitJob = vi.fn().mockResolvedValue(undefined);
    render(
      <MsaRtxrtControlPanel
        {...makeProps({ runnerStatus: "idle", isOwner: true, onSubmitJob })}
      />,
    );
    fireEvent.click(screen.getByTestId("live-one-arm"));
    fireEvent.change(screen.getByTestId("live-one-kind-select"), {
      target: { value: "live_one_dm" },
    });
    fireEvent.click(screen.getByTestId("live-one-cancel"));

    expect(onSubmitJob).not.toHaveBeenCalled();
    expect(screen.getByTestId("live-one-arm")).toBeInTheDocument();
  });

  it("disables Confirm when the runner is offline even after arming", () => {
    render(
      <MsaRtxrtControlPanel {...makeProps({ isOwner: true, runnerStatus: "offline" })} />,
    );
    // Arm button itself is disabled when offline — operator can't even get to the picker.
    expect(screen.getByTestId("live-one-arm")).toBeDisabled();
  });
});

// ── Run history ──────────────────────────────────────────────────────────────

describe("MsaRtxrtControlPanel — run history", () => {
  it("shows the empty-state message when there are no jobs", () => {
    render(<MsaRtxrtControlPanel {...makeProps()} />);
    expect(screen.getByTestId("run-history-empty")).toBeInTheDocument();
  });

  it("renders one row per recent job", () => {
    const jobs: MsaRtxrtJob[] = [
      {
        id: "j-1",
        kind: "smoke",
        status: "succeeded",
        createdAt: new Date("2026-05-12T10:00:00Z").toISOString(),
        summary: "Smoke OK",
      },
      {
        id: "j-2",
        kind: "dry_run_blast",
        status: "failed",
        createdAt: new Date("2026-05-12T11:00:00Z").toISOString(),
        summary: "Bot folder missing",
      },
    ];
    render(<MsaRtxrtControlPanel {...makeProps({ recentJobs: jobs })} />);
    expect(screen.queryByTestId("run-history-empty")).toBeNull();
    expect(screen.getByTestId("run-history-list")).toBeInTheDocument();
    expect(screen.getByTestId("job-j-1")).toBeInTheDocument();
    expect(screen.getByTestId("job-j-2")).toBeInTheDocument();
    expect(screen.getByText(/Smoke OK/i)).toBeInTheDocument();
    expect(screen.getByText(/Bot folder missing/i)).toBeInTheDocument();
  });
});

// ── Refresh button ───────────────────────────────────────────────────────────

describe("MsaRtxrtControlPanel — refresh", () => {
  it("calls onRefresh when the refresh button is clicked", () => {
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    render(<MsaRtxrtControlPanel {...makeProps({ onRefresh })} />);
    fireEvent.click(screen.getByTestId("refresh-button"));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });
});

// ── Configuration block ──────────────────────────────────────────────────────

describe("MsaRtxrtControlPanel — configuration block", () => {
  it("surfaces the source branch, runtime folder, and live-mode posture", () => {
    render(<MsaRtxrtControlPanel {...makeProps()} />);
    expect(screen.getByText("coo/import-luis-msa")).toBeInTheDocument();
    expect(
      screen.getByText(/incoming\/luis-msa-import.*Automation \[RTxRT\]/),
    ).toBeInTheDocument();
    expect(screen.getByText(/DRY_RUN=true/)).toBeInTheDocument();
    expect(
      screen.getByText(/ALLOW_LIVE_EXTERNAL_ACTIONS=false \(locked\)/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/CONFIRM_LIVE_TEST=YES.*MAX_TEST_ACTIONS=1.*owner only/),
    ).toBeInTheDocument();
  });
});

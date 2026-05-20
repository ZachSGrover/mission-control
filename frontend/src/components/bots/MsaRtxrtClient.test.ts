import { describe, expect, it } from "vitest";

import {
  deriveRunnerStatus,
  jobBodyForKind,
  rowToJob,
  rowsToJobs,
  type BackendJobRow,
} from "./MsaRtxrtClient";
import type { JobKind } from "./MsaRtxrtControlPanel";

function makeRow(overrides: Partial<BackendJobRow> = {}): BackendJobRow {
  return {
    id: "row-1",
    kind: "dry_run_blast",
    status: "queued",
    requested_by_user_id: "u-op",
    created_at: "2026-05-12T10:00:00Z",
    started_at: null,
    finished_at: null,
    summary: null,
    stdout_excerpt: null,
    error_excerpt: null,
    runner_id: null,
    target_runner_id: null,
    dry_run: true,
    live_one: false,
    max_test_actions: 0,
    ...overrides,
  };
}

// ── jobBodyForKind ─────────────────────────────────────────────────────────

describe("jobBodyForKind", () => {
  it("dry-run kinds produce a body with kind only", () => {
    expect(jobBodyForKind("smoke")).toEqual({ kind: "smoke" });
    expect(jobBodyForKind("dry_run_blast")).toEqual({ kind: "dry_run_blast" });
    expect(jobBodyForKind("dry_run_dm")).toEqual({ kind: "dry_run_dm" });
  });

  it("live-one kinds add confirm_live=YES and max_test_actions=1", () => {
    const kinds: JobKind[] = [
      "live_one_blast",
      "live_one_dm",
      "live_one_repost",
      "live_one_builder",
      "live_one_scan",
    ];
    for (const k of kinds) {
      expect(jobBodyForKind(k)).toEqual({
        kind: k,
        confirm_live: "YES",
        max_test_actions: 1,
      });
    }
  });
});

// ── rowToJob ───────────────────────────────────────────────────────────────

describe("rowToJob", () => {
  it("maps a basic dry-run row to a UI job", () => {
    const job = rowToJob(makeRow({ status: "running" }));
    expect(job).not.toBeNull();
    expect(job?.kind).toBe("dry_run_blast");
    expect(job?.status).toBe("running");
    expect(job?.createdAt).toBe("2026-05-12T10:00:00Z");
  });

  it("returns null for unknown kinds", () => {
    expect(rowToJob(makeRow({ kind: "live_all_blast" }))).toBeNull();
    expect(rowToJob(makeRow({ kind: "bogus" }))).toBeNull();
  });

  it("collapses cancelled to failed in the UI surface", () => {
    const job = rowToJob(makeRow({ status: "cancelled" }));
    expect(job?.status).toBe("failed");
  });

  it("prefers explicit summary over stdout/error excerpts", () => {
    const job = rowToJob(
      makeRow({
        status: "succeeded",
        summary: "Smoke OK",
        stdout_excerpt: "200 candidates processed.",
      }),
    );
    expect(job?.summary).toBe("Smoke OK");
  });

  it("falls back to error_excerpt for failed/blocked rows without a summary", () => {
    const job = rowToJob(
      makeRow({
        status: "failed",
        summary: null,
        error_excerpt: "script crashed",
        stdout_excerpt: "starting…",
      }),
    );
    expect(job?.summary).toBe("script crashed");
  });

  it("falls back to stdout_excerpt for succeeded rows without a summary", () => {
    const job = rowToJob(
      makeRow({
        status: "succeeded",
        summary: null,
        stdout_excerpt: "done",
      }),
    );
    expect(job?.summary).toBe("done");
  });
});

// ── rowsToJobs ─────────────────────────────────────────────────────────────

describe("rowsToJobs", () => {
  it("drops rows with unknown kinds while keeping the rest", () => {
    const jobs = rowsToJobs([
      makeRow({ id: "a", kind: "smoke", status: "succeeded" }),
      makeRow({ id: "b", kind: "live_all_blast" }), // dropped
      makeRow({ id: "c", kind: "dry_run_dm", status: "queued" }),
    ]);
    expect(jobs.map((j) => j.id)).toEqual(["a", "c"]);
  });
});

// ── deriveRunnerStatus (with heartbeat — preferred path) ───────────────────

const NOW = new Date("2026-05-12T12:00:00Z");

function hb(any_online: boolean): import("./MsaRtxrtClient").BackendRunnerStatus {
  return {
    runners: [
      {
        runner_id: "claw-1",
        last_seen_at: NOW.toISOString(),
        seconds_since_seen: any_online ? 3 : 999,
        status: any_online ? "online" : "offline",
        last_status: "idle",
      },
    ],
    any_online,
    freshness_seconds: 90,
  };
}

describe("deriveRunnerStatus (heartbeat-aware)", () => {
  it("returns idle when heartbeat says online and no job is running", () => {
    expect(deriveRunnerStatus([], hb(true), NOW)).toBe("idle");
  });

  it("returns idle even when there are ZERO jobs ever — chicken-and-egg fix", () => {
    // The original bug: empty queue → button disabled forever.
    expect(deriveRunnerStatus([], hb(true), NOW)).toBe("idle");
  });

  it("returns busy when heartbeat is online AND a job is currently running", () => {
    expect(
      deriveRunnerStatus(
        [makeRow({ status: "running", started_at: "2026-05-12T11:59:00Z" })],
        hb(true),
        NOW,
      ),
    ).toBe("busy");
  });

  it("returns offline when heartbeat says no runner is online", () => {
    expect(deriveRunnerStatus([], hb(false), NOW)).toBe("offline");
  });

  it("trusts heartbeat over recent terminal jobs (online → idle even with no recent job)", () => {
    expect(deriveRunnerStatus([], hb(true), NOW)).toBe("idle");
  });

  it("falls back to job-derived status when heartbeat is null (graceful degradation)", () => {
    // No heartbeat snapshot, no running job, but a fresh terminal job → idle.
    expect(
      deriveRunnerStatus(
        [makeRow({ status: "succeeded", finished_at: "2026-05-12T11:59:30Z" })],
        null,
        NOW,
      ),
    ).toBe("idle");
  });
});

// ── deriveRunnerStatusFromJobs (legacy, fallback) ──────────────────────────

import { deriveRunnerStatusFromJobs } from "./MsaRtxrtClient";

describe("deriveRunnerStatusFromJobs (legacy fallback)", () => {
  it("returns offline for an empty list", () => {
    expect(deriveRunnerStatusFromJobs([], NOW)).toBe("offline");
  });

  it("returns busy when any row is running", () => {
    expect(
      deriveRunnerStatusFromJobs(
        [makeRow({ status: "running", started_at: "2026-05-12T11:59:00Z" })],
        NOW,
      ),
    ).toBe("busy");
  });

  it("returns idle when the most recent terminal job finished within freshness window", () => {
    const result = deriveRunnerStatusFromJobs(
      [
        makeRow({
          status: "succeeded",
          finished_at: "2026-05-12T11:59:30Z", // 30s ago
        }),
      ],
      NOW,
    );
    expect(result).toBe("idle");
  });

  it("returns offline when the most recent terminal job is older than freshness window", () => {
    const result = deriveRunnerStatusFromJobs(
      [
        makeRow({
          status: "succeeded",
          finished_at: "2026-05-12T11:55:00Z", // 5 min ago
        }),
      ],
      NOW,
    );
    expect(result).toBe("offline");
  });

  it("returns offline when there are only queued rows (no runner activity)", () => {
    expect(
      deriveRunnerStatusFromJobs(
        [makeRow({ status: "queued", finished_at: null })],
        NOW,
      ),
    ).toBe("offline");
  });

  it("ignores rows with null/invalid finished_at while still working off the rest", () => {
    const result = deriveRunnerStatusFromJobs(
      [
        makeRow({ id: "a", status: "queued", finished_at: null }),
        makeRow({ id: "b", status: "succeeded", finished_at: "not-a-date" }),
        makeRow({
          id: "c",
          status: "succeeded",
          finished_at: "2026-05-12T11:59:45Z", // 15s ago
        }),
      ],
      NOW,
    );
    expect(result).toBe("idle");
  });
});

// ── Multi-runner targeting helpers ─────────────────────────────────────────

import { findHeartbeatById } from "./MsaRtxrtClient";

describe("jobBodyForKind (multi-runner v2)", () => {
  it("attaches target_runner_id when one is provided", () => {
    expect(jobBodyForKind("smoke", "luis-mac-1")).toEqual({
      kind: "smoke",
      target_runner_id: "luis-mac-1",
    });
  });

  it("omits target_runner_id when null or empty", () => {
    expect(jobBodyForKind("smoke", null)).toEqual({ kind: "smoke" });
    expect(jobBodyForKind("smoke", "")).toEqual({ kind: "smoke" });
    expect(jobBodyForKind("smoke", "   ")).toEqual({ kind: "smoke" });
  });

  it("preserves live-one safety flags alongside target_runner_id", () => {
    expect(jobBodyForKind("live_one_dm", "zach-laptop-1")).toEqual({
      kind: "live_one_dm",
      confirm_live: "YES",
      max_test_actions: 1,
      target_runner_id: "zach-laptop-1",
    });
  });
});

function multiRunnerHeartbeat(): import("./MsaRtxrtClient").BackendRunnerStatus {
  return {
    runners: [
      {
        runner_id: "claw-1",
        last_seen_at: NOW.toISOString(),
        seconds_since_seen: 3,
        status: "online",
        last_status: "idle",
      },
      {
        runner_id: "luis-mac-1",
        last_seen_at: "2026-05-12T11:50:00Z",
        seconds_since_seen: 600,
        status: "offline",
        last_status: "idle",
      },
    ],
    any_online: true,
    freshness_seconds: 90,
  };
}

describe("findHeartbeatById", () => {
  it("returns the matching runner row", () => {
    const hb = multiRunnerHeartbeat();
    expect(findHeartbeatById(hb, "claw-1")?.runner_id).toBe("claw-1");
    expect(findHeartbeatById(hb, "luis-mac-1")?.runner_id).toBe("luis-mac-1");
  });

  it("returns null on no match", () => {
    expect(findHeartbeatById(multiRunnerHeartbeat(), "mac-mini-1")).toBeNull();
  });

  it("returns null on empty / whitespace / null runner ID", () => {
    const hb = multiRunnerHeartbeat();
    expect(findHeartbeatById(hb, "")).toBeNull();
    expect(findHeartbeatById(hb, "   ")).toBeNull();
    expect(findHeartbeatById(hb, null)).toBeNull();
  });

  it("returns null on null heartbeat", () => {
    expect(findHeartbeatById(null, "claw-1")).toBeNull();
  });
});

describe("deriveRunnerStatus (selectedRunnerId-aware)", () => {
  it("returns idle when the selected runner is online", () => {
    expect(
      deriveRunnerStatus([], multiRunnerHeartbeat(), NOW, undefined, "claw-1"),
    ).toBe("idle");
  });

  it("returns offline when the selected runner is offline (even if another is online)", () => {
    expect(
      deriveRunnerStatus([], multiRunnerHeartbeat(), NOW, undefined, "luis-mac-1"),
    ).toBe("offline");
  });

  it("returns offline when the selected runner doesn't exist in the heartbeat", () => {
    expect(
      deriveRunnerStatus(
        [],
        multiRunnerHeartbeat(),
        NOW,
        undefined,
        "mac-mini-1",
      ),
    ).toBe("offline");
  });

  it("returns busy when any job is running (irrespective of selected runner)", () => {
    expect(
      deriveRunnerStatus(
        [makeRow({ status: "running", started_at: "2026-05-12T11:59:00Z" })],
        multiRunnerHeartbeat(),
        NOW,
        undefined,
        "claw-1",
      ),
    ).toBe("busy");
  });

  it("falls back to any_online when no runner is selected (back-compat)", () => {
    expect(deriveRunnerStatus([], multiRunnerHeartbeat(), NOW)).toBe("idle");
    expect(
      deriveRunnerStatus([], multiRunnerHeartbeat(), NOW, undefined, ""),
    ).toBe("idle");
    expect(
      deriveRunnerStatus([], multiRunnerHeartbeat(), NOW, undefined, null),
    ).toBe("idle");
  });
});

describe("rowToJob (multi-runner v2 fields)", () => {
  it("surfaces runner_id and target_runner_id when present", () => {
    const job = rowToJob(
      makeRow({
        kind: "smoke",
        status: "succeeded",
        runner_id: "luis-mac-1",
        target_runner_id: "luis-mac-1",
      }),
    );
    expect(job?.runnerId).toBe("luis-mac-1");
    expect(job?.targetRunnerId).toBe("luis-mac-1");
  });

  it("leaves runnerId/targetRunnerId undefined when backend returns null", () => {
    const job = rowToJob(
      makeRow({
        kind: "smoke",
        status: "queued",
        runner_id: null,
        target_runner_id: null,
      }),
    );
    expect(job?.runnerId).toBeUndefined();
    expect(job?.targetRunnerId).toBeUndefined();
  });
});

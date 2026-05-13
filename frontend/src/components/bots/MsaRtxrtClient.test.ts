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

// ── deriveRunnerStatus ─────────────────────────────────────────────────────

const NOW = new Date("2026-05-12T12:00:00Z");

describe("deriveRunnerStatus", () => {
  it("returns offline for an empty list", () => {
    expect(deriveRunnerStatus([], NOW)).toBe("offline");
  });

  it("returns busy when any row is running", () => {
    expect(
      deriveRunnerStatus(
        [makeRow({ status: "running", started_at: "2026-05-12T11:59:00Z" })],
        NOW,
      ),
    ).toBe("busy");
  });

  it("returns idle when the most recent terminal job finished within freshness window", () => {
    const result = deriveRunnerStatus(
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
    const result = deriveRunnerStatus(
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
      deriveRunnerStatus(
        [makeRow({ status: "queued", finished_at: null })],
        NOW,
      ),
    ).toBe("offline");
  });

  it("ignores rows with null/invalid finished_at while still working off the rest", () => {
    const result = deriveRunnerStatus(
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

/**
 * OnlyFans Intelligence — typed API helpers.
 *
 * Thin wrapper around `fetch` so the (many) sub-pages don't each duplicate
 * URL construction and error parsing.  All requests go through the caller's
 * `fetchWithAuth` from useAuthFetch so auth headers are injected uniformly.
 *
 * Mirrors the backend router at /api/v1/of-intelligence — no schema is
 * generated yet because Phase 1 sub-pages all use these direct types.
 */

import { getApiBaseUrl } from "@/lib/api-base";

// ── Shared types — mirror the backend Pydantic schemas ────────────────────────

export type FetchFn = (url: string, init?: RequestInit) => Promise<Response>;

export type CredentialStatus = {
  has_token: boolean;
  api_key_source: "db" | "env" | "none";
  api_key_preview: string | null;
  base_url: string;
  base_url_source: "db" | "env" | "none";
  supported_entities: string[];
};

export type PingResponse = {
  ok: boolean;
  status_code: number | null;
  latency_ms: number | null;
  base_url: string;
  api_key_source: "db" | "env" | "none";
  error: string | null;
  // Self-diagnosing fields populated by the backend's PingResult.  When
  // the *backend* route itself is missing (Mission Control out of date),
  // the frontend synthesizes a "mission_control" error_source instead of
  // throwing — see ofiApi.testConnection below.
  tested_url: string;
  error_source: "ok" | "configuration" | "network" | "onlymonster" | "mission_control" | "unknown";
  message: string | null;
};

export type SyncLogRow = {
  id: string;
  run_id: string;
  source: string;
  entity: string;
  status: string;
  items_synced: number;
  created_count: number;
  updated_count: number;
  skipped_duplicate_count: number;
  error_count: number;
  pages_fetched: number;
  reason: string | null;
  error: string | null;
  source_endpoint: string | null;
  started_at: string;
  finished_at: string | null;
  triggered_by: string | null;
};

export type StatusResponse = {
  connection: PingResponse;
  last_run_id: string | null;
  last_run_started_at: string | null;
  entities: Record<string, {
    status: string;
    items_synced: number;
    pages_fetched: number;
    started_at: string | null;
    finished_at: string | null;
    reason: string | null;
    error: string | null;
  }>;
  supported_entities: string[];
};

export type OverviewMetrics = {
  api_connected: boolean;
  api_key_source: "db" | "env" | "none";
  last_sync_started_at: string | null;
  last_sync_status: string | null;
  accounts_synced: number;
  fans_synced: number;
  messages_synced: number;
  revenue_today_cents: number;
  revenue_7d_cents: number;
  revenue_30d_cents: number;
  accounts_needing_attention: number;
  chatters_to_review: number;
  critical_alerts: number;
  latest_qc_report_id: string | null;
  latest_qc_report_date: string | null;
};

export type AccountRow = {
  id: string;
  source: string;
  source_id: string;
  username: string | null;
  display_name: string | null;
  status: string | null;
  access_status: string | null;
  last_synced_at: string;
};

export type FanRow = {
  id: string;
  source_id: string;
  account_source_id: string | null;
  username: string | null;
  lifetime_value_cents: number | null;
  last_message_at: string | null;
  is_subscribed: boolean | null;
  last_synced_at: string;
};

export type ChatterRow = {
  id: string;
  source_id: string;
  name: string | null;
  email: string | null;
  role: string | null;
  active: boolean | null;
  last_synced_at: string;
};

export type MessageRow = {
  id: string;
  source_id: string;
  chat_source_id: string | null;
  account_source_id: string | null;
  fan_source_id: string | null;
  chatter_source_id: string | null;
  direction: string | null;
  sent_at: string | null;
  body: string | null;
  revenue_cents: number | null;
};

export type MassMessageRow = {
  id: string;
  source_id: string;
  account_source_id: string | null;
  sent_at: string | null;
  recipients_count: number | null;
  purchases_count: number | null;
  revenue_cents: number | null;
  body_preview: string | null;
  snapshot_at: string;
};

export type PostRow = {
  id: string;
  source_id: string;
  account_source_id: string | null;
  published_at: string | null;
  likes_count: number | null;
  comments_count: number | null;
  revenue_cents: number | null;
  snapshot_at: string;
};

export type RevenueRow = {
  id: string;
  account_source_id: string | null;
  period_start: string | null;
  period_end: string | null;
  revenue_cents: number;
  transactions_count: number | null;
  captured_at: string;
};

export type QcReportRow = {
  id: string;
  report_date: string;
  summary: string | null;
  critical_alerts_count: number;
  accounts_reviewed: number;
  chatters_reviewed: number;
  generated_at: string;
};

export type QcReportDetail = QcReportRow & {
  payload: Record<string, unknown>;
  markdown: string | null;
};

export type QcConfig = {
  daily_report_time: string;  // "HH:MM" UTC; empty string means unset
  enabled: boolean;
  note?: string;
};

export type AlertRow = {
  id: string;
  code: string;
  severity: "info" | "warn" | "critical" | string;
  status: "open" | "acknowledged" | "resolved" | string;
  title: string;
  message: string | null;
  account_source_id: string | null;
  chatter_source_id: string | null;
  fan_source_id: string | null;
  created_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
};

export type MemoryEntryRow = {
  id: string;
  product: string;
  kind: string;
  title: string;
  obsidian_path: string | null;
  account_source_id: string | null;
  period_start: string | null;
  created_at: string;
};

export type ExportResponse = {
  generated_at: string;
  file_count: number;
  written_to_disk: string[];
  skipped: string[];
  obsidian_root: string;
};

// ── Helper ────────────────────────────────────────────────────────────────────

const BASE = "/api/v1/of-intelligence";

async function jsonRequest<T>(fetchFn: FetchFn, path: string, init?: RequestInit): Promise<T> {
  const res = await fetchFn(`${getApiBaseUrl()}${BASE}${path}`, init);
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json() as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// ── Public API ────────────────────────────────────────────────────────────────

export const ofiApi = {
  status:        (f: FetchFn) => jsonRequest<StatusResponse>(f, "/status"),
  overview:      (f: FetchFn) => jsonRequest<OverviewMetrics>(f, "/overview"),
  credentials:   (f: FetchFn) => jsonRequest<CredentialStatus>(f, "/credentials"),
  saveCredentials: (f: FetchFn, body: { api_key?: string; base_url?: string }) =>
    jsonRequest<CredentialStatus>(f, "/credentials", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteCredentials: (f: FetchFn) => jsonRequest<void>(f, "/credentials", { method: "DELETE" }),
  testConnection: async (f: FetchFn): Promise<PingResponse> => {
    const url = `${getApiBaseUrl()}${BASE}/test`;
    let res: Response;
    try {
      res = await f(url, { method: "POST" });
    } catch (err) {
      return {
        ok: false,
        status_code: null,
        latency_ms: null,
        base_url: "",
        api_key_source: "none",
        error: err instanceof Error ? err.message : String(err),
        tested_url: url,
        error_source: "mission_control",
        message: `Could not reach Mission Control backend at ${url}.`,
      };
    }
    if (res.ok) {
      return res.json() as Promise<PingResponse>;
    }
    // 404 here means *the Mission Control backend itself* is missing the
    // /of-intelligence/test route — usually because the backend process is
    // running an older build that predates this branch.  Return a
    // synthesized response so the Settings page can render a useful banner.
    let detail = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    return {
      ok: false,
      status_code: res.status,
      latency_ms: null,
      base_url: "",
      api_key_source: "none",
      error: detail,
      tested_url: url,
      error_source: "mission_control",
      message:
        res.status === 404
          ? "Mission Control backend has no /api/v1/of-intelligence/test route. Restart the backend with this branch's code."
          : `Mission Control backend returned ${res.status}: ${detail}`,
    };
  },
  triggerSync:   (f: FetchFn) => jsonRequest<{ ok: boolean; started_at: string; detail: string }>(f, "/sync", { method: "POST" }),
  syncLogs:      (f: FetchFn, limit = 100) => jsonRequest<SyncLogRow[]>(f, `/sync-logs?limit=${limit}`),

  accounts:      (f: FetchFn) => jsonRequest<AccountRow[]>(f, "/accounts"),
  fans:          (f: FetchFn, limit = 200) => jsonRequest<FanRow[]>(f, `/fans?limit=${limit}`),
  chatters:      (f: FetchFn) => jsonRequest<ChatterRow[]>(f, "/chatters"),
  messages:      (f: FetchFn, limit = 200) => jsonRequest<MessageRow[]>(f, `/messages?limit=${limit}`),
  massMessages:  (f: FetchFn, limit = 100) => jsonRequest<MassMessageRow[]>(f, `/mass-messages?limit=${limit}`),
  posts:         (f: FetchFn, limit = 100) => jsonRequest<PostRow[]>(f, `/posts?limit=${limit}`),
  revenue:       (f: FetchFn, limit = 200) => jsonRequest<RevenueRow[]>(f, `/revenue?limit=${limit}`),

  qcReports:     (f: FetchFn, limit = 30) => jsonRequest<QcReportRow[]>(f, `/qc-reports?limit=${limit}`),
  qcReport:      (f: FetchFn, id: string) => jsonRequest<QcReportDetail>(f, `/qc-reports/${id}`),
  generateQcReport: (f: FetchFn) => jsonRequest<QcReportDetail>(f, "/qc-reports", { method: "POST" }),

  qcConfig:      (f: FetchFn) => jsonRequest<QcConfig>(f, "/qc-config"),
  saveQcConfig:  (f: FetchFn, body: { daily_report_time?: string | null; enabled?: boolean }) =>
    jsonRequest<QcConfig>(f, "/qc-config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  alerts:        (f: FetchFn, opts: { onlyOpen?: boolean; limit?: number } = {}) => {
    const params = new URLSearchParams();
    if (opts.onlyOpen) params.set("only_open", "true");
    params.set("limit", String(opts.limit ?? 100));
    return jsonRequest<AlertRow[]>(f, `/alerts?${params.toString()}`);
  },
  evaluateAlerts: (f: FetchFn) => jsonRequest<{ evaluated_at: string; rules_run: number; alerts_created: number; alerts_skipped_existing: number }>(f, "/alerts/evaluate", { method: "POST" }),
  ackAlert:       (f: FetchFn, id: string) => jsonRequest<AlertRow>(f, `/alerts/${id}/acknowledge`, { method: "POST" }),
  resolveAlert:   (f: FetchFn, id: string) => jsonRequest<AlertRow>(f, `/alerts/${id}/resolve`, { method: "POST" }),

  memory:        (f: FetchFn, limit = 100) => jsonRequest<MemoryEntryRow[]>(f, `/memory?limit=${limit}`),
  exportMemory:  (f: FetchFn, body: { target_date?: string; export_path?: string; mirror_to_memory?: boolean } = {}) =>
    jsonRequest<ExportResponse>(f, "/memory/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};

// ── Display helpers ───────────────────────────────────────────────────────────

export function formatCents(cents: number | null | undefined): string {
  if (cents == null) return "—";
  return `$${(cents / 100).toFixed(2)}`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

export function formatRelative(value: string | null | undefined): string {
  if (!value) return "—";
  const ts = new Date(value).getTime();
  if (Number.isNaN(ts)) return value;
  const delta = Math.max(0, (Date.now() - ts) / 1000);
  if (delta < 60) return `${Math.round(delta)}s ago`;
  if (delta < 3600) return `${Math.round(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.round(delta / 3600)}h ago`;
  return `${Math.round(delta / 86400)}d ago`;
}

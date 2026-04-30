/**
 * Typed wrapper around `/api/v1/security/*` endpoints.
 *
 * Mirrors the Sprint 4 backend surface in
 * ``backend/app/api/security_admin.py`` and
 * ``backend/app/api/clerk_webhooks.py``. Every method takes the
 * caller's ``fetchWithAuth`` from ``useAuthFetch`` so the auth mode
 * (Clerk vs local) is transparent.
 */

import { getApiBaseUrl } from "@/lib/api-base";

export type FetchFn = (url: string, init?: RequestInit) => Promise<Response>;

export type KillSwitchSummary = {
  scope: string;
  scope_id: string | null;
  enabled: boolean;
};

export type SecurityStatus = {
  timestamp: string;
  encryption_key_dedicated: boolean;
  is_production: boolean;
  kill_switches: KillSwitchSummary[];
  audit_events_24h: number;
  audit_events_7d: number;
  approvals_pending: number;
  approvals_approved_live: number;
  consents_granted_live: number;
  creator_credentials_active: number;
  legacy_gateway_token_count: number;
  audit_retention_preview: Record<string, number>;
  missing_prerequisites: string[];
};

export type ApprovalSummary = {
  id: string;
  connector_type: string;
  requested_action: string;
  status: string;
  risk_level: string;
  organization_id: string | null;
  creator_id: string | null;
  requested_by_email: string | null;
  approved_by_email: string | null;
  expires_at: string | null;
  created_at: string;
  approved_at: string | null;
  rejected_at: string | null;
  revoked_at: string | null;
};

export type ConsentSummary = {
  id: string;
  consent_type: string;
  status: string;
  organization_id: string | null;
  creator_id: string | null;
  granted_by_email: string | null;
  granted_at: string | null;
  revoked_at: string | null;
  expires_at: string | null;
  source: string | null;
};

export type GatewayMigrationResult = {
  scanned: number;
  migrated: number;
  dry_run: boolean;
};

export type ApprovalCreateInput = {
  connector_type: string;
  requested_action: string;
  organization_id?: string | null;
  creator_id?: string | null;
  risk_level?: string;
  expires_at_iso?: string | null;
  reason?: string | null;
};

export type ConsentCreateInput = {
  consent_type: string;
  organization_id?: string | null;
  creator_id?: string | null;
  source?: string | null;
  document_reference?: string | null;
  expires_at_iso?: string | null;
  notes?: string | null;
};

export type GatePreviewResult = {
  allowed: boolean;
  reason: string;
  detail: string | null;
};

const BASE = "/api/v1/security";

async function jsonRequest<T>(
  fetchFn: FetchFn,
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetchFn(`${getApiBaseUrl()}${BASE}${path}`, init);
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const securityApi = {
  status: (f: FetchFn) => jsonRequest<SecurityStatus>(f, "/status"),
  approvals: (f: FetchFn, opts: { onlyPending?: boolean; limit?: number } = {}) => {
    const params = new URLSearchParams();
    if (opts.onlyPending) params.set("only_pending", "true");
    if (opts.limit !== undefined) params.set("limit", String(opts.limit));
    const qs = params.toString();
    return jsonRequest<ApprovalSummary[]>(f, `/approvals${qs ? `?${qs}` : ""}`);
  },
  consents: (f: FetchFn, opts: { onlyLive?: boolean; limit?: number } = {}) => {
    const params = new URLSearchParams();
    if (opts.onlyLive) params.set("only_live", "true");
    if (opts.limit !== undefined) params.set("limit", String(opts.limit));
    const qs = params.toString();
    return jsonRequest<ConsentSummary[]>(f, `/consents${qs ? `?${qs}` : ""}`);
  },
  enableKillSwitch: (
    f: FetchFn,
    body: { scope: string; scope_id?: string | null; reason?: string | null },
  ) =>
    jsonRequest<KillSwitchSummary>(f, "/kill-switches/enable", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  disableKillSwitch: (
    f: FetchFn,
    body: { scope: string; scope_id?: string | null; reason?: string | null },
  ) =>
    jsonRequest<KillSwitchSummary>(f, "/kill-switches/disable", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  approveApproval: (f: FetchFn, id: string, reason: string | null = null) =>
    jsonRequest<ApprovalSummary>(f, `/approvals/${id}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    }),
  rejectApproval: (f: FetchFn, id: string, reason: string | null = null) =>
    jsonRequest<ApprovalSummary>(f, `/approvals/${id}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    }),
  revokeApproval: (f: FetchFn, id: string, reason: string | null = null) =>
    jsonRequest<ApprovalSummary>(f, `/approvals/${id}/revoke`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    }),
  revokeConsent: (f: FetchFn, id: string, reason: string | null = null) =>
    jsonRequest<ConsentSummary>(f, `/consents/${id}/revoke`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    }),
  migrateGatewayTokens: (f: FetchFn, dryRun: boolean) =>
    jsonRequest<GatewayMigrationResult>(
      f,
      `/gateway-tokens/migrate?dry_run=${dryRun ? "true" : "false"}`,
      { method: "POST" },
    ),
  previewGate: (
    f: FetchFn,
    body: {
      connector_type: string;
      requested_action: string;
      organization_id?: string | null;
      creator_id?: string | null;
    },
  ) =>
    jsonRequest<GatePreviewResult>(f, "/connector-gate/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  createApproval: (f: FetchFn, body: ApprovalCreateInput) =>
    jsonRequest<ApprovalSummary>(f, "/approvals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  createConsent: (f: FetchFn, body: ConsentCreateInput) =>
    jsonRequest<ConsentSummary>(f, "/consents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};

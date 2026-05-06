/**
 * Read-only client for the Hermes diagnostic alert API.
 *
 * Backed by `customFetch` (Clerk-token aware) so it inherits the same auth
 * behaviour as the Orval-generated hooks. Defined manually rather than via
 * Orval so this slice doesn't require a fresh OpenAPI regeneration.
 */

import { useQuery } from "@tanstack/react-query";

import { customFetch } from "@/api/mutator";

// ── Types (mirror backend/app/schemas/hermes.py) ────────────────────────────
export type Severity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type AlertStatus =
  | "healthy"
  | "degraded"
  | "failed"
  | "blocked"
  | "rate_limited"
  | "disconnected"
  | "unknown"
  | "resolved";

export interface HermesIncident {
  alert_id: string;
  system: string;
  status: AlertStatus;
  severity: Severity;
  exact_issue: string;
  evidence: string[];
  likely_cause: string;
  business_impact: string;
  recommended_fix: string;
  claude_prompt: string;
  timestamp?: string | null;
  last_fired_at_unix?: number | null;
  failure_count?: number | null;
  first_seen?: string | null;
  resolved_at?: string | null;
}

export interface HermesSystemStatus {
  name: string;
  status: AlertStatus;
  severity?: Severity | null;
  last_alert_id?: string | null;
  last_alert_at?: string | null;
  note?: string | null;
}

export interface HermesStatus {
  overall: AlertStatus;
  summary: string;
  systems: HermesSystemStatus[];
  active_incident_count: number;
  repeated_incident_count: number;
  last_alert: HermesIncident | null;
  last_resolved: HermesIncident | null;
  state_dir_present: boolean;
  parse_warnings: number;
}

export interface HermesIncidentList {
  incidents: HermesIncident[];
  parse_warnings: number;
}

export interface HermesRepairPlan {
  alert_id: string;
  repair_mode: "manual" | "advisory";
  inspect_checklist: string[];
  recommended_next_action: string;
  claude_prompt: string;
  approval_required: boolean;
  blocked_actions: string[];
  rollback_notes: string;
}

export interface HermesSafetyRules {
  auto_inspect: string;
  auto_restart: string;
  auto_commit: string;
  auto_push: string;
  auto_deploy: string;
  secret_rotation: string;
  database_writes: string;
  onlyfans_writes: string;
  onlymonster_writes: string;
  browser_automation: string;
  restarts: string;
}

// ── React Query hooks ───────────────────────────────────────────────────────
const REFETCH_MS = 30_000;

export function useHermesStatus() {
  return useQuery<HermesStatus>({
    queryKey: ["hermes", "status"],
    queryFn: () => customFetch<HermesStatus>("/api/v1/hermes/status", { method: "GET" }),
    refetchInterval: REFETCH_MS,
    staleTime: REFETCH_MS / 2,
  });
}

export function useHermesIncidents() {
  return useQuery<HermesIncidentList>({
    queryKey: ["hermes", "incidents"],
    queryFn: () =>
      customFetch<HermesIncidentList>("/api/v1/hermes/incidents", { method: "GET" }),
    refetchInterval: REFETCH_MS,
    staleTime: REFETCH_MS / 2,
  });
}

export function useHermesRepairPlan(alertId: string | null) {
  return useQuery<HermesRepairPlan>({
    queryKey: ["hermes", "repair-plan", alertId],
    queryFn: () =>
      customFetch<HermesRepairPlan>(
        `/api/v1/hermes/repair-plan/${encodeURIComponent(alertId ?? "")}`,
        { method: "GET" },
      ),
    enabled: Boolean(alertId),
  });
}

export function useHermesSafety() {
  return useQuery<HermesSafetyRules>({
    queryKey: ["hermes", "safety"],
    queryFn: () => customFetch<HermesSafetyRules>("/api/v1/hermes/safety", { method: "GET" }),
    staleTime: 5 * 60_000,
  });
}

// ── Display helpers ─────────────────────────────────────────────────────────
export function isActive(incident: HermesIncident): boolean {
  return (
    incident.status === "failed" ||
    incident.status === "degraded" ||
    incident.status === "blocked" ||
    incident.status === "disconnected" ||
    incident.status === "rate_limited" ||
    incident.status === "unknown"
  );
}

export function severityRank(s: Severity | null | undefined): number {
  switch (s) {
    case "CRITICAL":
      return 4;
    case "HIGH":
      return 3;
    case "MEDIUM":
      return 2;
    case "LOW":
      return 1;
    default:
      return 0;
  }
}

export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString([], {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

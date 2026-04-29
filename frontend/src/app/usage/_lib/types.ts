/**
 * Usage Tracker — shared response types.
 *
 * Mirrors `backend/app/schemas/usage.py`.  Keep in sync manually for now;
 * once Orval is regenerated against the new /usage endpoints these can be
 * replaced with the auto-generated types.
 */

export type ProviderStatus = "ok" | "error" | "not_configured";
export type SnapshotSource = "live" | "manual" | "placeholder";
export type RangeKey = "24h" | "7d" | "30d" | "mtd";

export interface ProviderTotals {
  provider: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  requests: number;
  cost_usd: number;
  last_captured_at: string | null;
  last_status: ProviderStatus;
  last_error: string | null;
  last_source: SnapshotSource | null;
  configured: boolean;
}

export interface UsageOverview {
  range_key: RangeKey;
  range_start: string;
  range_end: string;
  total_cost_usd: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_requests: number;
  providers: ProviderTotals[];
  daily_threshold_usd: number | null;
  monthly_threshold_usd: number | null;
  daily_threshold_breached: boolean;
  monthly_threshold_breached: boolean;
  last_refresh_at: string | null;
}

export interface ProviderListResponse {
  providers: ProviderTotals[];
}

export interface DailyBucket {
  day: string;
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  requests: number;
}

export interface DailyUsageResponse {
  start: string;
  end: string;
  buckets: DailyBucket[];
}

export interface ProjectTotals {
  project: string | null;
  feature: string | null;
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  requests: number;
}

export interface ProjectListResponse {
  range_key: RangeKey;
  rows: ProjectTotals[];
}

export interface AlertsResponse {
  alerts_enabled: boolean;
  daily_threshold_usd: number | null;
  monthly_threshold_usd: number | null;
  daily_spend_usd: number;
  monthly_spend_usd: number;
  daily_breached: boolean;
  monthly_breached: boolean;
  last_error: string | null;
  last_error_provider: string | null;
  last_error_at: string | null;
  last_successful_check_at: string | null;
}

export interface UsageSettings {
  daily_threshold_usd: number | null;
  monthly_threshold_usd: number | null;
  alerts_enabled: boolean;
  discord_webhook_configured: boolean;
  openai_admin_configured: boolean;
  openai_admin_source: "db" | "env" | "none";
  openai_admin_preview: string | null;
  openai_org_id_set: boolean;
  openai_org_id_source: "db" | "env" | "none";
  openai_org_id_value: string | null;
  anthropic_admin_configured: boolean;
  anthropic_admin_source: "db" | "env" | "none";
  anthropic_org_id_set: boolean;
  gemini_supported: boolean;
  gemini_note: string;
}

export interface OpenAiCredentialsUpdate {
  admin_key?: string;
  org_id?: string;
}

export interface CredentialsStatus {
  admin_configured: boolean;
  admin_source: "db" | "env" | "none";
  admin_preview: string | null;
  org_id_set: boolean;
  org_id_source: "db" | "env" | "none";
  org_id_value: string | null;
}

export interface UsageSettingsUpdate {
  daily_threshold_usd?: number | null;
  monthly_threshold_usd?: number | null;
  alerts_enabled?: boolean;
}

export interface ProviderRefreshResult {
  provider: string;
  status: ProviderStatus;
  snapshot_id: string | null;
  captured_at: string | null;
  cost_usd: number;
  total_tokens: number;
  error: string | null;
  source: SnapshotSource;
}

export interface RefreshResponse {
  started_at: string;
  finished_at: string;
  results: ProviderRefreshResult[];
}

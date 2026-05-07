// X DM Bot RTxRT — shared types + fetch helpers for the detail pages.
//
// Privacy contract: nothing in this module reads, stores, or transmits
// secrets, cookies, tokens, or full user message bodies.  The only
// message field handled here is the 80-char preview the backend
// returns.

export const RT_BOT_SLUG = "x-dm-rtxrt";

export type RunStatus =
  | "draft"
  | "queued"
  | "running_scan"
  | "running_send"
  | "needs_review"
  | "approved"
  | "rejected"
  | "completed"
  | "failed"
  | "paused"
  | "archived";

export interface BotRun {
  id: string;
  bot_slug: string;
  status: RunStatus;
  mode: "sandbox" | "live";
  profile_id: string;
  profile_name: string;
  message_preview: string | null;
  target_count: number;
  sent_count: number;
  scan_count: number;
  readonly_count: number;
  elapsed_seconds: number | null;
  started_at: string | null;
  completed_at: string | null;
  created_by: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface RunOutput {
  id: string;
  output_type: "scan_summary" | "dry_run_list" | "run_log" | "error_log";
  content: unknown;
  created_at: string;
}

export interface RunDetail extends BotRun {
  outputs: RunOutput[];
}

export interface BotEntryDetail {
  slug: string;
  name: string;
  kind: string;
  description: string | null;
  enabled: boolean;
  safe_mode: boolean;
  status: string;
  last_status_detail: string | null;
  last_run_at: string | null;
  last_error_summary: string | null;
  permitted_roles: string[];
  can_operate: boolean;
  read_only_external: boolean;
}

export interface BotSettings {
  slug: string;
  name: string;
  version: string | null;
  sandbox_mode: boolean;
  live_writes_enabled: boolean;
  kill_switch_active: boolean;
  api_key_present: boolean;
}

export interface AuditEntry {
  id: string;
  actor_clerk_user_id: string;
  actor_email: string | null;
  actor_role: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  outcome: string;
  safe_summary: string | null;
  payload_hash: string | null;
  ip_address: string | null;
  created_at: string;
}

// Mock profile options for the MVP.  AdsPower profiles are NOT fetched
// — this is a hardcoded list of safe option strings.
export const MOCK_PROFILES = [
  { id: "AVAILABLE", name: "AVAILABLE" },
  { id: "CREATOR_PROFILE_1", name: "CREATOR PROFILE 1" },
  { id: "CREATOR_PROFILE_2", name: "CREATOR PROFILE 2" },
] as const;

export const MAX_PREVIEW_CHARS = 80;

export function previewOfMessage(message: string): string {
  return message.trim().slice(0, MAX_PREVIEW_CHARS);
}

export function formatRelative(iso: string | null): string {
  if (!iso) return "never";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86_400)}d ago`;
}

/**
 * Usage Tracker — fetch helpers.
 *
 * All routes hang off `/api/v1/usage/*`.  These helpers expect a
 * `fetchWithAuth`-style fetch (from `useAuthFetch`) so the Authorization
 * header is injected without leaking concerns into UI code.
 */

import { getApiBaseUrl } from "@/lib/api-base";

import type {
  AlertsResponse,
  AnthropicCredentialsUpdate,
  CredentialsStatus,
  DailyUsageResponse,
  OpenAiCredentialsUpdate,
  ProjectListResponse,
  ProviderListResponse,
  RangeKey,
  RefreshProvider,
  RefreshResponse,
  RefreshWindowHours,
  UsageOverview,
  UsageSettings,
  UsageSettingsUpdate,
} from "./types";

type FetchFn = (url: string, init?: RequestInit) => Promise<Response>;

function base(): string {
  return `${getApiBaseUrl()}/api/v1/usage`;
}

async function readJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { detail?: string } | null;
    throw new UsageApiError(res.status, body?.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export class UsageApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "UsageApiError";
  }
}

export async function fetchOverview(
  fetchFn: FetchFn,
  rangeKey: RangeKey = "7d",
): Promise<UsageOverview> {
  const res = await fetchFn(`${base()}/overview?range_key=${rangeKey}`);
  return readJson<UsageOverview>(res);
}

export async function fetchProviders(
  fetchFn: FetchFn,
  rangeKey: RangeKey = "7d",
): Promise<ProviderListResponse> {
  const res = await fetchFn(`${base()}/providers?range_key=${rangeKey}`);
  return readJson<ProviderListResponse>(res);
}

export async function fetchDaily(
  fetchFn: FetchFn,
  days = 14,
): Promise<DailyUsageResponse> {
  const res = await fetchFn(`${base()}/daily?days=${days}`);
  return readJson<DailyUsageResponse>(res);
}

export async function fetchProjects(
  fetchFn: FetchFn,
  rangeKey: RangeKey = "7d",
): Promise<ProjectListResponse> {
  const res = await fetchFn(`${base()}/projects?range_key=${rangeKey}`);
  return readJson<ProjectListResponse>(res);
}

export async function fetchAlerts(fetchFn: FetchFn): Promise<AlertsResponse> {
  const res = await fetchFn(`${base()}/alerts`);
  return readJson<AlertsResponse>(res);
}

export async function fetchSettings(fetchFn: FetchFn): Promise<UsageSettings> {
  const res = await fetchFn(`${base()}/settings`);
  return readJson<UsageSettings>(res);
}

export async function updateSettings(
  fetchFn: FetchFn,
  body: UsageSettingsUpdate,
): Promise<UsageSettings> {
  const res = await fetchFn(`${base()}/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readJson<UsageSettings>(res);
}

export async function postRefresh(
  fetchFn: FetchFn,
  options: { windowHours?: RefreshWindowHours; provider?: RefreshProvider } = {},
): Promise<RefreshResponse> {
  const params = new URLSearchParams();
  if (options.windowHours !== undefined) {
    params.set("window_hours", String(options.windowHours));
  }
  if (options.provider !== undefined) {
    params.set("provider", options.provider);
  }
  const qs = params.toString();
  const url = qs ? `${base()}/refresh?${qs}` : `${base()}/refresh`;
  const res = await fetchFn(url, { method: "POST" });
  return readJson<RefreshResponse>(res);
}

export async function saveOpenAiCredentials(
  fetchFn: FetchFn,
  body: OpenAiCredentialsUpdate,
): Promise<CredentialsStatus> {
  const res = await fetchFn(`${base()}/credentials/openai`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readJson<CredentialsStatus>(res);
}

export async function removeOpenAiCredentials(
  fetchFn: FetchFn,
): Promise<CredentialsStatus> {
  const res = await fetchFn(`${base()}/credentials/openai`, {
    method: "DELETE",
  });
  return readJson<CredentialsStatus>(res);
}

export async function saveAnthropicCredentials(
  fetchFn: FetchFn,
  body: AnthropicCredentialsUpdate,
): Promise<CredentialsStatus> {
  const res = await fetchFn(`${base()}/credentials/anthropic`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readJson<CredentialsStatus>(res);
}

export async function removeAnthropicCredentials(
  fetchFn: FetchFn,
): Promise<CredentialsStatus> {
  const res = await fetchFn(`${base()}/credentials/anthropic`, {
    method: "DELETE",
  });
  return readJson<CredentialsStatus>(res);
}

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
  DailyUsageResponse,
  ProjectListResponse,
  ProviderListResponse,
  RangeKey,
  RefreshResponse,
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

export async function postRefresh(fetchFn: FetchFn): Promise<RefreshResponse> {
  const res = await fetchFn(`${base()}/refresh`, { method: "POST" });
  return readJson<RefreshResponse>(res);
}

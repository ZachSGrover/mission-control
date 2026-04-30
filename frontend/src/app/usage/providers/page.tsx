"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useAuthFetch } from "@/hooks/use-auth-fetch";

import { EmptyState } from "../_components/EmptyState";
import { ProviderCard } from "../_components/ProviderCard";
import { RangePicker } from "../_components/RangePicker";
import { RefreshButton } from "../_components/RefreshButton";
import { RefreshWindowPicker } from "../_components/RefreshWindowPicker";
import { SetupCallout } from "../_components/SetupCallout";
import { UsagePageShell } from "../_components/UsagePageShell";
import { fetchProviders } from "../_lib/api";
import type {
  ProviderListResponse,
  RangeKey,
  RefreshWindowHours,
} from "../_lib/types";

// Render the three external providers explicitly.  "internal" lives on its
// own row at the bottom because it represents Mission Control's own logged
// calls rather than a third-party billing source.
const EXTERNAL = ["openai", "anthropic", "gemini"];

export default function UsageProvidersPage() {
  const { fetchWithAuth } = useAuthFetch();
  const [rangeKey, setRangeKey] = useState<RangeKey>("7d");
  const [refreshWindow, setRefreshWindow] = useState<RefreshWindowHours>(24);
  const [data, setData] = useState<ProviderListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (rk: RangeKey) => {
      setLoading(true);
      setError(null);
      try {
        setData(await fetchProviders(fetchWithAuth, rk));
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load providers");
      } finally {
        setLoading(false);
      }
    },
    [fetchWithAuth],
  );

  useEffect(() => {
    void load(rangeKey);
  }, [load, rangeKey]);

  const externalProviders = useMemo(() => {
    if (!data) return [];
    return EXTERNAL.map(
      (id) =>
        data.providers.find((p) => p.provider === id) ?? {
          provider: id,
          input_tokens: 0,
          output_tokens: 0,
          total_tokens: 0,
          requests: 0,
          cost_usd: 0,
          last_captured_at: null,
          last_status: "not_configured" as const,
          last_error: null,
          last_source: null,
          configured: false,
        },
    );
  }, [data]);

  const internal = useMemo(
    () => data?.providers.find((p) => p.provider === "internal"),
    [data],
  );

  const allNotConfigured = externalProviders.every((p) => !p.configured);

  return (
    <UsagePageShell
      title="Providers"
      subtitle="Per-provider spend, token volume, and health status."
      actions={
        <>
          <RangePicker value={rangeKey} onChange={setRangeKey} />
          <RefreshWindowPicker
            value={refreshWindow}
            onChange={setRefreshWindow}
          />
          <RefreshButton
            windowHours={refreshWindow}
            onRefreshed={() => void load(rangeKey)}
          />
        </>
      }
    >
      {error && (
        <div
          className="rounded-xl px-4 py-3 text-sm"
          style={{
            background: "rgba(239,68,68,0.1)",
            color: "#ef4444",
            border: "1px solid rgba(239,68,68,0.2)",
          }}
        >
          {error}
        </div>
      )}

      {!loading && allNotConfigured && data && <SetupCallout />}

      {loading && !data ? (
        <div className="grid md:grid-cols-2 gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="rounded-xl h-[260px] animate-pulse"
              style={{
                background: "var(--surface-strong)",
                border: "1px solid var(--border)",
              }}
            />
          ))}
        </div>
      ) : !data ? (
        <EmptyState
          title="No provider data yet"
          body="Press Refresh Usage to fetch the latest snapshot."
        />
      ) : (
        <>
          <section className="grid md:grid-cols-2 gap-4">
            {externalProviders.map((p) => (
              <ProviderCard key={p.provider} totals={p} />
            ))}
          </section>

          <section className="space-y-3">
            <h2
              className="text-xs font-semibold uppercase tracking-widest"
              style={{ color: "var(--text-quiet)" }}
            >
              Internal calls
            </h2>
            {internal ? (
              <ProviderCard totals={internal} />
            ) : (
              <EmptyState
                title="No internal usage logged yet"
                body="Mission Control agents will start populating this once usage logging is wired into them."
              />
            )}
          </section>
        </>
      )}
    </UsagePageShell>
  );
}

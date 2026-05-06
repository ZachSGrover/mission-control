"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, BellOff, CheckCircle2, ShieldAlert } from "lucide-react";

import { useAuthFetch } from "@/hooks/use-auth-fetch";

import { EmptyState } from "../_components/EmptyState";
import { RefreshButton } from "../_components/RefreshButton";
import { StatCard } from "../_components/StatCard";
import { UsagePageShell } from "../_components/UsagePageShell";
import { fetchAlerts } from "../_lib/api";
import { formatRelative, formatUsd } from "../_lib/format";
import type { AlertsResponse } from "../_lib/types";

type Severity = "critical" | "warning" | "info";

interface DerivedAlert {
  id: string;
  severity: Severity;
  provider: string | null;
  project: string | null;
  title: string;
  message: string;
  suggestedAction: string;
  status: "active" | "resolved";
  createdAt: string | null;
}

const SEVERITY_STYLES: Record<Severity, { bg: string; color: string; border: string }> = {
  critical: {
    bg: "rgba(239,68,68,0.1)",
    color: "#ef4444",
    border: "rgba(239,68,68,0.25)",
  },
  warning: {
    bg: "rgba(245,158,11,0.1)",
    color: "#f59e0b",
    border: "rgba(245,158,11,0.25)",
  },
  info: {
    bg: "rgba(59,130,246,0.08)",
    color: "#3b82f6",
    border: "rgba(59,130,246,0.25)",
  },
};

const SEVERITY_ICON: Record<Severity, typeof AlertTriangle> = {
  critical: AlertTriangle,
  warning: ShieldAlert,
  info: BellOff,
};

function deriveAlerts(data: AlertsResponse): DerivedAlert[] {
  const alerts: DerivedAlert[] = [];

  if (data.daily_breached) {
    alerts.push({
      id: "daily-threshold",
      severity: "critical",
      provider: null,
      project: null,
      title: "Daily spend threshold exceeded",
      message: `24h spend ${formatUsd(data.daily_spend_usd)} is above the configured limit of ${formatUsd(
        data.daily_threshold_usd,
      )}.`,
      suggestedAction:
        "Investigate which provider is responsible on the Providers page and pause non-critical agents.",
      status: "active",
      createdAt: null,
    });
  }

  if (data.monthly_breached) {
    alerts.push({
      id: "monthly-threshold",
      severity: "warning",
      provider: null,
      project: null,
      title: "Monthly spend threshold exceeded",
      message: `Month-to-date spend ${formatUsd(data.monthly_spend_usd)} is above the configured limit of ${formatUsd(
        data.monthly_threshold_usd,
      )}.`,
      suggestedAction:
        "Review project-level rollups and revisit the monthly cap in Settings.",
      status: "active",
      createdAt: null,
    });
  }

  if (data.last_error) {
    alerts.push({
      id: "last-error",
      severity: "warning",
      provider: data.last_error_provider ?? null,
      project: null,
      title: "Provider snapshot returned an error",
      message: data.last_error,
      suggestedAction:
        "Verify admin key and org ID for this provider in Usage Settings, then trigger Refresh Usage.",
      status: "active",
      createdAt: data.last_error_at,
    });
  }

  return alerts;
}

export default function UsageAlertsPage() {
  const { fetchWithAuth } = useAuthFetch();
  const [data, setData] = useState<AlertsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchAlerts(fetchWithAuth));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load alerts");
    } finally {
      setLoading(false);
    }
  }, [fetchWithAuth]);

  useEffect(() => {
    void load();
  }, [load]);

  const alerts = useMemo(() => (data ? deriveAlerts(data) : []), [data]);

  return (
    <UsagePageShell
      title="Alerts"
      subtitle="Threshold breaches and provider check failures."
      actions={<RefreshButton onRefreshed={() => void load()} />}
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

      {/* KPI strip */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          label="Alerts enabled"
          value={data ? (data.alerts_enabled ? "On" : "Off") : "—"}
          tone={data?.alerts_enabled ? "default" : "muted"}
          hint={
            data?.alerts_enabled
              ? "Threshold checks are active"
              : "Toggle on in Settings to start receiving alerts"
          }
        />
        <StatCard
          label="Daily spend"
          value={formatUsd(data?.daily_spend_usd ?? 0)}
          tone={data?.daily_breached ? "danger" : "default"}
          hint={
            data?.daily_threshold_usd === null || data?.daily_threshold_usd === undefined
              ? "No daily threshold set"
              : `Limit ${formatUsd(data.daily_threshold_usd)}`
          }
        />
        <StatCard
          label="Monthly spend"
          value={formatUsd(data?.monthly_spend_usd ?? 0)}
          tone={data?.monthly_breached ? "danger" : "default"}
          hint={
            data?.monthly_threshold_usd === null || data?.monthly_threshold_usd === undefined
              ? "No monthly threshold set"
              : `Limit ${formatUsd(data.monthly_threshold_usd)}`
          }
        />
        <StatCard
          label="Last successful check"
          value={formatRelative(data?.last_successful_check_at)}
          hint="Last green snapshot from any provider"
        />
      </section>

      {/* Alerts list */}
      {loading && !data ? (
        <div
          className="rounded-xl h-[160px] animate-pulse"
          style={{
            background: "var(--surface-strong)",
            border: "1px solid var(--border)",
          }}
        />
      ) : alerts.length === 0 ? (
        <EmptyState
          icon={<CheckCircle2 className="h-5 w-5" />}
          title="No active alerts"
          body="When daily or monthly thresholds are breached, or a provider snapshot fails, you'll see them listed here."
        />
      ) : (
        <section className="space-y-3">
          {alerts.map((alert) => (
            <AlertCard key={alert.id} alert={alert} />
          ))}
        </section>
      )}

      <p className="text-xs" style={{ color: "var(--text-quiet)" }}>
        Discord webhook delivery is on the Phase 3 roadmap; alerts are
        currently surface-only.
      </p>
    </UsagePageShell>
  );
}

function AlertCard({ alert }: { alert: DerivedAlert }) {
  const Icon = SEVERITY_ICON[alert.severity];
  const styles = SEVERITY_STYLES[alert.severity];
  return (
    <div
      className="rounded-xl px-4 py-4"
      style={{
        background: styles.bg,
        border: `1px solid ${styles.border}`,
      }}
    >
      <div className="flex items-start gap-3">
        <Icon
          className="h-4 w-4 mt-0.5 shrink-0"
          style={{ color: styles.color }}
        />
        <div className="flex-1 min-w-0 space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className="text-[10px] font-semibold uppercase tracking-widest"
              style={{ color: styles.color }}
            >
              {alert.severity}
            </span>
            {alert.provider && (
              <span
                className="text-[10px] font-medium uppercase tracking-wide rounded-full px-2 py-0.5"
                style={{
                  background: "var(--surface)",
                  color: "var(--text-muted)",
                }}
              >
                {alert.provider}
              </span>
            )}
            {alert.project && (
              <span
                className="text-[10px] font-medium uppercase tracking-wide rounded-full px-2 py-0.5"
                style={{
                  background: "var(--surface)",
                  color: "var(--text-muted)",
                }}
              >
                {alert.project}
              </span>
            )}
            <span className="text-[10px]" style={{ color: "var(--text-quiet)" }}>
              {alert.createdAt ? formatRelative(alert.createdAt) : "now"}
            </span>
          </div>
          <p className="text-sm font-medium" style={{ color: "var(--text)" }}>
            {alert.title}
          </p>
          <p className="text-xs" style={{ color: "var(--text-muted)" }}>
            {alert.message}
          </p>
          <p
            className="text-xs"
            style={{ color: "var(--text)" }}
          >
            <span
              className="font-semibold"
              style={{ color: "var(--text-quiet)" }}
            >
              Suggested action:
            </span>{" "}
            {alert.suggestedAction}
          </p>
        </div>
      </div>
    </div>
  );
}

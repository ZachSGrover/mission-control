"use client";

/**
 * SystemStatusBar — compact top-level health strip for the Mission Control dashboard.
 *
 * Checks five services the operator needs at-a-glance:
 *   • backend       → GET {API}/health
 *   • next-server   → implicitly "up" if this component renders
 *   • telegram      → GET /api/v1/telegram/config    (has_token)
 *   • discord       → GET /api/v1/discord/status     (connected)
 *   • openai        → GET /api/v1/settings/api-keys  (openai.configured)
 *
 * Pure fetches (no generated client) so it won't break on schema drift.
 */

import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";

import { getApiBaseUrl } from "@/lib/api-base";
import { useAuthFetch } from "@/hooks/use-auth-fetch";

type State = "ok" | "down" | "off" | "checking";

type ServiceStatus = {
  key:    "backend" | "next" | "telegram" | "discord" | "openai";
  label:  string;
  state:  State;
  detail: string;
};

type MessagingMetrics = {
  total_count:      number;
  avg_ms_last_10:   number | null;
  telegram_avg_ms:  number | null;
  telegram_last_at: number | null;
  telegram_count:   number;
  discord_avg_ms:   number | null;
  discord_last_at:  number | null;
  discord_count:    number;
  ai_call_ratio_pct:number;
};

const toneFor = (state: State): string => {
  switch (state) {
    case "ok":
      return "bg-emerald-50 text-emerald-700 border-emerald-200";
    case "down":
      return "bg-rose-50 text-rose-700 border-rose-200";
    case "off":
      return "bg-slate-100 text-slate-500 border-slate-200";
    case "checking":
    default:
      return "bg-slate-50 text-slate-400 border-slate-200";
  }
};

const dotFor = (state: State): string => {
  switch (state) {
    case "ok":       return "bg-emerald-500";
    case "down":     return "bg-rose-500";
    case "off":      return "bg-slate-400";
    case "checking":
    default:         return "bg-slate-300 animate-pulse";
  }
};

function Pill({ status }: { status: ServiceStatus }) {
  return (
    <div
      className={`flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-medium ${toneFor(status.state)}`}
      title={status.detail}
    >
      <span className={`h-2 w-2 rounded-full ${dotFor(status.state)}`} />
      <span className="uppercase tracking-wide">{status.label}</span>
      <span className="text-[11px] opacity-75">{status.detail}</span>
    </div>
  );
}

export function SystemStatusBar() {
  const { fetchWithAuth } = useAuthFetch();
  const [statuses, setStatuses] = useState<ServiceStatus[]>([
    { key: "backend",  label: "Backend",  state: "checking", detail: "…"      },
    { key: "next",     label: "Next",     state: "ok",       detail: "serving"},
    { key: "telegram", label: "Telegram", state: "checking", detail: "…"      },
    { key: "discord",  label: "Discord",  state: "checking", detail: "…"      },
    { key: "openai",   label: "OpenAI",   state: "checking", detail: "…"      },
  ]);
  const [loading, setLoading] = useState(false);
  const [lastChecked, setLastChecked] = useState<string>("");
  const [metrics, setMetrics] = useState<MessagingMetrics | null>(null);
  const [network, setNetwork] = useState<{
    is_online: boolean | null;
    last_online_at: number | null;
    last_offline_at: number | null;
  } | null>(null);
  const [tgMode, setTgMode] = useState<{ mode: string; polling_active: boolean } | null>(null);

  const update = useCallback(
    (key: ServiceStatus["key"], state: State, detail: string) => {
      setStatuses((prev) =>
        prev.map((s) => (s.key === key ? { ...s, state, detail } : s)),
      );
    },
    [],
  );

  const check = useCallback(async () => {
    setLoading(true);
    const base = getApiBaseUrl();

    // 1. backend /health — no auth required
    void (async () => {
      try {
        const res = await fetch(`${base}/health`, { cache: "no-store" });
        if (res.ok) update("backend", "ok", "healthy");
        else         update("backend", "down", `HTTP ${res.status}`);
      } catch (err) {
        update("backend", "down", err instanceof Error ? err.message : "unreachable");
      }
    })();

    // 2. telegram config
    void (async () => {
      try {
        const res = await fetchWithAuth(`${base}/api/v1/telegram/config`);
        if (!res.ok) {
          update("telegram", "down", `HTTP ${res.status}`);
          return;
        }
        const data = (await res.json()) as {
          has_token: boolean; bot_username: string | null; source: string;
        };
        if (!data.has_token) update("telegram", "off", "no token");
        else                 update("telegram", "ok", data.bot_username ? `@${data.bot_username}` : data.source);
      } catch (err) {
        update("telegram", "down", err instanceof Error ? err.message : "error");
      }
    })();

    // 3. discord status
    void (async () => {
      try {
        const res = await fetchWithAuth(`${base}/api/v1/discord/status`);
        if (!res.ok) {
          update("discord", "down", `HTTP ${res.status}`);
          return;
        }
        const data = (await res.json()) as {
          connected: boolean; bot_username: string | null; detail: string;
        };
        if (!data.connected) update("discord", "off", data.detail || "offline");
        else                 update("discord", "ok", data.bot_username ? `@${data.bot_username}` : data.detail || "connected");
      } catch (err) {
        update("discord", "down", err instanceof Error ? err.message : "error");
      }
    })();

    // 4. openai via settings/api-keys
    void (async () => {
      try {
        const res = await fetchWithAuth(`${base}/api/v1/settings/api-keys`);
        if (!res.ok) {
          update("openai", "down", `HTTP ${res.status}`);
          return;
        }
        const data = (await res.json()) as {
          openai: { configured: boolean; preview: string | null; source: string };
        };
        if (!data.openai?.configured) update("openai", "off", "no key");
        else                           update("openai", "ok", data.openai.source);
      } catch (err) {
        update("openai", "down", err instanceof Error ? err.message : "error");
      }
    })();

    // 5. messaging metrics (non-blocking; failure is fine)
    void (async () => {
      try {
        const res = await fetchWithAuth(`${base}/api/v1/messaging/metrics`);
        if (!res.ok) return;
        const data = (await res.json()) as MessagingMetrics;
        setMetrics(data);
      } catch {
        /* ignore — metrics are optional UI sugar */
      }
    })();

    // 6. network state (public /system/network)
    void (async () => {
      try {
        const res = await fetch(`${base}/api/v1/system/network`, { cache: "no-store" });
        if (!res.ok) return;
        setNetwork(await res.json());
      } catch { /* ignore */ }
    })();

    // 7. telegram mode (public /system/telegram-mode)
    void (async () => {
      try {
        const res = await fetch(`${base}/api/v1/system/telegram-mode`, { cache: "no-store" });
        if (!res.ok) return;
        setTgMode(await res.json());
      } catch { /* ignore */ }
    })();

    setLoading(false);
    setLastChecked(new Date().toLocaleTimeString());
  }, [fetchWithAuth, update]);

  useEffect(() => {
    // Initial poll + 30s interval; check() updates state from network result.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void check();
    const id = window.setInterval(() => void check(), 30_000);
    return () => window.clearInterval(id);
  }, [check]);

  return (
    <section className="mb-4 rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
      <div className="flex items-center justify-between gap-3 mb-2">
        <div className="flex items-center gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            System Status
          </h3>
          {lastChecked && (
            <span className="text-[11px] text-slate-400">checked {lastChecked}</span>
          )}
        </div>
        <button
          type="button"
          onClick={() => void check()}
          disabled={loading}
          className="flex items-center gap-1 text-[11px] text-slate-400 hover:text-slate-600 transition-colors disabled:opacity-40"
        >
          <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>
      <div className="flex flex-wrap gap-2">
        {statuses.map((s) => (
          <Pill key={s.key} status={s} />
        ))}
        {network && (
          <Pill
            status={{
              key: "backend",
              label: "Internet",
              state:
                network.is_online === null
                  ? "checking"
                  : network.is_online
                    ? "ok"
                    : "down",
              detail:
                network.is_online === false && network.last_online_at
                  ? `offline · back ${formatRelative(network.last_online_at)}`
                  : network.is_online && network.last_offline_at
                    ? `reconnected ${formatRelative(network.last_offline_at)}`
                    : network.is_online === null
                      ? "probing"
                      : "online",
            }}
          />
        )}
        {tgMode && (
          <Pill
            status={{
              key: "telegram",
              label: "TG mode",
              state:
                tgMode.mode === "polling"
                  ? "down"
                  : tgMode.mode === "webhook"
                    ? "ok"
                    : "off",
              detail: tgMode.polling_active ? "polling (fallback)" : tgMode.mode,
            }}
          />
        )}
      </div>

      {metrics && metrics.total_count > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-slate-100 pt-2 text-[11px] text-slate-500">
          <span>
            <span className="uppercase tracking-wide text-slate-400">Avg (last 10)</span>{" "}
            <span className="font-mono font-medium text-slate-700">
              {metrics.avg_ms_last_10 !== null ? `${metrics.avg_ms_last_10.toFixed(0)} ms` : "—"}
            </span>
          </span>
          <span>
            <span className="uppercase tracking-wide text-slate-400">Telegram</span>{" "}
            <span className="font-mono text-slate-700">
              {metrics.telegram_count > 0
                ? `${(metrics.telegram_avg_ms ?? 0).toFixed(0)} ms · ${formatRelative(metrics.telegram_last_at)}`
                : "no messages yet"}
            </span>
          </span>
          <span>
            <span className="uppercase tracking-wide text-slate-400">Discord</span>{" "}
            <span className="font-mono text-slate-700">
              {metrics.discord_count > 0
                ? `${(metrics.discord_avg_ms ?? 0).toFixed(0)} ms · ${formatRelative(metrics.discord_last_at)}`
                : "no messages yet"}
            </span>
          </span>
          <span>
            <span className="uppercase tracking-wide text-slate-400">AI calls</span>{" "}
            <span className="font-mono text-slate-700">{metrics.ai_call_ratio_pct.toFixed(0)}%</span>
          </span>
        </div>
      )}
    </section>
  );
}

function formatRelative(ts: number | null): string {
  if (ts === null) return "—";
  const now = Date.now() / 1000;
  const delta = Math.max(0, now - ts);
  if (delta < 60)    return `${Math.round(delta)}s ago`;
  if (delta < 3600)  return `${Math.round(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.round(delta / 3600)}h ago`;
  return `${Math.round(delta / 86400)}d ago`;
}

"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";
import { Check, Info } from "lucide-react";

import { useAuthFetch } from "@/hooks/use-auth-fetch";

import { UsagePageShell } from "../_components/UsagePageShell";
import { fetchSettings, updateSettings } from "../_lib/api";
import type { UsageSettings, UsageSettingsUpdate } from "../_lib/types";

export default function UsageSettingsPage() {
  const { fetchWithAuth } = useAuthFetch();
  const [data, setData] = useState<UsageSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState<{ ok: boolean; msg: string } | null>(
    null,
  );

  // Local form state.  Synced from server response on load and after each
  // save so the inputs stay authoritative without re-fetching.
  const [dailyInput, setDailyInput] = useState<string>("");
  const [monthlyInput, setMonthlyInput] = useState<string>("");
  const [alertsEnabled, setAlertsEnabled] = useState<boolean>(false);

  const applyServer = useCallback((s: UsageSettings) => {
    setData(s);
    setDailyInput(s.daily_threshold_usd === null ? "" : String(s.daily_threshold_usd));
    setMonthlyInput(
      s.monthly_threshold_usd === null ? "" : String(s.monthly_threshold_usd),
    );
    setAlertsEnabled(s.alerts_enabled);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      applyServer(await fetchSettings(fetchWithAuth));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load settings");
    } finally {
      setLoading(false);
    }
  }, [applyServer, fetchWithAuth]);

  useEffect(() => {
    void load();
  }, [load]);

  const flash = useCallback((ok: boolean, msg: string) => {
    setFeedback({ ok, msg });
    setTimeout(() => setFeedback(null), 3000);
  }, []);

  const save = useCallback(async () => {
    if (!data) return;
    setSaving(true);
    try {
      const payload: UsageSettingsUpdate = {
        daily_threshold_usd:
          dailyInput.trim() === "" ? null : Number(dailyInput),
        monthly_threshold_usd:
          monthlyInput.trim() === "" ? null : Number(monthlyInput),
        alerts_enabled: alertsEnabled,
      };
      const next = await updateSettings(fetchWithAuth, payload);
      applyServer(next);
      flash(true, "Saved.");
    } catch (e) {
      flash(false, e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }, [
    alertsEnabled,
    applyServer,
    data,
    dailyInput,
    fetchWithAuth,
    flash,
    monthlyInput,
  ]);

  return (
    <UsagePageShell
      title="Usage settings"
      subtitle="Configure spend thresholds and provider admin credentials."
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

      <Callout>
        Provider admin usage requires <strong>admin keys</strong> and{" "}
        <strong>organization IDs</strong> — these are different from the
        regular API keys used for inference. Set them as environment
        variables (<code className="font-mono">OPENAI_ADMIN_KEY</code>,{" "}
        <code className="font-mono">OPENAI_ORG_ID</code>,{" "}
        <code className="font-mono">ANTHROPIC_ADMIN_KEY</code>,{" "}
        <code className="font-mono">ANTHROPIC_ORG_ID</code>) or add them to
        the database via the existing Settings → API Keys flow under the{" "}
        <code className="font-mono">admin_key.openai</code> /{" "}
        <code className="font-mono">admin_key.anthropic</code> keys.
      </Callout>

      {/* Thresholds + alerts */}
      <section className="space-y-3">
        <h2
          className="text-xs font-semibold uppercase tracking-widest"
          style={{ color: "var(--text-quiet)" }}
        >
          Spend thresholds
        </h2>

        <div
          className="rounded-xl p-4 space-y-4"
          style={{
            background: "var(--surface-strong)",
            border: "1px solid var(--border)",
          }}
        >
          <NumberField
            label="Daily threshold (USD)"
            hint="Triggers an alert when 24-hour spend crosses this amount. Leave blank to disable."
            value={dailyInput}
            onChange={setDailyInput}
            disabled={loading || saving}
            placeholder="e.g. 5"
          />
          <NumberField
            label="Monthly threshold (USD)"
            hint="Triggers an alert when month-to-date spend crosses this amount. Leave blank to disable."
            value={monthlyInput}
            onChange={setMonthlyInput}
            disabled={loading || saving}
            placeholder="e.g. 150"
          />
          <ToggleRow
            label="Alerts enabled"
            hint="When off, thresholds are evaluated but no alerts surface."
            value={alertsEnabled}
            onChange={setAlertsEnabled}
            disabled={loading || saving}
          />

          <div className="flex items-center justify-between">
            <p
              className="text-xs"
              style={{
                color: feedback
                  ? feedback.ok
                    ? "#22c55e"
                    : "#ef4444"
                  : "var(--text-quiet)",
              }}
            >
              {feedback?.msg ?? ""}
            </p>
            <button
              type="button"
              onClick={() => void save()}
              disabled={loading || saving}
              className="rounded-lg px-4 py-2 text-sm font-medium text-white transition-opacity disabled:opacity-40"
              style={{ background: "var(--accent)" }}
            >
              {saving ? "Saving…" : "Save thresholds"}
            </button>
          </div>
        </div>
      </section>

      {/* Provider admin status */}
      <section className="space-y-3">
        <h2
          className="text-xs font-semibold uppercase tracking-widest"
          style={{ color: "var(--text-quiet)" }}
        >
          Provider admin keys
        </h2>

        <div
          className="rounded-xl divide-y"
          style={{
            background: "var(--surface-strong)",
            border: "1px solid var(--border)",
          }}
        >
          <ProviderRow
            label="OpenAI"
            help="Required for live OpenAI billing snapshots."
            keyConfigured={!!data?.openai_admin_configured}
            keySource={data?.openai_admin_source ?? "none"}
            orgIdSet={!!data?.openai_org_id_set}
            envHints={["OPENAI_ADMIN_KEY", "OPENAI_ORG_ID"]}
          />
          <ProviderRow
            label="Anthropic"
            help="Required for live Anthropic message-usage snapshots."
            keyConfigured={!!data?.anthropic_admin_configured}
            keySource={data?.anthropic_admin_source ?? "none"}
            orgIdSet={!!data?.anthropic_org_id_set}
            envHints={["ANTHROPIC_ADMIN_KEY", "ANTHROPIC_ORG_ID"]}
          />
          <ProviderRow
            label="Gemini"
            help={
              data?.gemini_note ??
              "Google does not yet expose a public Gemini usage API."
            }
            keyConfigured={false}
            keySource="none"
            orgIdSet={false}
            envHints={[]}
            unsupported
          />
        </div>
      </section>

      {/* Discord webhook placeholder */}
      <section className="space-y-3">
        <h2
          className="text-xs font-semibold uppercase tracking-widest"
          style={{ color: "var(--text-quiet)" }}
        >
          Discord webhook
        </h2>
        <div
          className="rounded-xl p-4 space-y-2"
          style={{
            background: "var(--surface-strong)",
            border: "1px solid var(--border)",
          }}
        >
          <div className="flex items-center justify-between gap-3">
            <div>
              <p
                className="text-sm font-medium"
                style={{ color: "var(--text)" }}
              >
                Discord webhook
              </p>
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                Coming in Phase 3 — alert delivery to a Discord channel via
                incoming webhook URL.
              </p>
            </div>
            <span
              className="text-[10px] font-semibold uppercase tracking-widest rounded-full px-2 py-0.5"
              style={{
                background: "var(--surface)",
                color: "var(--text-quiet)",
                border: "1px solid var(--border)",
              }}
            >
              {data?.discord_webhook_configured ? "configured" : "not yet"}
            </span>
          </div>
        </div>
      </section>
    </UsagePageShell>
  );
}

function Callout({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="rounded-xl px-4 py-3 flex gap-3 items-start text-sm"
      style={{
        background: "rgba(59,130,246,0.06)",
        border: "1px solid rgba(59,130,246,0.2)",
        color: "var(--text)",
      }}
    >
      <Info
        className="h-4 w-4 shrink-0 mt-0.5"
        style={{ color: "#3b82f6" }}
      />
      <p style={{ color: "var(--text-muted)" }}>{children}</p>
    </div>
  );
}

function NumberField({
  label,
  hint,
  value,
  onChange,
  disabled,
  placeholder,
}: {
  label: string;
  hint: string;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  placeholder?: string;
}) {
  return (
    <div className="space-y-1.5">
      <label className="block">
        <span
          className="text-xs font-medium"
          style={{ color: "var(--text)" }}
        >
          {label}
        </span>
      </label>
      <input
        type="number"
        inputMode="decimal"
        min={0}
        step="0.01"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        placeholder={placeholder}
        className="w-full rounded-lg px-3 py-2 text-sm font-mono focus:outline-none disabled:opacity-50"
        style={{
          background: "var(--surface-muted, var(--surface))",
          border: "1px solid var(--border-strong, var(--border))",
          color: "var(--text)",
        }}
      />
      <p className="text-[11px]" style={{ color: "var(--text-quiet)" }}>
        {hint}
      </p>
    </div>
  );
}

function ToggleRow({
  label,
  hint,
  value,
  onChange,
  disabled,
}: {
  label: string;
  hint: string;
  value: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div>
        <p className="text-sm font-medium" style={{ color: "var(--text)" }}>
          {label}
        </p>
        <p className="text-[11px]" style={{ color: "var(--text-quiet)" }}>
          {hint}
        </p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={value}
        disabled={disabled}
        onClick={() => onChange(!value)}
        className="relative inline-flex h-5 w-9 items-center rounded-full transition-colors disabled:opacity-50"
        style={{
          background: value ? "var(--accent)" : "var(--surface)",
          border: "1px solid var(--border)",
        }}
      >
        <span
          className="inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform"
          style={{
            transform: value ? "translateX(18px)" : "translateX(2px)",
          }}
        />
      </button>
    </div>
  );
}

function ProviderRow({
  label,
  help,
  keyConfigured,
  keySource,
  orgIdSet,
  envHints,
  unsupported,
}: {
  label: string;
  help: string;
  keyConfigured: boolean;
  keySource: "db" | "env" | "none";
  orgIdSet: boolean;
  envHints: string[];
  unsupported?: boolean;
}) {
  const ready = keyConfigured && orgIdSet;
  return (
    <div className="px-4 py-4 flex flex-col md:flex-row md:items-center md:justify-between gap-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <p
            className="text-sm font-medium"
            style={{ color: "var(--text)" }}
          >
            {label}
          </p>
          {unsupported ? (
            <Pill tone="muted">Not yet supported</Pill>
          ) : ready ? (
            <Pill tone="ok">
              <Check className="h-3 w-3" />
              Ready
            </Pill>
          ) : (
            <Pill tone="warn">Setup needed</Pill>
          )}
        </div>
        <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
          {help}
        </p>
      </div>
      <div className="flex flex-col items-start md:items-end gap-1 text-xs shrink-0">
        {!unsupported && (
          <>
            <span style={{ color: "var(--text-muted)" }}>
              Admin key:{" "}
              <span style={{ color: "var(--text)" }}>
                {keyConfigured
                  ? `Configured (${keySource})`
                  : "Not configured"}
              </span>
            </span>
            <span style={{ color: "var(--text-muted)" }}>
              Org ID:{" "}
              <span style={{ color: "var(--text)" }}>
                {orgIdSet ? "Set" : "Not set"}
              </span>
            </span>
            {envHints.length > 0 && (
              <span
                className="font-mono text-[10px]"
                style={{ color: "var(--text-quiet)" }}
              >
                {envHints.join(", ")}
              </span>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Pill({
  children,
  tone,
}: {
  children: React.ReactNode;
  tone: "ok" | "warn" | "muted";
}) {
  const styles =
    tone === "ok"
      ? { bg: "rgba(34,197,94,0.12)", color: "#22c55e" }
      : tone === "warn"
      ? { bg: "rgba(245,158,11,0.12)", color: "#f59e0b" }
      : { bg: "var(--surface)", color: "var(--text-quiet)" };
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-widest"
      style={{ background: styles.bg, color: styles.color }}
    >
      {children}
    </span>
  );
}

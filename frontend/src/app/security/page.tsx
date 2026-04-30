"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, RefreshCw, ShieldCheck, ShieldAlert } from "lucide-react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import {
  securityApi,
  type ApprovalSummary,
  type ConsentSummary,
  type SecurityStatus,
} from "@/lib/security/api";

// ── Page ─────────────────────────────────────────────────────────────────────

export default function SecurityPage() {
  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel
          message="Sign in to access security admin."
          forceRedirectUrl="/security"
        />
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <RoleGuard
          require="owner"
          fallback={<LoadingFrame />}
          denied={<DeniedFrame />}
        >
          <SecurityAdmin />
        </RoleGuard>
      </SignedIn>
    </DashboardShell>
  );
}

function LoadingFrame() {
  return (
    <main className="flex-1 overflow-y-auto p-6" style={{ background: "var(--bg)" }}>
      <p style={{ color: "var(--text-muted)" }}>Loading…</p>
    </main>
  );
}

function DeniedFrame() {
  return (
    <main className="flex-1 overflow-y-auto p-6" style={{ background: "var(--bg)" }}>
      <div
        className="rounded-xl border p-6"
        style={{ background: "var(--surface)", borderColor: "var(--border)" }}
      >
        <p className="text-base font-semibold" style={{ color: "var(--text)" }}>
          Owner role required
        </p>
        <p className="text-sm mt-2" style={{ color: "var(--text-muted)" }}>
          Security admin is restricted to the owner role.
        </p>
      </div>
    </main>
  );
}

function SecurityAdmin() {
  const { fetchWithAuth } = useAuthFetch();
  const [status, setStatus] = useState<SecurityStatus | null>(null);
  const [approvals, setApprovals] = useState<ApprovalSummary[]>([]);
  const [consents, setConsents] = useState<ConsentSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [s, a, c] = await Promise.all([
        securityApi.status(fetchWithAuth),
        securityApi.approvals(fetchWithAuth, { limit: 25 }),
        securityApi.consents(fetchWithAuth, { limit: 25 }),
      ]);
      setStatus(s);
      setApprovals(a);
      setConsents(c);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [fetchWithAuth]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onToggleGlobalKillSwitch = async (enable: boolean) => {
    setBusy(true);
    try {
      const op = enable ? securityApi.enableKillSwitch : securityApi.disableKillSwitch;
      await op(fetchWithAuth, { scope: "global", reason: enable ? "manual enable" : "manual disable" });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const onApprovalAction = async (
    id: string,
    op: "approve" | "reject" | "revoke",
  ) => {
    setBusy(true);
    try {
      const fn =
        op === "approve"
          ? securityApi.approveApproval
          : op === "reject"
          ? securityApi.rejectApproval
          : securityApi.revokeApproval;
      await fn(fetchWithAuth, id);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const onConsentRevoke = async (id: string) => {
    setBusy(true);
    try {
      await securityApi.revokeConsent(fetchWithAuth, id);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const onMigrateGatewayTokens = async (dryRun: boolean) => {
    setBusy(true);
    try {
      const r = await securityApi.migrateGatewayTokens(fetchWithAuth, dryRun);
      await refresh();
      alert(
        `Gateway token migration${dryRun ? " (dry-run)" : ""}: scanned=${r.scanned} migrated=${r.migrated}`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const globalKill = status?.kill_switches.find((k) => k.scope === "global" && !k.scope_id);

  return (
    <main className="flex-1 overflow-y-auto" style={{ background: "var(--bg)" }}>
      <div className="px-6 pt-6 pb-3 border-b" style={{ borderColor: "var(--border)" }}>
        <p className="text-[11px] font-semibold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>
          Security
        </p>
        <h1 className="text-xl font-semibold mt-0.5" style={{ color: "var(--text)" }}>
          Security admin
        </h1>
        <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
          Live state of the prevention controls. Owner-only. Every action audits.
        </p>
      </div>

      <div className="p-6 space-y-6">
        {error && (
          <div
            className="rounded-md border p-3 text-sm flex items-center gap-2"
            style={{ borderColor: "rgb(248,113,113)", color: "rgb(225,29,72)" }}
          >
            <AlertTriangle className="h-4 w-4" />
            {error}
          </div>
        )}

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading || busy}
            className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
            style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
        </div>

        {/* Top stats */}
        {status && (
          <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Stat label="Production" value={status.is_production ? "yes" : "no"} tone={status.is_production ? "ok" : "muted"} />
            <Stat label="Encryption key dedicated" value={status.encryption_key_dedicated ? "yes" : "NO"} tone={status.encryption_key_dedicated ? "ok" : "bad"} />
            <Stat label="Audit events 24h" value={String(status.audit_events_24h)} />
            <Stat label="Legacy gateway tokens" value={String(status.legacy_gateway_token_count)} tone={status.legacy_gateway_token_count > 0 ? "bad" : "ok"} />
          </section>
        )}

        {/* Global kill switch */}
        {status && (
          <Card title="Global kill switch" hint={globalKill?.enabled ? "ENABLED — every connector blocked" : "disabled"}>
            <div className="flex items-center gap-3">
              {globalKill?.enabled ? (
                <ShieldAlert className="h-5 w-5" style={{ color: "rgb(190,18,60)" }} />
              ) : (
                <ShieldCheck className="h-5 w-5" style={{ color: "rgb(5,150,105)" }} />
              )}
              <p className="text-sm" style={{ color: "var(--text)" }}>
                Status: <strong>{globalKill?.enabled ? "ENABLED" : "disabled"}</strong>
              </p>
              {globalKill?.enabled ? (
                <button
                  type="button"
                  onClick={() => void onToggleGlobalKillSwitch(false)}
                  disabled={busy}
                  className="ml-auto rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
                  style={{ borderColor: "var(--border)", color: "var(--text)" }}
                >
                  Disable
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    if (confirm("Enable the GLOBAL kill switch? Every connector and automation will be blocked until disabled.")) {
                      void onToggleGlobalKillSwitch(true);
                    }
                  }}
                  disabled={busy}
                  className="ml-auto rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50"
                  style={{ background: "rgb(190,18,60)", color: "white" }}
                >
                  Enable kill switch
                </button>
              )}
            </div>
            <p className="text-xs mt-2" style={{ color: "var(--text-quiet)" }}>
              Toggling the global kill switch is the highest-stakes action in the system. Every toggle is audited at severity <em>critical</em>.
            </p>
          </Card>
        )}

        {/* All kill switches */}
        {status && status.kill_switches.length > 0 && (
          <Card title="All kill switches" hint={`${status.kill_switches.length} total`}>
            <ul className="space-y-1 text-sm">
              {status.kill_switches.map((k) => (
                <li key={`${k.scope}:${k.scope_id ?? ""}`} className="flex items-center gap-2">
                  <span className={k.enabled ? "font-semibold" : ""} style={{ color: k.enabled ? "rgb(190,18,60)" : "var(--text-muted)" }}>
                    {k.enabled ? "ENABLED" : "disabled"}
                  </span>
                  <span style={{ color: "var(--text)" }}>
                    {k.scope}
                    {k.scope_id ? `:${k.scope_id}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        )}

        {/* Connector approvals */}
        <Card title="Connector approvals" hint={`${approvals.length} recent`}>
          {approvals.length === 0 ? (
            <p className="text-sm" style={{ color: "var(--text-muted)" }}>
              No approvals on record.
            </p>
          ) : (
            <ul className="space-y-2">
              {approvals.map((a) => (
                <li key={a.id} className="rounded-md border p-3 text-sm" style={{ borderColor: "var(--border)" }}>
                  <div className="flex items-center justify-between gap-2">
                    <span style={{ color: "var(--text)" }}>
                      {a.connector_type} · {a.requested_action} · <em>{a.status}</em>
                    </span>
                    <span className="text-xs" style={{ color: "var(--text-quiet)" }}>
                      {a.creator_id ?? "no creator"} · risk {a.risk_level}
                    </span>
                  </div>
                  {a.status === "pending" && (
                    <div className="mt-2 flex gap-2">
                      <button
                        type="button"
                        onClick={() => void onApprovalAction(a.id, "approve")}
                        disabled={busy}
                        className="rounded-md border px-2 py-1 text-xs"
                        style={{ borderColor: "var(--border)", color: "rgb(5,150,105)" }}
                      >
                        Approve
                      </button>
                      <button
                        type="button"
                        onClick={() => void onApprovalAction(a.id, "reject")}
                        disabled={busy}
                        className="rounded-md border px-2 py-1 text-xs"
                        style={{ borderColor: "var(--border)", color: "rgb(180,83,9)" }}
                      >
                        Reject
                      </button>
                    </div>
                  )}
                  {a.status === "approved" && !a.revoked_at && (
                    <div className="mt-2">
                      <button
                        type="button"
                        onClick={() => {
                          if (confirm(`Revoke this approval? Future ${a.connector_type} actions will be blocked.`)) {
                            void onApprovalAction(a.id, "revoke");
                          }
                        }}
                        disabled={busy}
                        className="rounded-md border px-2 py-1 text-xs"
                        style={{ borderColor: "var(--border)", color: "rgb(190,18,60)" }}
                      >
                        Revoke
                      </button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>

        {/* Consents */}
        <Card title="Client consents" hint={`${consents.length} recent`}>
          {consents.length === 0 ? (
            <p className="text-sm" style={{ color: "var(--text-muted)" }}>
              No consent records on file.
            </p>
          ) : (
            <ul className="space-y-2">
              {consents.map((c) => (
                <li key={c.id} className="rounded-md border p-3 text-sm" style={{ borderColor: "var(--border)" }}>
                  <div className="flex items-center justify-between gap-2">
                    <span style={{ color: "var(--text)" }}>
                      {c.consent_type} · <em>{c.status}</em>
                    </span>
                    <span className="text-xs" style={{ color: "var(--text-quiet)" }}>
                      {c.creator_id ?? "no creator"} · {c.source ?? "no source"}
                    </span>
                  </div>
                  {c.status === "granted" && !c.revoked_at && (
                    <div className="mt-2">
                      <button
                        type="button"
                        onClick={() => {
                          if (confirm(`Revoke this consent? In-flight syncs depending on it will fail closed.`)) {
                            void onConsentRevoke(c.id);
                          }
                        }}
                        disabled={busy}
                        className="rounded-md border px-2 py-1 text-xs"
                        style={{ borderColor: "var(--border)", color: "rgb(190,18,60)" }}
                      >
                        Revoke consent
                      </button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>

        {/* Gateway token migration */}
        {status && (
          <Card title="Gateway token migration" hint={`${status.legacy_gateway_token_count} legacy plaintext rows`}>
            <p className="text-sm mb-3" style={{ color: "var(--text-muted)" }}>
              Encrypts any remaining plaintext gateway tokens. The migrator refuses to run unless <code>SETTINGS_ENCRYPTION_KEY</code> is configured.
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => void onMigrateGatewayTokens(true)}
                disabled={busy}
                className="rounded-md border px-3 py-1.5 text-sm"
                style={{ borderColor: "var(--border)", color: "var(--text)" }}
              >
                Dry run
              </button>
              <button
                type="button"
                onClick={() => {
                  if (confirm("Run the migration for real? Plaintext tokens will be encrypted in place.")) {
                    void onMigrateGatewayTokens(false);
                  }
                }}
                disabled={busy || status.legacy_gateway_token_count === 0}
                className="rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50"
                style={{ background: "var(--accent-strong)", color: "white" }}
              >
                Run migration
              </button>
            </div>
          </Card>
        )}

        {/* Retention preview */}
        {status && (
          <Card title="Audit retention preview" hint="rows eligible for purge under per-category windows">
            {Object.keys(status.audit_retention_preview).length === 0 ? (
              <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                Nothing eligible. The retention pipeline is dry-run by default.
              </p>
            ) : (
              <ul className="text-sm space-y-1">
                {Object.entries(status.audit_retention_preview).map(([cat, n]) => (
                  <li key={cat} style={{ color: "var(--text-muted)" }}>
                    {cat}: <span style={{ color: "var(--text)" }}>{n}</span> row(s)
                  </li>
                ))}
              </ul>
            )}
          </Card>
        )}

        {/* Missing prerequisites */}
        {status && status.missing_prerequisites.length > 0 && (
          <Card title="Missing prerequisites" hint="things to fix before direct connectors are safe">
            <ul className="space-y-1.5 text-sm">
              {status.missing_prerequisites.map((m) => (
                <li key={m} style={{ color: "rgb(180,83,9)" }}>
                  ⚠ {m}
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </main>
  );
}

// ── Atoms ────────────────────────────────────────────────────────────────────

function Card({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section
      className="rounded-xl border p-5"
      style={{ background: "var(--surface)", borderColor: "var(--border)" }}
    >
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold" style={{ color: "var(--text)" }}>{title}</h2>
        {hint && (
          <span className="text-xs" style={{ color: "var(--text-quiet)" }}>{hint}</span>
        )}
      </div>
      {children}
    </section>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "ok" | "bad" | "muted" }) {
  const color =
    tone === "ok"
      ? "rgb(5,150,105)"
      : tone === "bad"
      ? "rgb(190,18,60)"
      : tone === "muted"
      ? "var(--text-muted)"
      : "var(--text)";
  return (
    <div
      className="rounded-xl border p-4"
      style={{ background: "var(--surface)", borderColor: "var(--border)" }}
    >
      <p className="text-[11px] font-semibold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>
        {label}
      </p>
      <p className="mt-1 text-xl font-semibold" style={{ color }}>{value}</p>
    </div>
  );
}

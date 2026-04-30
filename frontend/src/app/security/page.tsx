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
  type ApprovalCreateInput,
  type ApprovalSummary,
  type ConsentCreateInput,
  type ConsentSummary,
  type OnlyFansDirectStatus,
  type OnlyMonsterGatePreviewResult,
  type OnlyMonsterGateStatus,
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
  const [ofDirect, setOfDirect] = useState<OnlyFansDirectStatus | null>(null);
  const [omGate, setOmGate] = useState<OnlyMonsterGateStatus | null>(null);
  const [omPreviewCreatorId, setOmPreviewCreatorId] = useState<string>("");
  const [omPreviewResult, setOmPreviewResult] = useState<OnlyMonsterGatePreviewResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [s, a, c, od, om] = await Promise.all([
        securityApi.status(fetchWithAuth),
        securityApi.approvals(fetchWithAuth, { limit: 25 }),
        securityApi.consents(fetchWithAuth, { limit: 25 }),
        securityApi.onlyfansDirectStatus(fetchWithAuth),
        securityApi.onlymonsterGateStatus(fetchWithAuth, {
          creatorId: omPreviewCreatorId.trim() || null,
        }),
      ]);
      setStatus(s);
      setApprovals(a);
      setConsents(c);
      setOfDirect(od);
      setOmGate(om);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [fetchWithAuth, omPreviewCreatorId]);

  const onOmGatePreview = async () => {
    const id = omPreviewCreatorId.trim();
    if (!id) {
      setError("creator_id is required for an OnlyMonster gate preview.");
      return;
    }
    setBusy(true);
    try {
      const r = await securityApi.onlymonsterGatePreview(fetchWithAuth, {
        creator_id: id,
      });
      setOmPreviewResult(r);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

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

  const onCreateApproval = async (input: ApprovalCreateInput) => {
    setBusy(true);
    try {
      await securityApi.createApproval(fetchWithAuth, input);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      throw e;
    } finally {
      setBusy(false);
    }
  };

  const onCreateConsent = async (input: ConsentCreateInput) => {
    setBusy(true);
    try {
      await securityApi.createConsent(fetchWithAuth, input);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      throw e;
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

        {/* OnlyMonster gated sync readiness (Sprint 8A) */}
        {omGate && (
          <Card
            title="OnlyMonster gated sync"
            hint={omGate.real_client_wired ? "real client wired" : "fake client only"}
          >
            <div className="space-y-2 text-sm">
              <ul className="text-xs space-y-1" style={{ color: "var(--text-muted)" }}>
                <li>
                  Env flag <code>MC_ONLYMONSTER_GATED_SYNC_ENABLED</code>:{" "}
                  <strong>{omGate.env_flag_enabled ? "on" : "off"}</strong>
                </li>
                <li>
                  Approval present:{" "}
                  <strong style={{ color: omGate.approval_present ? "rgb(5,150,105)" : "rgb(180,83,9)" }}>
                    {omGate.approval_present ? "yes" : "no"}
                  </strong>
                </li>
                <li>
                  Consent present:{" "}
                  <strong style={{ color: omGate.consent_present ? "rgb(5,150,105)" : "rgb(180,83,9)" }}>
                    {omGate.consent_present ? "yes" : "no"}
                  </strong>
                </li>
                <li>
                  Kill switch:{" "}
                  <strong style={{ color: omGate.kill_switch_blocking ? "rgb(190,18,60)" : "rgb(5,150,105)" }}>
                    {omGate.kill_switch_blocking ?? "clear"}
                  </strong>
                </li>
                <li>
                  Encryption key dedicated:{" "}
                  <strong>{omGate.encryption_key_dedicated ? "yes" : "no"}</strong>
                </li>
                <li>
                  Real client wired: <strong>{omGate.real_client_wired ? "yes" : "no"}</strong>
                </li>
                <li>
                  Direct OnlyFans:{" "}
                  <strong style={{ color: "rgb(190,18,60)" }}>
                    {omGate.direct_onlyfans_blocked ? "blocked" : "NOT BLOCKED"}
                  </strong>
                </li>
              </ul>
              <p className="text-xs" style={{ color: "var(--text-quiet)" }}>
                {omGate.notes}
              </p>

              <div className="flex items-end gap-2 pt-2 border-t" style={{ borderColor: "var(--border)" }}>
                <label className="flex-1 text-xs">
                  <span className="block mb-1 font-medium uppercase tracking-wider" style={{ color: "var(--text-quiet)" }}>
                    Creator ID (for preview against fake client)
                  </span>
                  <input
                    type="text"
                    value={omPreviewCreatorId}
                    onChange={(e) => setOmPreviewCreatorId(e.target.value)}
                    placeholder="creator-A"
                    className="w-full rounded-md border px-2 py-1.5 text-sm"
                    style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--text)" }}
                  />
                </label>
                <button
                  type="button"
                  onClick={() => void onOmGatePreview()}
                  disabled={busy || !omPreviewCreatorId.trim()}
                  className="rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
                  style={{ borderColor: "var(--border)", color: "var(--text)" }}
                >
                  Run gated preview
                </button>
              </div>
              <p className="text-xs" style={{ color: "var(--text-quiet)" }}>
                Preview always uses the fake client. There is no &ldquo;Connect&rdquo;
                button. Production refuses the fake client unless{" "}
                <code>MC_ONLYMONSTER_ALLOW_FAKE_CLIENT=1</code>.
              </p>

              {omPreviewResult && (
                <div
                  className="rounded-md border p-2 text-xs space-y-1"
                  style={{
                    borderColor: omPreviewResult.allowed ? "rgb(5,150,105)" : "rgb(190,18,60)",
                    background: "var(--surface)",
                  }}
                >
                  <p style={{ color: "var(--text)" }}>
                    Last preview:{" "}
                    <strong style={{ color: omPreviewResult.allowed ? "rgb(5,150,105)" : "rgb(190,18,60)" }}>
                      {omPreviewResult.allowed ? "ALLOWED" : "BLOCKED"}
                    </strong>{" "}
                    · creator <code>{omPreviewResult.creator_id}</code>
                  </p>
                  <p style={{ color: "var(--text-muted)" }}>
                    rows_read={omPreviewResult.rows_read}, rows_written={omPreviewResult.rows_written}
                    {omPreviewResult.error_category ? `, error=${omPreviewResult.error_category}` : ""}
                    {omPreviewResult.audit_event_id ? `, audit_id=${omPreviewResult.audit_event_id.slice(0, 8)}…` : ""}
                  </p>
                  <p style={{ color: "var(--text-quiet)" }}>{omPreviewResult.notes}</p>
                </div>
              )}
            </div>
          </Card>
        )}

        {/* Direct OnlyFans connector status (Sprint 7 — disabled by design) */}
        {ofDirect && (
          <Card
            title="Direct OnlyFans connector"
            hint={ofDirect.enabled ? "active" : "disabled"}
          >
            <div className="space-y-2 text-sm">
              <div className="flex items-center gap-2">
                <ShieldAlert className="h-4 w-4" style={{ color: "rgb(190,18,60)" }} />
                <p style={{ color: "var(--text)" }}>
                  Connector: <strong>disabled</strong> · mode <strong>{ofDirect.mode}</strong> · session{" "}
                  <strong>{ofDirect.session_health}</strong>
                </p>
              </div>
              <ul className="text-xs space-y-1" style={{ color: "var(--text-muted)" }}>
                <li>Real account connection: <strong style={{ color: "rgb(190,18,60)" }}>blocked</strong></li>
                <li>Write actions: <strong style={{ color: "rgb(190,18,60)" }}>blocked ({ofDirect.write_actions_count} hard-blocked)</strong></li>
                <li>Read-only preparation: <strong>in progress</strong> ({ofDirect.read_actions_count} read categories defined)</li>
                <li>
                  Rate-limit policy: max <strong>{ofDirect.rate_max_per_minute}</strong>/min,{" "}
                  <strong>{ofDirect.rate_max_per_hour}</strong>/hr; backoff{" "}
                  {ofDirect.backoff_initial_seconds}s → {ofDirect.backoff_max_seconds}s
                </li>
                <li>Real client wired: <strong>{ofDirect.real_client_wired ? "yes" : "no"}</strong></li>
              </ul>
              <p className="text-xs" style={{ color: "var(--text-quiet)" }}>
                {ofDirect.notes}
              </p>
              <p className="text-xs" style={{ color: "var(--text-quiet)" }}>
                There is no &ldquo;Connect&rdquo; button. Activation requires the
                readiness checklist at{" "}
                <code>docs/security/direct-onlyfans-readiness-checklist.md</code> to
                pass and an explicit connector approval + creator consent.
              </p>
            </div>
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

        {/* Create approval */}
        <Card title="Create connector approval" hint="owner records the approval the gate will check at runtime">
          <ApprovalForm onSubmit={onCreateApproval} disabled={busy} />
        </Card>

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

        {/* Create consent */}
        <Card title="Record client consent" hint="record the fact of an out-of-band signed consent">
          <ConsentForm onSubmit={onCreateConsent} disabled={busy} />
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

// ── Forms ────────────────────────────────────────────────────────────────────

const APPROVAL_CONNECTOR_TYPES = ["onlymonster", "onlyfans_direct", "other"] as const;
const APPROVAL_RISK_LEVELS = ["low", "medium", "high", "critical"] as const;

function ApprovalForm({
  onSubmit,
  disabled,
}: {
  onSubmit: (input: ApprovalCreateInput) => Promise<void>;
  disabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [connectorType, setConnectorType] = useState<string>("onlymonster");
  const [requestedAction, setRequestedAction] = useState<string>("creator_sync");
  const [creatorId, setCreatorId] = useState<string>("");
  const [organizationId, setOrganizationId] = useState<string>("");
  const [riskLevel, setRiskLevel] = useState<string>("medium");
  const [expiresAtIso, setExpiresAtIso] = useState<string>("");
  const [reason, setReason] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const reset = () => {
    setRequestedAction("creator_sync");
    setCreatorId("");
    setOrganizationId("");
    setRiskLevel("medium");
    setExpiresAtIso("");
    setReason("");
    setLocalError(null);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLocalError(null);
    if (!connectorType.trim() || !requestedAction.trim()) {
      setLocalError("connector_type and requested_action are required");
      return;
    }
    setSubmitting(true);
    try {
      await onSubmit({
        connector_type: connectorType.trim(),
        requested_action: requestedAction.trim(),
        creator_id: creatorId.trim() || null,
        organization_id: organizationId.trim() || null,
        risk_level: riskLevel,
        expires_at_iso: expiresAtIso.trim() || null,
        reason: reason.trim() || null,
      });
      reset();
      setOpen(false);
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        disabled={disabled}
        className="rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
        style={{ borderColor: "var(--border)", color: "var(--text)" }}
      >
        New approval…
      </button>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <FormField label="Connector type">
          <select
            value={connectorType}
            onChange={(e) => setConnectorType(e.target.value)}
            className="w-full rounded-md border px-2 py-1.5 text-sm"
            style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--text)" }}
          >
            {APPROVAL_CONNECTOR_TYPES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </FormField>
        <FormField label="Requested action">
          <input
            type="text"
            value={requestedAction}
            onChange={(e) => setRequestedAction(e.target.value)}
            placeholder="e.g. creator_sync"
            className="w-full rounded-md border px-2 py-1.5 text-sm"
            style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--text)" }}
          />
        </FormField>
        <FormField label="Creator ID (optional)">
          <input
            type="text"
            value={creatorId}
            onChange={(e) => setCreatorId(e.target.value)}
            className="w-full rounded-md border px-2 py-1.5 text-sm"
            style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--text)" }}
          />
        </FormField>
        <FormField label="Organization ID (UUID, optional)">
          <input
            type="text"
            value={organizationId}
            onChange={(e) => setOrganizationId(e.target.value)}
            className="w-full rounded-md border px-2 py-1.5 text-sm"
            style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--text)" }}
          />
        </FormField>
        <FormField label="Risk level">
          <select
            value={riskLevel}
            onChange={(e) => setRiskLevel(e.target.value)}
            className="w-full rounded-md border px-2 py-1.5 text-sm"
            style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--text)" }}
          >
            {APPROVAL_RISK_LEVELS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </FormField>
        <FormField label="Expires at (ISO 8601, optional)">
          <input
            type="text"
            value={expiresAtIso}
            onChange={(e) => setExpiresAtIso(e.target.value)}
            placeholder="2026-12-31T23:59:00Z"
            className="w-full rounded-md border px-2 py-1.5 text-sm"
            style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--text)" }}
          />
        </FormField>
      </div>
      <FormField label="Reason (audited)">
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={2}
          className="w-full rounded-md border px-2 py-1.5 text-sm"
          style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--text)" }}
        />
      </FormField>
      {localError && (
        <p className="text-xs" style={{ color: "rgb(190,18,60)" }}>
          {localError}
        </p>
      )}
      <p className="text-xs" style={{ color: "var(--text-quiet)" }}>
        Creates a <em>pending</em> approval. The gate refuses connector actions until you also click <strong>Approve</strong> below.
      </p>
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={disabled || submitting}
          className="rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50"
          style={{ background: "var(--accent-strong)", color: "white" }}
        >
          {submitting ? "Creating…" : "Create approval"}
        </button>
        <button
          type="button"
          onClick={() => {
            reset();
            setOpen(false);
          }}
          disabled={submitting}
          className="rounded-md border px-3 py-1.5 text-sm"
          style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

const CONSENT_TYPES = [
  "onlymonster_read",
  "onlyfans_direct_read",
  "data_processing",
  "other",
] as const;

function ConsentForm({
  onSubmit,
  disabled,
}: {
  onSubmit: (input: ConsentCreateInput) => Promise<void>;
  disabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [consentType, setConsentType] = useState<string>("onlymonster_read");
  const [creatorId, setCreatorId] = useState<string>("");
  const [organizationId, setOrganizationId] = useState<string>("");
  const [source, setSource] = useState<string>("");
  const [documentReference, setDocumentReference] = useState<string>("");
  const [expiresAtIso, setExpiresAtIso] = useState<string>("");
  const [notes, setNotes] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const reset = () => {
    setCreatorId("");
    setOrganizationId("");
    setSource("");
    setDocumentReference("");
    setExpiresAtIso("");
    setNotes("");
    setLocalError(null);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLocalError(null);
    if (!consentType.trim()) {
      setLocalError("consent_type is required");
      return;
    }
    setSubmitting(true);
    try {
      await onSubmit({
        consent_type: consentType.trim(),
        creator_id: creatorId.trim() || null,
        organization_id: organizationId.trim() || null,
        source: source.trim() || null,
        document_reference: documentReference.trim() || null,
        expires_at_iso: expiresAtIso.trim() || null,
        notes: notes.trim() || null,
      });
      reset();
      setOpen(false);
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        disabled={disabled}
        className="rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
        style={{ borderColor: "var(--border)", color: "var(--text)" }}
      >
        Record consent…
      </button>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <FormField label="Consent type">
          <select
            value={consentType}
            onChange={(e) => setConsentType(e.target.value)}
            className="w-full rounded-md border px-2 py-1.5 text-sm"
            style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--text)" }}
          >
            {CONSENT_TYPES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </FormField>
        <FormField label="Creator ID (optional)">
          <input
            type="text"
            value={creatorId}
            onChange={(e) => setCreatorId(e.target.value)}
            className="w-full rounded-md border px-2 py-1.5 text-sm"
            style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--text)" }}
          />
        </FormField>
        <FormField label="Organization ID (UUID, optional)">
          <input
            type="text"
            value={organizationId}
            onChange={(e) => setOrganizationId(e.target.value)}
            className="w-full rounded-md border px-2 py-1.5 text-sm"
            style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--text)" }}
          />
        </FormField>
        <FormField label="Source (e.g. signed PDF, DocuSign)">
          <input
            type="text"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            className="w-full rounded-md border px-2 py-1.5 text-sm"
            style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--text)" }}
          />
        </FormField>
        <FormField label="Document reference (URL or hash)">
          <input
            type="text"
            value={documentReference}
            onChange={(e) => setDocumentReference(e.target.value)}
            className="w-full rounded-md border px-2 py-1.5 text-sm"
            style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--text)" }}
          />
        </FormField>
        <FormField label="Expires at (ISO 8601, optional)">
          <input
            type="text"
            value={expiresAtIso}
            onChange={(e) => setExpiresAtIso(e.target.value)}
            placeholder="2027-04-28T00:00:00Z"
            className="w-full rounded-md border px-2 py-1.5 text-sm"
            style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--text)" }}
          />
        </FormField>
      </div>
      <FormField label="Notes (audited)">
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={2}
          className="w-full rounded-md border px-2 py-1.5 text-sm"
          style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--text)" }}
        />
      </FormField>
      {localError && (
        <p className="text-xs" style={{ color: "rgb(190,18,60)" }}>
          {localError}
        </p>
      )}
      <p className="text-xs" style={{ color: "var(--text-quiet)" }}>
        Records the fact of an out-of-band signed consent. Do <strong>not</strong> paste the signed text body — only its reference. Revoke from the list below; in-flight syncs depending on it fail closed.
      </p>
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={disabled || submitting}
          className="rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50"
          style={{ background: "var(--accent-strong)", color: "white" }}
        >
          {submitting ? "Recording…" : "Record consent"}
        </button>
        <button
          type="button"
          onClick={() => {
            reset();
            setOpen(false);
          }}
          disabled={submitting}
          className="rounded-md border px-3 py-1.5 text-sm"
          style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

function FormField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-xs">
      <span className="block mb-1 font-medium uppercase tracking-wider" style={{ color: "var(--text-quiet)" }}>
        {label}
      </span>
      {children}
    </label>
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

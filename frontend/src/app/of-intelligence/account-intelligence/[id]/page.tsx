"use client";

export const dynamic = "force-dynamic";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { EmptyState, SectionShell, StatPill, StatusBadge } from "@/components/of-intelligence/SectionShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import {
  formatCents,
  formatDate,
  formatRelative,
  ofiApi,
  type AccountAuditResponse,
  type CreatorProfileRow,
  type CreatorProfileUpdate,
} from "@/lib/of-intelligence/api";

type FieldDef = {
  key: keyof CreatorProfileUpdate;
  label: string;
  hint?: string;
  multiline?: boolean;
  rows?: number;
  type?: "text" | "url";
};

const STRATEGY_FIELDS: ReadonlyArray<FieldDef> = [
  {
    key: "brand_persona",
    label: "Brand persona",
    hint: "Who this creator is — their public identity, archetype, fantasy.",
    multiline: true,
    rows: 4,
  },
  {
    key: "content_pillars",
    label: "Content pillars",
    hint: "The 3–5 themes / styles they post around.",
    multiline: true,
    rows: 3,
  },
  {
    key: "voice_tone",
    label: "Voice & tone",
    hint: "How chatters should sound when speaking as this creator.",
    multiline: true,
    rows: 3,
  },
  {
    key: "audience_summary",
    label: "Audience",
    hint: "Who's actually buying — demographics, what they want.",
    multiline: true,
    rows: 3,
  },
  {
    key: "monetization_focus",
    label: "Monetization focus",
    hint: "Where revenue comes from — subs, PPV, tips, custom, sexting, etc.",
    multiline: true,
    rows: 2,
  },
  {
    key: "posting_cadence",
    label: "Posting cadence",
    hint: "Wall / mass-DM / story rhythm.",
    multiline: true,
    rows: 2,
  },
  {
    key: "strategy_summary",
    label: "Strategy summary",
    hint: "The current 30–60 day plan.  This drives audits and AI prompts.",
    multiline: true,
    rows: 4,
  },
  {
    key: "off_limits",
    label: "Off limits",
    hint: "Hard nos — kinks, words, scenarios, regions.",
    multiline: true,
    rows: 3,
  },
  {
    key: "vault_notes",
    label: "Vault notes",
    hint: "What's in the vault — categorisation, naming conventions, what to push.",
    multiline: true,
    rows: 4,
  },
  {
    key: "agency_notes",
    label: "Agency notes",
    hint: "Internal-only — anything chatters / managers should know.",
    multiline: true,
    rows: 3,
  },
];

const SOCIAL_FIELDS: ReadonlyArray<FieldDef> = [
  { key: "onlyfans_url", label: "OnlyFans URL", type: "url" },
  { key: "instagram_url", label: "Instagram URL", type: "url" },
  { key: "twitter_url", label: "Twitter / X URL", type: "url" },
  { key: "tiktok_url", label: "TikTok URL", type: "url" },
  { key: "threads_url", label: "Threads URL", type: "url" },
  { key: "reddit_url", label: "Reddit URL", type: "url" },
];

export default function CreatorProfileDetailPage() {
  const params = useParams<{ id: string }>();
  const profileId = params?.id;
  const { fetchWithAuth } = useAuthFetch();
  const [profile, setProfile] = useState<CreatorProfileRow | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [audit, setAudit] = useState<AccountAuditResponse | null>(null);

  const refresh = useCallback(async () => {
    if (!profileId) return;
    setError(null);
    try {
      const row = await ofiApi.creatorProfile(fetchWithAuth, profileId);
      setProfile(row);
      // Seed the draft from server values so unedited fields don't get
      // wiped on save.
      const seed: Record<string, string> = {};
      for (const f of [...STRATEGY_FIELDS, ...SOCIAL_FIELDS]) {
        const v = row[f.key as keyof CreatorProfileRow];
        seed[f.key as string] = typeof v === "string" ? v : "";
      }
      setDraft(seed);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [profileId, fetchWithAuth]);

  useEffect(() => { void refresh(); }, [refresh]);

  const setField = (key: string, value: string) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
  };

  const handleSave = useCallback(async () => {
    if (!profileId) return;
    setSaving(true);
    setError(null);
    try {
      // Send every operator field — backend treats empty as null.
      const body: CreatorProfileUpdate = {};
      for (const f of [...STRATEGY_FIELDS, ...SOCIAL_FIELDS]) {
        const value = (draft[f.key as string] ?? "").trim();
        (body as Record<string, string | null>)[f.key as string] = value || null;
      }
      const updated = await ofiApi.updateCreatorProfile(fetchWithAuth, profileId, body);
      setProfile(updated);
      setSavedAt(new Date().toISOString());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }, [profileId, draft, fetchWithAuth]);

  const handleGenerateAudit = useCallback(async () => {
    if (!profileId) return;
    setAuditLoading(true);
    setError(null);
    try {
      const result = await ofiApi.generateAccountAudit(fetchWithAuth, profileId);
      setAudit(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setAuditLoading(false);
    }
  }, [profileId, fetchWithAuth]);

  if (loading) {
    return (
      <SectionShell title="Account Intelligence">
        <EmptyState title="Loading profile…" />
      </SectionShell>
    );
  }
  if (!profile) {
    return (
      <SectionShell title="Account Intelligence">
        <EmptyState
          title="Profile not found."
          hint="It may have been deleted or the URL is wrong."
        />
      </SectionShell>
    );
  }

  const label = profile.display_name || profile.username || profile.source_account_id;
  return (
    <SectionShell
      title={label}
      description={`${profile.platform || "OnlyFans"} • ${profile.username ? "@" + profile.username : profile.source_account_id}`}
      actions={
        <div className="flex items-center gap-2">
          <Link
            href="/of-intelligence/account-intelligence"
            className="text-xs hover:underline"
            style={{ color: "var(--text-muted)" }}
          >
            ← Back
          </Link>
          <button
            onClick={() => void handleGenerateAudit()}
            disabled={auditLoading}
            className="rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
            style={{
              background: "var(--accent-strong)",
              borderColor: "var(--accent-strong)",
              color: "white",
            }}
          >
            {auditLoading ? "Generating…" : "Generate Account Audit"}
          </button>
          <button
            onClick={() => void handleSave()}
            disabled={saving}
            className="rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
            style={{
              background: "var(--surface)",
              borderColor: "var(--border)",
              color: "var(--text)",
            }}
          >
            {saving ? "Saving…" : "Save changes"}
          </button>
        </div>
      }
    >
      {error && (
        <div
          className="mb-4 rounded-md border p-3 text-sm"
          style={{ borderColor: "rgb(248,113,113)", color: "rgb(225,29,72)" }}
        >
          {error}
        </div>
      )}
      {savedAt && (
        <div
          className="mb-4 rounded-md border p-3 text-sm"
          style={{ borderColor: "rgba(16,185,129,0.5)", color: "rgb(5,150,105)" }}
        >
          Saved {formatRelative(savedAt)}.
        </div>
      )}

      {/* ── Identity / live stats ────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <StatPill
          label="Access"
          value={profile.access_status || "—"}
          hint={
            profile.subscription_expiration_date
              ? `Expires ${formatDate(profile.subscription_expiration_date)}`
              : undefined
          }
        />
        <StatPill
          label="Sub price"
          value={formatCents(profile.subscribe_price_cents)}
        />
        <StatPill
          label="Fans synced"
          value={profile.stats.fans_count.toLocaleString()}
        />
        <StatPill
          label="Messages synced"
          value={profile.stats.messages_count.toLocaleString()}
        />
        <StatPill
          label="Revenue (30d)"
          value={formatCents(profile.stats.revenue_30d_cents)}
        />
        <StatPill
          label="Revenue (lifetime)"
          value={formatCents(profile.stats.revenue_total_cents)}
        />
        <StatPill
          label="Open alerts"
          value={profile.stats.open_alert_count.toString()}
          hint={profile.stats.open_alert_count > 0 ? "Review on Alerts tab" : undefined}
        />
        <StatPill
          label="Last sync"
          value={formatRelative(profile.last_account_sync_at)}
        />
      </div>

      {/* ── Identity strip (read-only) ───────────────────────────────── */}
      <div
        className="rounded-xl border p-4 mb-6"
        style={{ background: "var(--surface)", borderColor: "var(--border)" }}
      >
        <p
          className="text-[11px] font-semibold uppercase tracking-widest mb-2"
          style={{ color: "var(--text-quiet)" }}
        >
          Identity (auto-filled from OnlyMonster)
        </p>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
          <ReadOnlyField label="Username" value={profile.username} />
          <ReadOnlyField label="Display name" value={profile.display_name} />
          <ReadOnlyField label="Platform" value={profile.platform} />
          <ReadOnlyField label="Organisation" value={profile.organisation_id} />
          <ReadOnlyField
            label="Account status"
            value={profile.status}
            badge={<StatusBadge status={profile.status} />}
          />
          <ReadOnlyField label="Source account id" value={profile.source_account_id} />
        </div>
      </div>

      {/* ── Strategy / brand fields (editable) ───────────────────────── */}
      <div
        className="rounded-xl border p-5 mb-6"
        style={{ background: "var(--surface)", borderColor: "var(--border)" }}
      >
        <h2
          className="text-sm font-semibold uppercase tracking-widest mb-4"
          style={{ color: "var(--text-quiet)" }}
        >
          Brand & Strategy
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {STRATEGY_FIELDS.map((f) => (
            <EditableField
              key={f.key as string}
              field={f}
              value={draft[f.key as string] ?? ""}
              onChange={(v) => setField(f.key as string, v)}
            />
          ))}
        </div>
      </div>

      {/* ── External presence ────────────────────────────────────────── */}
      <div
        className="rounded-xl border p-5 mb-6"
        style={{ background: "var(--surface)", borderColor: "var(--border)" }}
      >
        <h2
          className="text-sm font-semibold uppercase tracking-widest mb-4"
          style={{ color: "var(--text-quiet)" }}
        >
          External Presence
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {SOCIAL_FIELDS.map((f) => (
            <EditableField
              key={f.key as string}
              field={f}
              value={draft[f.key as string] ?? ""}
              onChange={(v) => setField(f.key as string, v)}
            />
          ))}
        </div>
      </div>

      {/* ── Audit output ─────────────────────────────────────────────── */}
      {audit && (
        <div
          className="rounded-xl border p-5 mb-6"
          style={{ background: "var(--surface)", borderColor: "var(--border)" }}
        >
          <div className="flex items-start justify-between mb-3">
            <div>
              <h2
                className="text-sm font-semibold uppercase tracking-widest"
                style={{ color: "var(--text-quiet)" }}
              >
                Account Audit
              </h2>
              <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
                Generated {formatRelative(audit.generated_at)}.  Read-only — pulls only
                what we&apos;ve already synced.
              </p>
            </div>
            <button
              onClick={() => {
                if (typeof navigator !== "undefined" && navigator.clipboard) {
                  void navigator.clipboard.writeText(audit.markdown);
                }
              }}
              className="rounded-md border px-2 py-1 text-xs"
              style={{
                background: "var(--bg)",
                borderColor: "var(--border)",
                color: "var(--text-muted)",
              }}
            >
              Copy markdown
            </button>
          </div>

          <p className="text-sm mb-4" style={{ color: "var(--text)" }}>
            {audit.summary}
          </p>

          <div className="space-y-4">
            {audit.sections.map((section) => (
              <div key={section.title}>
                <h3
                  className="text-xs font-semibold uppercase tracking-widest mb-1"
                  style={{ color: "var(--text-quiet)" }}
                >
                  {section.title}
                </h3>
                <pre
                  className="text-sm whitespace-pre-wrap"
                  style={{
                    fontFamily: "inherit",
                    color: "var(--text)",
                    margin: 0,
                  }}
                >
                  {section.body}
                </pre>
              </div>
            ))}
          </div>
        </div>
      )}
    </SectionShell>
  );
}

function ReadOnlyField({
  label,
  value,
  badge,
}: {
  label: string;
  value: string | null | undefined;
  badge?: React.ReactNode;
}) {
  return (
    <div>
      <p
        className="text-[11px] font-semibold uppercase tracking-widest"
        style={{ color: "var(--text-quiet)" }}
      >
        {label}
      </p>
      <div className="mt-0.5 flex items-center gap-2" style={{ color: "var(--text)" }}>
        {badge ?? <span>{value || "—"}</span>}
      </div>
    </div>
  );
}

function EditableField({
  field,
  value,
  onChange,
}: {
  field: FieldDef;
  value: string;
  onChange: (v: string) => void;
}) {
  const inputStyle = {
    background: "var(--bg)",
    borderColor: "var(--border)",
    color: "var(--text)",
  };
  return (
    <div>
      <label
        className="text-xs font-semibold uppercase tracking-widest"
        style={{ color: "var(--text-quiet)" }}
      >
        {field.label}
      </label>
      {field.multiline ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          rows={field.rows ?? 3}
          className="mt-1 w-full rounded-md border px-3 py-2 text-sm"
          style={inputStyle}
        />
      ) : (
        <input
          type={field.type ?? "text"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="mt-1 w-full rounded-md border px-3 py-2 text-sm"
          style={inputStyle}
        />
      )}
      {field.hint && (
        <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
          {field.hint}
        </p>
      )}
    </div>
  );
}

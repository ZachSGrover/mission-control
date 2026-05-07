"use client";

import { useState } from "react";
import { Loader2, Lock, Save } from "lucide-react";

import type { MCRole } from "@/lib/roles";

const EDITABLE_ROLES: ReadonlyArray<Exclude<MCRole, "owner">> = [
  "operator",
  "builder",
  "viewer",
];

export interface BotPermissionsEditorProps {
  slug: string;
  permittedRoles: MCRole[];
  readOnlyExternal: boolean;
  viewerRole: MCRole | null;
  /**
   * Persist a new permitted_roles list. Implementations should hit
   * PATCH /api/v1/bots/{slug}/permissions and return the canonical list
   * as stored by the server (which always includes "owner").
   */
  onSave: (slug: string, permittedRoles: MCRole[]) => Promise<MCRole[]>;
}

// Owner-only inline editor for a single bot's permitted_roles.
//
// Invariants enforced in the UI:
//   • Hidden entirely for any role other than "owner" — operators do
//     not see or interact with this surface.
//   • Owner is always selected and not toggleable.  Even if a caller
//     somehow submitted without owner, the server reinstates it; this
//     UI mirrors that contract.
//   • Bots flagged read_only_external never expose checkboxes or a
//     save button — the surface is permanently informational.
//   • No secrets, tokens, webhook URLs, or fan PII pass through this
//     component; only role strings.
export function BotPermissionsEditor({
  slug,
  permittedRoles,
  readOnlyExternal,
  viewerRole,
  onSave,
}: BotPermissionsEditorProps) {
  // Hooks must run on every render in the same order, so they live above the
  // early-return gates. The component still bails out via the returns below.
  const [selected, setSelected] = useState<Set<MCRole>>(
    () => new Set<MCRole>(permittedRoles),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (viewerRole !== "owner") return null;

  if (readOnlyExternal) {
    return (
      <div
        className="mt-2 rounded-md px-3 py-2 text-[11px]"
        style={{ background: "var(--surface-muted)", color: "var(--text-quiet)" }}
        data-testid="bot-permissions-blocked"
      >
        <Lock className="inline h-3 w-3 mr-1" aria-hidden="true" />
        Managed externally — start/stop and permissions are not editable here.
      </div>
    );
  }

  const toggle = (role: MCRole) => {
    if (role === "owner") return;
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(role)) next.delete(role);
      else next.add(role);
      return next;
    });
  };

  const onSubmit = async () => {
    setBusy(true);
    setError(null);
    try {
      const out = new Set(selected);
      out.add("owner");
      const next = await onSave(slug, Array.from(out));
      setSelected(new Set(next));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="mt-2 rounded-md px-3 py-2"
      style={{ background: "var(--surface-muted)", border: "1px solid var(--border)" }}
      data-testid="bot-permissions-editor"
    >
      <p
        className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider"
        style={{ color: "var(--text-quiet)" }}
      >
        Permissions
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <label
          className="inline-flex items-center gap-1.5 text-xs"
          style={{ color: "var(--text-muted)" }}
        >
          <input
            type="checkbox"
            checked
            disabled
            readOnly
            aria-label="owner (always permitted)"
            data-testid="bot-permissions-owner"
          />
          owner
        </label>
        {EDITABLE_ROLES.map((role) => (
          <label
            key={role}
            className="inline-flex items-center gap-1.5 text-xs"
            style={{ color: "var(--text)" }}
          >
            <input
              type="checkbox"
              checked={selected.has(role)}
              onChange={() => toggle(role)}
              disabled={busy}
              data-testid={`bot-permissions-${role}`}
              aria-label={role}
            />
            {role}
          </label>
        ))}
        <button
          type="button"
          onClick={() => void onSubmit()}
          disabled={busy}
          className="ml-auto flex items-center gap-1 rounded-md px-2 py-1 text-xs disabled:opacity-50"
          style={{ background: "var(--accent-soft)", color: "var(--accent-strong)" }}
          data-testid="bot-permissions-save"
        >
          {busy ? (
            <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
          ) : (
            <Save className="h-3 w-3" aria-hidden="true" />
          )}
          Save
        </button>
      </div>
      {error && (
        <p className="mt-1 text-[11px]" style={{ color: "#ef4444" }}>
          {error}
        </p>
      )}
    </div>
  );
}

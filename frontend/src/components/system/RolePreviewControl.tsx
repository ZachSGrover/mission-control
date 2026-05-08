"use client";

import { Eye } from "lucide-react";

import { useRole } from "@/hooks/use-role";
import type { MCRole } from "@/lib/roles";
import { getRolePreview, setRolePreview } from "@/lib/role-preview";

const PREVIEWABLE_ROLES: ReadonlyArray<MCRole> = [
  "owner",
  "operator",
  "builder",
  "viewer",
];

// Owner-only control that lets the founder preview the UI as any role.
// Renders nothing for non-owners (real role is the gate, not preview
// state — operators cannot see this even if they fiddle with the
// localStorage key directly).
export function RolePreviewControl() {
  const { realRole } = useRole();
  if (realRole !== "owner") return null;

  // Read the current preview value live from localStorage to keep this
  // a pure controlled component — no local state to drift.
  const currentPreview: MCRole = getRolePreview() ?? "owner";

  const onChange = (next: MCRole): void => {
    if (next === "owner") {
      setRolePreview(null);
    } else {
      setRolePreview(next);
    }
  };

  return (
    <section
      data-testid="role-preview-control"
      className="rounded-xl p-4 space-y-3"
      style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}
    >
      <div className="flex items-center gap-2">
        <Eye className="h-4 w-4" style={{ color: "var(--text-quiet)" }} aria-hidden="true" />
        <p className="text-sm font-medium" style={{ color: "var(--text)" }}>
          Role preview
        </p>
      </div>
      <p className="text-xs" style={{ color: "var(--text-quiet)" }}>
        Preview the UI as another role.  Affects only this browser session — the
        backend continues to enforce your real role on every request.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {PREVIEWABLE_ROLES.map((role) => {
          const active = currentPreview === role;
          return (
            <button
              key={role}
              type="button"
              onClick={() => onChange(role)}
              data-testid={`role-preview-${role}`}
              aria-pressed={active}
              className="rounded-md px-3 py-1.5 text-xs font-medium capitalize transition-colors"
              style={
                active
                  ? { background: "var(--accent-soft)", color: "var(--accent-strong)" }
                  : {
                      background: "var(--surface-muted)",
                      color: "var(--text-muted)",
                      border: "1px solid var(--border)",
                    }
              }
            >
              {role}
            </button>
          );
        })}
      </div>
    </section>
  );
}

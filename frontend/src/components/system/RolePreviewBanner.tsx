"use client";

import { Eye, X } from "lucide-react";

import { useRole } from "@/hooks/use-role";
import { setRolePreview } from "@/lib/role-preview";

// Sticky top-of-viewport banner that appears whenever the owner is
// viewing the UI as another role.  Backend permissions are unaffected
// — this is a pure frontend visualization aid for the founder.
export function RolePreviewBanner() {
  const { role, realRole, previewing } = useRole();
  if (!previewing || !role) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="role-preview-banner"
      className="sticky top-0 z-[60] flex items-center gap-2 px-4 py-2 text-xs"
      style={{
        background: "rgba(168,85,247,0.12)",
        borderBottom: "1px solid rgba(168,85,247,0.3)",
        color: "#c084fc",
      }}
    >
      <Eye className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span className="font-semibold uppercase tracking-wider">
        Previewing {role} view
      </span>
      <span className="opacity-80">
        Preview mode does not change your real permissions (real role: {realRole}).
      </span>
      <button
        type="button"
        onClick={() => setRolePreview(null)}
        data-testid="role-preview-banner-clear"
        className="ml-auto inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium"
        style={{ background: "rgba(168,85,247,0.18)", color: "#c084fc" }}
      >
        <X className="h-3 w-3" aria-hidden="true" />
        Exit preview
      </button>
    </div>
  );
}

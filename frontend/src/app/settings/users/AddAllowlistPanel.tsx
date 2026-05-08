"use client";

import { useState } from "react";
import { UserPlus } from "lucide-react";

import { getApiBaseUrl } from "@/lib/api-base";
import type { MCRole } from "@/lib/roles";

export interface AllowedUserEntry {
  clerk_user_id: string | null;
  email: string | null;
  name: string | null;
  role: string;
  added_by_clerk_user_id: string | null;
  created_at: string;
  pending: boolean;
}

type FetchFn = (url: string, init?: RequestInit) => Promise<Response>;

async function addAllowedUserByEmail(
  email: string,
  role: MCRole,
  fetchFn: FetchFn,
): Promise<AllowedUserEntry> {
  const res = await fetchFn(`${getApiBaseUrl()}/api/v1/allowed-users`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, role }),
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  return (await res.json()) as AllowedUserEntry;
}

// Owner-only invite panel.
//
// Role dropdown order is canonical: Owner > Operator > Builder > Viewer.
// Operator must be present so a COO can be invited with bot-operation
// privileges without being granted the broader Builder surface.
export function AddAllowlistPanel({
  fetchFn,
  onAdded,
}: {
  fetchFn: FetchFn;
  onAdded: (entry: AllowedUserEntry) => void;
}) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<MCRole>("viewer");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAdd = async () => {
    const trimmed = email.trim();
    if (!trimmed) {
      setError("Enter an email address.");
      return;
    }
    if (!trimmed.includes("@") || !trimmed.includes(".")) {
      setError("Enter a valid email address.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const entry = await addAllowedUserByEmail(trimmed, role, fetchFn);
      onAdded(entry);
      setEmail("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add user.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="rounded-xl p-4 space-y-3"
      style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}
    >
      <p className="text-sm font-medium" style={{ color: "var(--text)" }}>
        Invite by email
      </p>
      <p className="text-xs" style={{ color: "var(--text-quiet)" }}>
        Enter an email address. They&apos;ll be pre-authorized; the invite activates
        the first time they sign in with that email.
      </p>
      <div className="flex gap-2">
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void handleAdd();
          }}
          placeholder="name@example.com"
          disabled={busy}
          className="flex-1 rounded-lg px-3 py-2 text-sm focus:outline-none disabled:opacity-50"
          style={{
            background: "var(--surface-muted)",
            border: "1px solid var(--border-strong)",
            color: "var(--text)",
          }}
        />
        <select
          value={role}
          disabled={busy}
          onChange={(e) => setRole(e.target.value as MCRole)}
          data-testid="invite-role-select"
          className="rounded-lg px-2 py-2 text-sm focus:outline-none disabled:opacity-50"
          style={{
            background: "var(--surface-muted)",
            border: "1px solid var(--border-strong)",
            color: "var(--text)",
          }}
        >
          <option value="owner">Owner</option>
          <option value="operator">Operator</option>
          <option value="builder">Builder</option>
          <option value="viewer">Viewer</option>
        </select>
        <button
          type="button"
          onClick={() => void handleAdd()}
          disabled={busy || !email.trim()}
          className="flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium text-white transition-opacity disabled:opacity-40"
          style={{ background: "var(--accent)" }}
        >
          <UserPlus className="h-3.5 w-3.5" />
          {busy ? "Adding…" : "Invite"}
        </button>
      </div>
      <p className="text-[11px]" style={{ color: "var(--text-quiet)" }}>
        The selected role is applied automatically on first sign-in. You can still
        adjust it later from Role assignments.
      </p>
      {error && (
        <p className="text-xs" style={{ color: "var(--danger)" }}>
          {error}
        </p>
      )}
    </div>
  );
}

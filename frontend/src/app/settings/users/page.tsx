"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";
import { Lock, Shield, ShieldOff, Trash2, UserPlus } from "lucide-react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { getApiBaseUrl } from "@/lib/api-base";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { useAuthFetch } from "@/hooks/use-auth-fetch";
import type { MCRole } from "@/lib/roles";

// ── Types ─────────────────────────────────────────────────────────────────────

interface UserEntry {
  clerk_user_id: string;
  email: string | null;
  name: string | null;
  role: MCRole;
  disabled: boolean;
}

interface AllowedUserEntry {
  clerk_user_id: string | null;
  email: string | null;
  name: string | null;
  role: string;
  added_by_clerk_user_id: string | null;
  created_at: string;
  pending: boolean;
}

function entryKey(entry: AllowedUserEntry): string {
  return entry.clerk_user_id ?? (entry.email ? `email:${entry.email}` : entry.created_at);
}

type FetchFn = (url: string, init?: RequestInit) => Promise<Response>;

// ── API helpers — roles ───────────────────────────────────────────────────────

async function fetchUsers(fetchFn: FetchFn): Promise<UserEntry[]> {
  const res = await fetchFn(`${getApiBaseUrl()}/api/v1/roles/users`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<UserEntry[]>;
}

async function apiSetRole(
  clerkUserId: string,
  role: MCRole,
  disabled: boolean,
  fetchFn: FetchFn,
): Promise<UserEntry> {
  const res = await fetchFn(`${getApiBaseUrl()}/api/v1/roles/users/${clerkUserId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role, disabled }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<UserEntry>;
}

async function removeUserRole(clerkUserId: string, fetchFn: FetchFn): Promise<void> {
  const res = await fetchFn(`${getApiBaseUrl()}/api/v1/roles/users/${clerkUserId}`, {
    method: "DELETE",
  });
  if (!res.ok && res.status !== 204) {
    const body = await res.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
}

// ── API helpers — allowlist ───────────────────────────────────────────────────

async function fetchAllowedUsers(fetchFn: FetchFn): Promise<AllowedUserEntry[]> {
  const res = await fetchFn(`${getApiBaseUrl()}/api/v1/allowed-users`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<AllowedUserEntry[]>;
}

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
    const body = await res.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<AllowedUserEntry>;
}

async function removeAllowedUser(key: string, fetchFn: FetchFn): Promise<void> {
  const res = await fetchFn(
    `${getApiBaseUrl()}/api/v1/allowed-users/${encodeURIComponent(key)}`,
    { method: "DELETE" },
  );
  if (!res.ok && res.status !== 204) {
    const body = await res.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
}

// ── Role badge ────────────────────────────────────────────────────────────────

const ROLE_COLORS: Record<string, { bg: string; text: string }> = {
  owner:   { bg: "rgba(168,85,247,0.15)",  text: "#c084fc" },
  builder: { bg: "rgba(59,130,246,0.15)",  text: "#60a5fa" },
  viewer:  { bg: "rgba(107,114,128,0.15)", text: "#9ca3af" },
};

function RoleBadge({ role }: { role: string }) {
  const colors = ROLE_COLORS[role] ?? ROLE_COLORS.viewer;
  return (
    <span
      className="rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize"
      style={{ background: colors.bg, color: colors.text }}
    >
      {role}
    </span>
  );
}

// ── User row (roles section) ──────────────────────────────────────────────────

function UserRow({
  user,
  fetchFn,
  onUpdate,
  onRemove,
}: {
  user: UserEntry;
  fetchFn: FetchFn;
  onUpdate: (u: UserEntry) => void;
  onRemove: (id: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const act = useCallback(async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy(false); }
  }, []);

  const handleRoleChange = (newRole: MCRole) => {
    void act(async () => {
      const updated = await apiSetRole(user.clerk_user_id, newRole, user.disabled, fetchFn);
      onUpdate(updated);
    });
  };

  const handleToggleDisabled = () => {
    void act(async () => {
      const updated = await apiSetRole(user.clerk_user_id, user.role, !user.disabled, fetchFn);
      onUpdate(updated);
    });
  };

  const handleRemove = () => {
    void act(async () => {
      await removeUserRole(user.clerk_user_id, fetchFn);
      onRemove(user.clerk_user_id);
    });
  };

  const displayName = user.name ?? user.email ?? user.clerk_user_id;
  const sub = user.name && user.email ? user.email : user.clerk_user_id;

  return (
    <div
      className="flex items-center gap-3 rounded-xl px-4 py-3"
      style={{
        background: "var(--surface-strong)",
        border: "1px solid var(--border)",
        opacity: user.disabled ? 0.6 : 1,
      }}
    >
      <div
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-semibold uppercase"
        style={{ background: "var(--accent)", color: "#fff" }}
      >
        {displayName.slice(0, 1)}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium" style={{ color: "var(--text)" }}>{displayName}</p>
        <p className="truncate text-xs" style={{ color: "var(--text-quiet)" }}>{sub}</p>
        {error && <p className="mt-0.5 text-xs" style={{ color: "var(--danger)" }}>{error}</p>}
      </div>
      <select
        value={user.role}
        disabled={busy}
        onChange={(e) => handleRoleChange(e.target.value as MCRole)}
        className="rounded-lg px-2 py-1 text-xs focus:outline-none disabled:opacity-50"
        style={{ background: "var(--surface-muted)", border: "1px solid var(--border-strong)", color: "var(--text)" }}
      >
        <option value="owner">Owner</option>
        <option value="builder">Builder</option>
        <option value="viewer">Viewer</option>
      </select>
      <RoleBadge role={user.role} />
      <button
        type="button"
        title={user.disabled ? "Enable account" : "Disable account"}
        disabled={busy}
        onClick={handleToggleDisabled}
        className="rounded-lg p-1.5 transition-colors disabled:opacity-40"
        style={{ background: "var(--surface-muted)", border: "1px solid var(--border-strong)", color: user.disabled ? "#22c55e" : "var(--text-quiet)" }}
      >
        {user.disabled ? <Shield className="h-3.5 w-3.5" /> : <ShieldOff className="h-3.5 w-3.5" />}
      </button>
      <button
        type="button"
        title="Remove role (reverts to viewer default)"
        disabled={busy}
        onClick={handleRemove}
        className="rounded-lg p-1.5 transition-colors disabled:opacity-40"
        style={{ background: "var(--surface-muted)", border: "1px solid var(--border-strong)", color: "var(--text-quiet)" }}
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

// ── Allowed user row ──────────────────────────────────────────────────────────

function AllowedUserRow({
  entry,
  fetchFn,
  onRemove,
}: {
  entry: AllowedUserEntry;
  fetchFn: FetchFn;
  onRemove: (key: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const rowKey = entryKey(entry);
  const deleteKey = entry.clerk_user_id ?? entry.email ?? "";

  const handleRemove = async () => {
    if (!deleteKey) return;
    setBusy(true);
    setError(null);
    try {
      await removeAllowedUser(deleteKey, fetchFn);
      onRemove(rowKey);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  const displayName = entry.name ?? entry.email ?? entry.clerk_user_id ?? "—";
  const sub = entry.name && entry.email
    ? entry.email
    : entry.clerk_user_id ?? entry.email ?? "";

  return (
    <div
      className="flex items-center gap-3 rounded-xl px-4 py-3"
      style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}
    >
      <div
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-semibold uppercase"
        style={{ background: "var(--accent)", color: "#fff" }}
      >
        {displayName.slice(0, 1)}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium" style={{ color: "var(--text)" }}>{displayName}</p>
        <p className="truncate text-xs font-mono" style={{ color: "var(--text-quiet)" }}>{sub}</p>
        {error && <p className="mt-0.5 text-xs" style={{ color: "var(--danger)" }}>{error}</p>}
      </div>
      {entry.pending && (
        <span
          className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider"
          style={{ background: "rgba(234,179,8,0.15)", color: "#eab308" }}
          title="Invited by email. Access grants on first sign-in."
        >
          Pending
        </span>
      )}
      <RoleBadge role={entry.role} />
      <button
        type="button"
        title="Remove from allowlist (revokes access)"
        disabled={busy || !deleteKey}
        onClick={() => void handleRemove()}
        className="rounded-lg p-1.5 transition-colors disabled:opacity-40"
        style={{ background: "var(--surface-muted)", border: "1px solid var(--border-strong)", color: "var(--danger, #ef4444)" }}
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

// ── Add to allowlist panel ────────────────────────────────────────────────────

function AddAllowlistPanel({
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
    if (!trimmed) { setError("Enter an email address."); return; }
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
      setRole("viewer");
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
      <p className="text-sm font-medium" style={{ color: "var(--text)" }}>Invite by email</p>
      <p className="text-xs" style={{ color: "var(--text-quiet)" }}>
        Enter an email address. They&apos;ll be pre-authorized; the invite activates the first time they sign in with that email.
      </p>
      <div className="flex gap-2">
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void handleAdd(); }}
          placeholder="name@example.com"
          disabled={busy}
          className="flex-1 rounded-lg px-3 py-2 text-sm focus:outline-none disabled:opacity-50"
          style={{ background: "var(--surface-muted)", border: "1px solid var(--border-strong)", color: "var(--text)" }}
        />
        <select
          value={role}
          disabled={busy}
          onChange={(e) => setRole(e.target.value as MCRole)}
          className="rounded-lg px-2 py-2 text-sm focus:outline-none disabled:opacity-50"
          style={{ background: "var(--surface-muted)", border: "1px solid var(--border-strong)", color: "var(--text)" }}
        >
          <option value="owner">Owner</option>
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
        Non-viewer roles for pending invites default to <code>viewer</code> until they sign in — adjust from Role assignments afterward.
      </p>
      {error && <p className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}
    </div>
  );
}

// ── Content (owner only) ──────────────────────────────────────────────────────

function UserManagementContent() {
  const [users, setUsers] = useState<UserEntry[]>([]);
  const [allowedUsers, setAllowedUsers] = useState<AllowedUserEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const { fetchWithAuth } = useAuthFetch();

  useEffect(() => {
    Promise.all([
      fetchUsers(fetchWithAuth),
      fetchAllowedUsers(fetchWithAuth),
    ])
      .then(([u, a]) => {
        setUsers(u);
        setAllowedUsers(a);
        setLoading(false);
      })
      .catch((e) => {
        setLoadError(e instanceof Error ? e.message : "Failed to load.");
        setLoading(false);
      });
  }, [fetchWithAuth]);

  const handleUpdate = useCallback((updated: UserEntry) => {
    setUsers((prev) => prev.map((u) => u.clerk_user_id === updated.clerk_user_id ? updated : u));
  }, []);

  const handleRemoveRole = useCallback((id: string) => {
    setUsers((prev) => prev.filter((u) => u.clerk_user_id !== id));
  }, []);

  const handleAllowedAdded = useCallback((entry: AllowedUserEntry) => {
    const newKey = entryKey(entry);
    setAllowedUsers((prev) => {
      const exists = prev.some((u) => entryKey(u) === newKey);
      return exists
        ? prev.map((u) => entryKey(u) === newKey ? entry : u)
        : [...prev, entry];
    });
  }, []);

  const handleAllowedRemoved = useCallback((removedKey: string) => {
    setAllowedUsers((prev) => prev.filter((u) => entryKey(u) !== removedKey));
    setUsers((prev) => prev.filter((u) => {
      const byClerk = removedKey === u.clerk_user_id;
      const byEmail = removedKey === `email:${u.email ?? ""}`;
      return !byClerk && !byEmail;
    }));
  }, []);

  return (
    <main className="flex-1 overflow-y-auto" style={{ background: "var(--bg)" }}>
      <div className="max-w-2xl mx-auto px-6 py-8 space-y-10">
        <div>
          <h1 className="text-xl font-semibold" style={{ color: "var(--text)" }}>User Management</h1>
          <p className="mt-1 text-sm" style={{ color: "var(--text-muted)" }}>
            Control who can access Mission Control and what they can do.
          </p>
        </div>

        {loadError && (
          <div
            className="rounded-xl px-4 py-3 text-sm"
            style={{ background: "rgba(239,68,68,0.1)", color: "#ef4444", border: "1px solid rgba(239,68,68,0.2)" }}
          >
            {loadError}
          </div>
        )}

        {/* ── Allowlist ── */}
        <section className="space-y-4">
          <div className="flex items-center gap-2">
            <Lock className="h-4 w-4" style={{ color: "var(--text-quiet)" }} />
            <h2 className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>
              Allowed users ({allowedUsers.length})
            </h2>
          </div>
          <div
            className="rounded-xl px-4 py-3 text-xs"
            style={{ background: "rgba(168,85,247,0.08)", border: "1px solid rgba(168,85,247,0.2)", color: "var(--text-muted)" }}
          >
            Only users on this list can sign in. Anyone not listed is denied access immediately after authentication.
          </div>

          {loading ? (
            <p className="text-sm" style={{ color: "var(--text-quiet)" }}>Loading…</p>
          ) : allowedUsers.length === 0 ? (
            <p className="text-sm" style={{ color: "var(--text-quiet)" }}>No users on the allowlist yet. The next person to sign in will be auto-added as owner.</p>
          ) : (
            allowedUsers.map((u) => (
              <AllowedUserRow
                key={entryKey(u)}
                entry={u}
                fetchFn={fetchWithAuth}
                onRemove={handleAllowedRemoved}
              />
            ))
          )}

          <AddAllowlistPanel fetchFn={fetchWithAuth} onAdded={handleAllowedAdded} />
        </section>

        {/* ── Role permissions reference ── */}
        <section
          className="rounded-xl p-4 space-y-2"
          style={{ background: "var(--surface-strong)", border: "1px solid var(--border)" }}
        >
          <p className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>
            Role permissions
          </p>
          <div className="grid grid-cols-3 gap-2 text-xs" style={{ color: "var(--text-muted)" }}>
            <div>
              <p className="font-semibold" style={{ color: "#c084fc" }}>Owner</p>
              <p>Full access, credentials, user management</p>
            </div>
            <div>
              <p className="font-semibold" style={{ color: "#60a5fa" }}>Builder</p>
              <p>AI, projects, memory, automation — no credentials</p>
            </div>
            <div>
              <p className="font-semibold" style={{ color: "#9ca3af" }}>Viewer</p>
              <p>Read-only access</p>
            </div>
          </div>
        </section>

        {/* ── Role management ── */}
        <section className="space-y-3">
          <h2 className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--text-quiet)" }}>
            Role assignments ({users.length})
          </h2>
          <p className="text-xs" style={{ color: "var(--text-quiet)" }}>
            Adjust roles for users who have already signed in.
          </p>
          {loading ? (
            <p className="text-sm" style={{ color: "var(--text-quiet)" }}>Loading…</p>
          ) : users.length === 0 ? (
            <p className="text-sm" style={{ color: "var(--text-quiet)" }}>No users with explicit role assignments yet.</p>
          ) : (
            users.map((u) => (
              <UserRow
                key={u.clerk_user_id}
                user={u}
                fetchFn={fetchWithAuth}
                onUpdate={handleUpdate}
                onRemove={handleRemoveRole}
              />
            ))
          )}
        </section>
      </div>
    </main>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function UsersPage() {
  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel message="Sign in to access Digidle OS" forceRedirectUrl="/settings/users" />
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <RoleGuard
          require="owner"
          denied={
            <main className="flex-1 flex items-center justify-center" style={{ background: "var(--bg)" }}>
              <p className="text-sm" style={{ color: "var(--text-quiet)" }}>Owner access required.</p>
            </main>
          }
        >
          <UserManagementContent />
        </RoleGuard>
      </SignedIn>
    </DashboardShell>
  );
}

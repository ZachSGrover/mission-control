"use client";

import type { ReactNode } from "react";

import { useRole } from "@/hooks/use-role";
import type { MCRole } from "@/lib/roles";

interface RoleGuardProps {
  /** Minimum role required to render children. */
  require: MCRole;
  /** Rendered while the role is being fetched. Defaults to null (nothing). */
  fallback?: ReactNode;
  /** Rendered when the user doesn't have the required role. Defaults to null. */
  denied?: ReactNode;
  children: ReactNode;
}

const ROLE_RANK: Record<MCRole, number> = { owner: 3, builder: 2, viewer: 1 };

function hasMinRole(userRole: MCRole, required: MCRole): boolean {
  return ROLE_RANK[userRole] >= ROLE_RANK[required];
}

/**
 * Conditionally renders `children` only when the current user meets
 * the minimum `require` role threshold.
 *
 * Usage:
 *   <RoleGuard require="owner">  ← only owners see this
 *     <CredentialsSection />
 *   </RoleGuard>
 */
export function RoleGuard({
  require,
  fallback = null,
  denied = null,
  children,
}: RoleGuardProps) {
  const { role, loading } = useRole();

  if (loading) return <>{fallback}</>;
  if (!role || !hasMinRole(role, require)) return <>{denied}</>;
  return <>{children}</>;
}

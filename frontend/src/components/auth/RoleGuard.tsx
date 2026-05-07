"use client";

import type { ReactNode } from "react";

import { useRole } from "@/hooks/use-role";
import { hasMinRole, type MCRole } from "@/lib/roles";

interface RoleGuardProps {
  /** Minimum role required to render children. */
  require: MCRole;
  /** Rendered while the role is being fetched. Defaults to null (nothing). */
  fallback?: ReactNode;
  /** Rendered when the user doesn't have the required role. Defaults to null. */
  denied?: ReactNode;
  children: ReactNode;
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

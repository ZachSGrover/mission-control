"use client";

// Shell-level invite gate.
//
// Defense-in-depth layer on top of:
//   1. Clerk "Restricted" sign-ups (stops account creation at the door), and
//   2. the backend allowlist (`_check_allowlist`), which fails closed and
//      returns 403 for any signed-in-but-uninvited user.
//
// This component makes that backend decision the single source of truth for
// the *UI shell*: a signed-in user who is not on the allowlist never sees the
// app chrome — only a locked "not approved" panel. We deliberately do NOT
// maintain a second allowlist at the edge; we just surface the backend's
// verdict via POST /api/v1/auth/bootstrap (which runs the allowlist check).

import { type ReactNode } from "react";

import { useQuery } from "@tanstack/react-query";

import { bootstrapUserApiV1AuthBootstrapPost } from "@/api/generated/auth/auth";
import { ApiError } from "@/api/mutator";
import { SignOutButton, isClerkEnabled, useAuth } from "@/auth/clerk";
import { isLocalAuthMode } from "@/auth/localAuth";
import { Button } from "@/components/ui/button";

export function ApprovalGate({ children }: { children: ReactNode }) {
  // Local desktop builds and CI/secretless builds don't use Clerk; the backend
  // still enforces access on every data call, so no shell gate is needed here.
  // These checks are build-constant, so the conditional return is stable.
  if (isLocalAuthMode() || !isClerkEnabled()) {
    return <>{children}</>;
  }
  return <ClerkApprovalGate>{children}</ClerkApprovalGate>;
}

function ClerkApprovalGate({ children }: { children: ReactNode }) {
  const { isLoaded, isSignedIn } = useAuth();

  const approval = useQuery({
    queryKey: ["auth", "approval"],
    queryFn: () => bootstrapUserApiV1AuthBootstrapPost(),
    enabled: isLoaded && Boolean(isSignedIn),
    staleTime: 5 * 60 * 1000,
    // Don't retry an authoritative auth verdict (401/403); do retry transient
    // network/5xx so a backend hiccup never falsely locks out a real user.
    retry: (failureCount, error) => {
      if (
        error instanceof ApiError &&
        (error.status === 401 || error.status === 403)
      ) {
        return false;
      }
      return failureCount < 2;
    },
  });

  if (!isLoaded) {
    return <GateLoading />;
  }

  // Signed-out users are handled upstream (proxy.ts redirects to sign-in, and
  // pages render their own <SignedOut> panels). Pass through untouched.
  if (!isSignedIn) {
    return <>{children}</>;
  }

  if (approval.isPending) {
    return <GateLoading />;
  }

  // The one verdict that locks the shell: backend says "not on the allowlist".
  if (approval.error instanceof ApiError && approval.error.status === 403) {
    return <NotApprovedPanel />;
  }

  // Approved (200) or a transient error we chose to fail-open on. In the
  // transient case the shell loads but every data call is still enforced
  // server-side, so no unapproved data can leak.
  return <>{children}</>;
}

function GateLoading() {
  return (
    <div
      className="flex min-h-screen items-center justify-center"
      style={{ background: "var(--bg)" }}
    >
      <p className="text-sm" style={{ color: "var(--text-muted)" }}>
        Checking access…
      </p>
    </div>
  );
}

function NotApprovedPanel() {
  return (
    <div
      className="flex min-h-screen items-center justify-center p-10 text-center"
      style={{ background: "var(--bg)" }}
    >
      <div
        className="max-w-md rounded-xl px-6 py-8"
        style={{
          background: "var(--surface)",
          border: "1px solid var(--border)",
          boxShadow: "var(--shadow-card)",
        }}
      >
        <h2
          className="text-base font-semibold"
          style={{ color: "var(--text)" }}
        >
          Access not authorized
        </h2>
        <p className="mt-2 text-sm" style={{ color: "var(--text-muted)" }}>
          Your account isn&apos;t on the invite list for this workspace. Ask an
          administrator to invite you, then sign in again.
        </p>
        <SignOutButton>
          <Button className="mt-6" variant="outline" data-testid="approval-gate-signout">
            Sign out
          </Button>
        </SignOutButton>
      </div>
    </div>
  );
}

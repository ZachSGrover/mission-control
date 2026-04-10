"use client";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";

export default function WorkflowsPage() {
  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel
          message="Sign in to access Digidle OS"
          forceRedirectUrl="/workflows"
        />
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <main className="flex flex-col items-center justify-center" style={{ height: "calc(100vh - 64px)" }}>
          <p className="text-slate-400 text-sm">Workflows — coming soon.</p>
        </main>
      </SignedIn>
    </DashboardShell>
  );
}

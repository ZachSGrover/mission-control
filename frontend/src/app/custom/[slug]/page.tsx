"use client";

export const dynamic = "force-dynamic";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Hash } from "lucide-react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { loadLayout } from "@/lib/sidebar-store";

function CustomPageContent() {
  const params = useParams();
  const slug = typeof params?.slug === "string" ? params.slug : Array.isArray(params?.slug) ? params.slug[0] : "";

  const [label, setLabel] = useState<string>("");

  useEffect(() => {
    if (!slug) return;
    const layout = loadLayout();
    const href = `/custom/${slug}`;
    for (const cat of layout.categories) {
      const match = cat.items.find((it) => it.href === href);
      if (match) {
        setLabel(match.label);
        return;
      }
    }
  }, [slug]);

  return (
    <div className="px-6 py-6 max-w-3xl mx-auto w-full">
      <div className="flex items-center gap-3 mb-4">
        <Hash className="h-5 w-5" style={{ color: "var(--text-quiet)" }} />
        <h1 className="text-2xl font-semibold tracking-tight" style={{ color: "var(--text)" }}>
          {label || "Custom Page"}
        </h1>
      </div>

      <div
        className="rounded-lg border p-6"
        style={{ background: "var(--surface)", borderColor: "var(--border)" }}
      >
        <p className="text-sm font-medium mb-1" style={{ color: "var(--text)" }}>
          Custom Page
        </p>
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          This page has been added to your sidebar. Content builder coming soon.
        </p>
        {slug && (
          <p className="mt-4 text-xs" style={{ color: "var(--text-quiet)" }}>
            Slug: <code>{slug}</code>
          </p>
        )}
      </div>
    </div>
  );
}

export default function CustomSlugPage() {
  return (
    <DashboardShell>
      <SignedOut>
        <SignedOutPanel message="Sign in to view this page" forceRedirectUrl="/" />
      </SignedOut>
      <SignedIn>
        <DashboardSidebar />
        <ErrorBoundary>
          <CustomPageContent />
        </ErrorBoundary>
      </SignedIn>
    </DashboardShell>
  );
}

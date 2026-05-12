"use client";

export const dynamic = "force-dynamic";

import { BookOpen, Sparkles } from "lucide-react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";

import { PromptCard, SopCard } from "./components";
import { PROMPT_LIBRARY, SOP_LIBRARY } from "./sops-content";

// ── Section heading ──────────────────────────────────────────────────────────

function SectionHeading({
  Icon,
  label,
  count,
  description,
}: {
  Icon: React.ElementType;
  label: string;
  count: number;
  description: string;
}) {
  return (
    <div className="mb-5">
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4" style={{ color: "var(--text-muted)" }} />
        <h2
          className="text-xs font-semibold uppercase tracking-widest"
          style={{ color: "var(--text-quiet)" }}
        >
          {label}
        </h2>
        <span
          className="rounded-full px-2 py-0.5 text-[10px] font-medium"
          style={{
            background: "var(--surface-strong)",
            color: "var(--text-muted)",
            border: "1px solid var(--border)",
          }}
        >
          {count}
        </span>
      </div>
      <p
        className="mt-1.5 text-sm leading-relaxed"
        style={{ color: "var(--text-muted)" }}
      >
        {description}
      </p>
    </div>
  );
}

// ── Page content ─────────────────────────────────────────────────────────────

function SOPsContent() {
  return (
    <main className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-3xl px-6 py-10 space-y-12">
        {/* Header */}
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold" style={{ color: "var(--text)" }}>
            Mission Control SOPs
          </h1>
          <p
            className="text-sm leading-relaxed"
            style={{ color: "var(--text-muted)" }}
          >
            A builder manual for safely creating tools, bots, workflows, and
            agency systems inside Digidle OS.
          </p>
        </header>

        {/* Section 1 — SOP Library */}
        <section data-testid="sop-library-section">
          <SectionHeading
            Icon={BookOpen}
            label="SOP Library"
            count={SOP_LIBRARY.length}
            description="Read these once, reference whenever. Click View SOP to expand a card."
          />
          <div className="space-y-4">
            {SOP_LIBRARY.map((sop) => (
              <SopCard key={sop.id} sop={sop} />
            ))}
          </div>
        </section>

        {/* Section 2 — Claude Prompt Library */}
        <section data-testid="prompt-library-section">
          <SectionHeading
            Icon={Sparkles}
            label="Claude Prompt Library"
            count={PROMPT_LIBRARY.length}
            description="Copy a prompt and paste it into Claude before kicking off a task. Only prompts have copy buttons."
          />
          <div className="space-y-4">
            {PROMPT_LIBRARY.map((prompt) => (
              <PromptCard key={prompt.id} prompt={prompt} />
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function SOPsPage() {
  return (
    <DashboardShell>
      <DashboardSidebar />
      <SignedIn>
        <SOPsContent />
      </SignedIn>
      <SignedOut>
        <SignedOutPanel
          message="Sign in to read Mission Control SOPs"
          forceRedirectUrl="/memory/sops"
        />
      </SignedOut>
    </DashboardShell>
  );
}

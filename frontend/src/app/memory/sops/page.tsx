"use client";

export const dynamic = "force-dynamic";

import {
  AlertTriangle,
  BookOpen,
  Hammer,
  ShieldCheck,
  Sparkles,
  Upload,
} from "lucide-react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";

import {
  GalleryCard,
  PromptCard,
  SecurityRulesBlock,
  SimpleSopBlock,
  StepBlock,
} from "./components";
import {
  DEVELOPER_SOP,
  EMERGENCY_SOP,
  IMPORT_SOP,
  PROMPT_LIBRARY,
  SECURITY_RULES,
  SOP_GALLERY,
  type Prompt,
} from "./sops-content";

// ── Section heading ──────────────────────────────────────────────────────────

function SectionHeading({
  Icon,
  label,
  count,
  description,
  anchorId,
}: {
  Icon: React.ElementType;
  label: string;
  count?: number;
  description: string;
  anchorId?: string;
}) {
  return (
    <div id={anchorId} className="mb-5 scroll-mt-20">
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4" style={{ color: "var(--text-muted)" }} />
        <h2
          className="text-xs font-semibold uppercase tracking-widest"
          style={{ color: "var(--text-quiet)" }}
        >
          {label}
        </h2>
        {count !== undefined && (
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
        )}
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

// ── Prompt lookup helper ─────────────────────────────────────────────────────

function findPrompt(promptId: string): Prompt {
  const prompt = PROMPT_LIBRARY.find((p) => p.id === promptId);
  if (!prompt) {
    // Should be impossible — promptId references are static. Treat as a build
    // bug rather than a runtime concern, but fail loud during dev.
    throw new Error(`SOP references unknown prompt id: ${promptId}`);
  }
  return prompt;
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
            Step-by-step operating manuals and Claude prompts for building
            safely inside Digidle OS.
          </p>
        </header>

        {/* Gallery — four overview cards */}
        <section data-testid="sop-gallery-section">
          <SectionHeading
            Icon={BookOpen}
            label="SOP Library"
            count={SOP_GALLERY.length}
            description="Four operating manuals. Jump into one, or read the developer SOP top-to-bottom."
          />
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {SOP_GALLERY.map((card) => (
              <GalleryCard key={card.id} card={card} />
            ))}
          </div>
        </section>

        {/* Mission Control Developer SOP — the main step flow */}
        <section data-testid="developer-sop-section">
          <SectionHeading
            Icon={Hammer}
            label="Mission Control Developer SOP"
            count={DEVELOPER_SOP.steps.length}
            description={DEVELOPER_SOP.description}
            anchorId="developer-sop"
          />
          <div className="space-y-4">
            {DEVELOPER_SOP.steps.map((step) => (
              <StepBlock
                key={step.number}
                step={step}
                prompt={findPrompt(step.promptId)}
              />
            ))}
          </div>
        </section>

        {/* Import Existing Code SOP */}
        <section data-testid="import-sop-section" className="scroll-mt-20">
          <SectionHeading
            Icon={Upload}
            label="Import Existing Code SOP"
            description="Move outside-built code into the repo safely. The import prompt is at the bottom of the block."
            anchorId="import-sop"
          />
          <SimpleSopBlock sop={IMPORT_SOP} prompt={findPrompt(IMPORT_SOP.promptId)} />
        </section>

        {/* Emergency Debug SOP */}
        <section data-testid="emergency-sop-section" className="scroll-mt-20">
          <SectionHeading
            Icon={AlertTriangle}
            label="Emergency Debug SOP"
            description="Stop the bleed first, fix the exact issue second."
            anchorId="emergency-sop"
          />
          <SimpleSopBlock
            sop={EMERGENCY_SOP}
            prompt={findPrompt(EMERGENCY_SOP.promptId)}
          />
        </section>

        {/* Security and Live Action Rules */}
        <section data-testid="security-rules-section" className="scroll-mt-20">
          <SectionHeading
            Icon={ShieldCheck}
            label="Security and Live Action Rules"
            description={SECURITY_RULES.description}
            anchorId="security-rules"
          />
          <SecurityRulesBlock
            title={SECURITY_RULES.title}
            description={SECURITY_RULES.description}
            blocks={SECURITY_RULES.blocks}
          />
        </section>

        {/* Claude Prompt Library — full cards in SOP order */}
        <section data-testid="prompt-library-section">
          <SectionHeading
            Icon={Sparkles}
            label="Claude Prompt Library"
            count={PROMPT_LIBRARY.length}
            description="Ten prompts in the same order as the developer SOP. Copy one before kicking off the matching step."
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

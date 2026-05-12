"use client";

export const dynamic = "force-dynamic";

import {
  AlertTriangle,
  BookOpen,
  Hammer,
  ShieldCheck,
  Upload,
} from "lucide-react";

import { SignedIn, SignedOut } from "@/auth/clerk";
import { SignedOutPanel } from "@/components/auth/SignedOutPanel";
import { DashboardSidebar } from "@/components/organisms/DashboardSidebar";
import { DashboardShell } from "@/components/templates/DashboardShell";

import {
  BuildStepCard,
  ExtraStepGroup,
  GalleryCard,
  IntroFolderBlock,
  SafetyRulesBlock,
} from "./components";
import {
  EMERGENCY_FOLDER,
  IMPORT_FOLDER,
  MISSION_CONTROL_BUILD,
  PROMPT_LIBRARY,
  SAFETY_RULES,
  SOP_GALLERY,
  type Prompt,
} from "./sops-content";

// ── Section heading ──────────────────────────────────────────────────────────

function SectionHeading({
  Icon,
  label,
  description,
  anchorId,
  size = "md",
}: {
  Icon: React.ElementType;
  label: string;
  description: string;
  anchorId?: string;
  size?: "md" | "lg";
}) {
  const labelClasses =
    size === "lg"
      ? "text-base font-semibold"
      : "text-xs font-semibold uppercase tracking-widest";
  return (
    <div id={anchorId} className="mb-5 scroll-mt-20">
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4" style={{ color: "var(--text-muted)" }} />
        <h2
          className={labelClasses}
          style={{
            color: size === "lg" ? "var(--text)" : "var(--text-quiet)",
          }}
        >
          {label}
        </h2>
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
            Simple step-by-step build manuals and Claude Code prompts for
            working safely inside Digidle OS.
          </p>
        </header>

        {/* Gallery — four folder cards */}
        <section data-testid="sop-gallery-section">
          <SectionHeading
            Icon={BookOpen}
            label="SOP Library"
            description="Four folders. Mission Control Build is the main one — copy the prompt at each step and run it before moving on."
          />
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {SOP_GALLERY.map((card) => (
              <GalleryCard key={card.id} card={card} />
            ))}
          </div>
        </section>

        {/* Mission Control Build — five main steps + three extras */}
        <section
          data-testid="mission-control-build-section"
          className="scroll-mt-20"
        >
          <SectionHeading
            Icon={Hammer}
            label={MISSION_CONTROL_BUILD.title}
            description={MISSION_CONTROL_BUILD.description}
            anchorId="mission-control-build"
            size="lg"
          />
          <div className="space-y-4">
            {MISSION_CONTROL_BUILD.steps.map((step) => (
              <BuildStepCard
                key={step.promptId}
                step={step}
                prompt={findPrompt(step.promptId)}
              />
            ))}
          </div>

          {/* Extras: When ready for PR / If checks fail / Continue later */}
          <div className="mt-8 space-y-6">
            {MISSION_CONTROL_BUILD.extras.map((extra) => (
              <ExtraStepGroup
                key={extra.step.promptId}
                label={extra.label}
                step={extra.step}
                prompt={findPrompt(extra.step.promptId)}
              />
            ))}
          </div>
        </section>

        {/* Import Existing Code */}
        <section
          data-testid="import-folder-section"
          className="scroll-mt-20"
        >
          <SectionHeading
            Icon={Upload}
            label={IMPORT_FOLDER.title}
            description={IMPORT_FOLDER.description}
            anchorId="import-existing-code"
            size="lg"
          />
          <IntroFolderBlock
            folder={IMPORT_FOLDER}
            prompt={findPrompt(IMPORT_FOLDER.promptId)}
          />
        </section>

        {/* Safety Rules */}
        <section
          data-testid="safety-rules-section"
          className="scroll-mt-20"
        >
          <SectionHeading
            Icon={ShieldCheck}
            label={SAFETY_RULES.title}
            description={SAFETY_RULES.description}
            anchorId="safety-rules"
            size="lg"
          />
          <SafetyRulesBlock
            title={SAFETY_RULES.title}
            description={SAFETY_RULES.description}
            blocks={SAFETY_RULES.blocks}
          />
        </section>

        {/* Emergency Debug */}
        <section
          data-testid="emergency-folder-section"
          className="scroll-mt-20"
        >
          <SectionHeading
            Icon={AlertTriangle}
            label={EMERGENCY_FOLDER.title}
            description={EMERGENCY_FOLDER.description}
            anchorId="emergency-debug"
            size="lg"
          />
          <IntroFolderBlock
            folder={EMERGENCY_FOLDER}
            prompt={findPrompt(EMERGENCY_FOLDER.promptId)}
          />
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

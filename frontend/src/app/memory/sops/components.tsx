"use client";

import { ArrowDown } from "lucide-react";

import { CopyButton } from "@/components/hermes/CopyButton";

import type {
  BuildStep,
  IntroFolder,
  Prompt,
  SopBlock,
  SopGalleryCard,
} from "./sops-content";

// ── Shared atoms ─────────────────────────────────────────────────────────────

function Badge({ label, tone = "muted" }: { label: string; tone?: "muted" | "accent" }) {
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-widest"
      style={
        tone === "accent"
          ? {
              background: "var(--accent-soft)",
              color: "var(--accent-strong)",
              border: "1px solid var(--border)",
            }
          : {
              background: "var(--surface-strong)",
              color: "var(--text-muted)",
              border: "1px solid var(--border)",
            }
      }
    >
      {label}
    </span>
  );
}

function StepNumber({ n }: { n: number }) {
  return (
    <span
      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold"
      style={{
        background: "var(--accent-soft)",
        color: "var(--accent-strong)",
        border: "1px solid var(--border)",
      }}
    >
      {n}
    </span>
  );
}

// ── Block renderer (paragraph / heading / numbered / bullets) ────────────────
//
// Reused by the Safety Rules section. Never renders <pre> — SOPs are read,
// not pasted.

export function SopBlocks({ blocks }: { blocks: SopBlock[] }) {
  return (
    <div className="space-y-4" data-testid="sop-blocks">
      {blocks.map((block, idx) => {
        if (block.type === "heading") {
          return (
            <h4
              key={idx}
              className="text-xs font-semibold uppercase tracking-widest"
              style={{ color: "var(--text-quiet)" }}
            >
              {block.text}
            </h4>
          );
        }
        if (block.type === "paragraph") {
          return (
            <p
              key={idx}
              className="text-sm leading-relaxed"
              style={{ color: "var(--text-muted)" }}
            >
              {block.text}
            </p>
          );
        }
        if (block.type === "numbered") {
          return (
            <ol
              key={idx}
              className="list-decimal pl-5 space-y-1.5 text-sm leading-relaxed"
              style={{ color: "var(--text-muted)" }}
            >
              {block.items.map((item, i) => (
                <li key={i}>{item}</li>
              ))}
            </ol>
          );
        }
        // bullets
        return (
          <ul
            key={idx}
            className="list-disc pl-5 space-y-1 text-sm leading-relaxed"
            style={{ color: "var(--text-muted)" }}
          >
            {block.items.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        );
      })}
    </div>
  );
}

// ── Top-of-page folder card ──────────────────────────────────────────────────
//
// Notion-style folder card. Clicking anchor-jumps to the matching detail
// section. No copy button — these are navigation entries.

export function GalleryCard({ card }: { card: SopGalleryCard }) {
  return (
    <a
      href={card.anchor}
      className="block rounded-2xl p-5 transition-colors hover:bg-white/5"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
      }}
      data-testid={`gallery-card-${card.id}`}
    >
      <h3 className="text-base font-semibold" style={{ color: "var(--text)" }}>
        {card.title}
      </h3>
      <p
        className="mt-2 text-sm leading-relaxed"
        style={{ color: "var(--text-muted)" }}
      >
        {card.description}
      </p>
      <p
        className="mt-3 inline-flex items-center gap-1 text-xs font-medium"
        style={{ color: "var(--accent-strong)" }}
      >
        Open folder
        <ArrowDown className="h-3 w-3" />
      </p>
    </a>
  );
}

// ── Build step card (Mission Control Build main steps + extras) ──────────────
//
// One unified card type for both numbered main steps (1–5) and the smaller
// extra cards (Open PR, Fix failed checks, Continue later). The card carries:
//   - step number badge (only if step.number is set)
//   - title and purpose (plain English for the COO)
//   - small prompt preview (no full body)
//   - Copy button (copies the full prompt body)
//
// Identical visual hierarchy across the two so the page feels consistent.

export function BuildStepCard({
  step,
  prompt,
  ariaLabelPrefix,
}: {
  step: BuildStep;
  prompt: Prompt;
  /** Optional override for tests / extras — defaults to "Step N: <title>". */
  ariaLabelPrefix?: string;
}) {
  const heading =
    ariaLabelPrefix ??
    (step.number !== undefined
      ? `Step ${step.number}: ${step.title}`
      : step.title);

  return (
    <article
      className="rounded-2xl p-5"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
      }}
      data-testid={`build-step-${prompt.id}`}
    >
      <header className="flex items-start gap-3">
        {step.number !== undefined && <StepNumber n={step.number} />}
        <div className="flex-1 min-w-0">
          <h3 className="text-base font-semibold" style={{ color: "var(--text)" }}>
            {heading}
          </h3>
          <p
            className="mt-1.5 text-sm leading-relaxed"
            style={{ color: "var(--text-muted)" }}
          >
            {step.purpose}
          </p>
        </div>
      </header>

      <div
        className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl px-4 py-3"
        style={{
          background: "var(--surface-strong)",
          border: "1px solid var(--border)",
        }}
      >
        <div className="min-w-0">
          <p
            className="text-[10px] font-semibold uppercase tracking-widest"
            style={{ color: "var(--text-quiet)" }}
          >
            Prompt
          </p>
          <p
            className="mt-0.5 text-sm font-medium truncate"
            style={{ color: "var(--text)" }}
          >
            {prompt.title}
          </p>
        </div>
        <CopyButton
          text={prompt.body}
          label="Copy prompt"
          ariaLabel={`Copy ${prompt.title}`}
        />
      </div>

      <pre
        className="mt-3 overflow-x-auto rounded-lg p-3 text-[11px] leading-relaxed whitespace-pre-wrap font-mono"
        style={{
          background: "var(--surface-strong)",
          border: "1px solid var(--border)",
          color: "var(--text-muted)",
        }}
        data-testid={`build-step-preview-${prompt.id}`}
      >
        {prompt.preview}
        {"\n…"}
      </pre>
    </article>
  );
}

// ── Intro + prompt folder (Import + Emergency) ───────────────────────────────
//
// A folder with a single prompt. Same visual language as a BuildStepCard
// (so the page reads consistently) but with the folder title as the heading
// and the folder intro under it.

export function IntroFolderBlock({
  folder,
  prompt,
}: {
  folder: IntroFolder;
  prompt: Prompt;
}) {
  return (
    <article
      id={folder.id}
      className="rounded-2xl p-5 scroll-mt-20"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
      }}
      data-testid={`intro-folder-${folder.id}`}
    >
      <h3 className="text-base font-semibold" style={{ color: "var(--text)" }}>
        {folder.title}
      </h3>
      <p
        className="mt-1.5 text-sm leading-relaxed"
        style={{ color: "var(--text-muted)" }}
      >
        {folder.description}
      </p>
      <p
        className="mt-3 text-sm leading-relaxed"
        style={{ color: "var(--text-muted)" }}
      >
        {folder.intro}
      </p>

      <div
        className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl px-4 py-3"
        style={{
          background: "var(--surface-strong)",
          border: "1px solid var(--border)",
        }}
      >
        <div className="min-w-0">
          <p
            className="text-[10px] font-semibold uppercase tracking-widest"
            style={{ color: "var(--text-quiet)" }}
          >
            Prompt
          </p>
          <p
            className="mt-0.5 text-sm font-medium truncate"
            style={{ color: "var(--text)" }}
          >
            {prompt.title}
          </p>
        </div>
        <CopyButton
          text={prompt.body}
          label="Copy prompt"
          ariaLabel={`Copy ${prompt.title}`}
        />
      </div>

      <pre
        className="mt-3 overflow-x-auto rounded-lg p-3 text-[11px] leading-relaxed whitespace-pre-wrap font-mono"
        style={{
          background: "var(--surface-strong)",
          border: "1px solid var(--border)",
          color: "var(--text-muted)",
        }}
        data-testid={`intro-folder-preview-${folder.id}`}
      >
        {prompt.preview}
        {"\n…"}
      </pre>
    </article>
  );
}

// ── Safety Rules block ───────────────────────────────────────────────────────
//
// Readable structured prose. Explicitly NO copy button. The block also has no
// "Prompt" pill — this is the only folder where the content is meant to be
// read and never copied.

export function SafetyRulesBlock({
  title,
  description,
  blocks,
}: {
  title: string;
  description: string;
  blocks: SopBlock[];
}) {
  return (
    <article
      id="safety-rules"
      className="rounded-2xl p-5 scroll-mt-20"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
      }}
      data-testid="safety-rules-block"
    >
      <h3 className="text-base font-semibold" style={{ color: "var(--text)" }}>
        {title}
      </h3>
      <p
        className="mt-1.5 text-sm leading-relaxed"
        style={{ color: "var(--text-muted)" }}
      >
        {description}
      </p>
      <div className="mt-4">
        <SopBlocks blocks={blocks} />
      </div>
    </article>
  );
}

// ── Extra-step sub-section header (for "When ready for PR" etc.) ────────────
//
// A small label rendered above a single BuildStepCard so the three extras
// inside Mission Control Build feel like grouped follow-ups rather than
// random sixth/seventh/eighth steps.

export function ExtraStepGroup({
  label,
  step,
  prompt,
}: {
  label: string;
  step: BuildStep;
  prompt: Prompt;
}) {
  return (
    <div className="space-y-2" data-testid={`extra-group-${prompt.id}`}>
      <h4
        className="text-[10px] font-semibold uppercase tracking-widest"
        style={{ color: "var(--text-quiet)" }}
      >
        {label}
      </h4>
      <BuildStepCard step={step} prompt={prompt} />
    </div>
  );
}

// ── (Re-export the badge for ad-hoc use) ─────────────────────────────────────

export { Badge };

"use client";

import { ArrowDown } from "lucide-react";

import { CopyButton } from "@/components/hermes/CopyButton";

import type {
  DeveloperStep,
  Prompt,
  SimpleSop,
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

function UpdatedLabel({ date }: { date: string }) {
  return (
    <span className="text-[11px]" style={{ color: "var(--text-quiet)" }}>
      Updated {date}
    </span>
  );
}

// ── Block renderer (paragraph / heading / numbered / bullets) ────────────────

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

// ── Top-of-page SOP gallery card ─────────────────────────────────────────────
//
// Clicking the card anchor-jumps to the detail section below. No copy button —
// these are navigation entries, not the canonical content.

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
        Jump to SOP
        <ArrowDown className="h-3 w-3" />
      </p>
    </a>
  );
}

// ── Developer SOP step block ─────────────────────────────────────────────────
//
// Each Developer SOP step shows: numbered badge, title, purpose, and a small
// inline prompt reference with the matching Copy button. The compact ref keeps
// the page scannable; the bottom Prompt Library has the full card with preview.

export function StepBlock({
  step,
  prompt,
}: {
  step: DeveloperStep;
  prompt: Prompt;
}) {
  return (
    <article
      className="rounded-2xl p-5"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
      }}
      data-testid={`step-${step.number}`}
    >
      <div className="flex items-center gap-3">
        <span
          className="flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold"
          style={{
            background: "var(--accent-soft)",
            color: "var(--accent-strong)",
            border: "1px solid var(--border)",
          }}
        >
          {step.number}
        </span>
        <h3 className="text-base font-semibold" style={{ color: "var(--text)" }}>
          Step {step.number}: {step.title}
        </h3>
      </div>

      <p
        className="mt-3 text-sm leading-relaxed"
        style={{ color: "var(--text-muted)" }}
      >
        {step.purpose}
      </p>

      <CompactPromptRef prompt={prompt} stepNumber={step.number} />
    </article>
  );
}

// ── Inline prompt reference (compact) ────────────────────────────────────────
//
// A small "use this prompt" callout shown inside a Step or a SimpleSopBlock.
// Shows only the title + copy button — the full card with preview lives in
// the Prompt Library section.

export function CompactPromptRef({
  prompt,
  stepNumber,
}: {
  prompt: Prompt;
  stepNumber?: number;
}) {
  const refLabel = stepNumber !== undefined ? `Step ${stepNumber} prompt` : "Prompt";
  return (
    <div
      className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl px-4 py-3"
      style={{
        background: "var(--surface-strong)",
        border: "1px solid var(--border)",
      }}
      data-testid={`compact-prompt-${prompt.id}`}
    >
      <div className="min-w-0">
        <p
          className="text-[10px] font-semibold uppercase tracking-widest"
          style={{ color: "var(--text-quiet)" }}
        >
          {refLabel}
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
  );
}

// ── Simple SOP block (Import / Emergency) ────────────────────────────────────
//
// Title + description + numbered substeps + a single CompactPromptRef.

export function SimpleSopBlock({
  sop,
  prompt,
}: {
  sop: SimpleSop;
  prompt: Prompt;
}) {
  return (
    <article
      id={sop.id}
      className="rounded-2xl p-5"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
      }}
      data-testid={`simple-sop-${sop.id}`}
    >
      <h3 className="text-base font-semibold" style={{ color: "var(--text)" }}>
        {sop.title}
      </h3>
      <p
        className="mt-1.5 text-sm leading-relaxed"
        style={{ color: "var(--text-muted)" }}
      >
        {sop.description}
      </p>
      <ol
        className="mt-4 list-decimal pl-5 space-y-1.5 text-sm leading-relaxed"
        style={{ color: "var(--text-muted)" }}
      >
        {sop.steps.map((step, i) => (
          <li key={i}>{step}</li>
        ))}
      </ol>
      <CompactPromptRef prompt={prompt} />
    </article>
  );
}

// ── Security and Live Action Rules block ─────────────────────────────────────
//
// Plain readable prose. No copy button. Reuses SopBlocks for the actual content.

export function SecurityRulesBlock({
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
      id="security-rules"
      className="rounded-2xl p-5"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
      }}
      data-testid="security-rules-block"
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

// ── Full prompt card (used in the Claude Prompt Library section) ─────────────
//
// Step number badge (when applicable) + title + when-to-use + description +
// two-line preview + Copy button. SOPs / step blocks / security do NOT render
// this — only the bottom library.

export function PromptCard({ prompt }: { prompt: Prompt }) {
  return (
    <article
      className="rounded-2xl p-5 transition-colors"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
      }}
      data-testid={`prompt-card-${prompt.id}`}
    >
      <header className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {prompt.step !== undefined && <Badge label={`Step ${prompt.step}`} tone="accent" />}
          <Badge label="Prompt" />
        </div>
        <CopyButton
          text={prompt.body}
          label="Copy prompt"
          ariaLabel={`Copy ${prompt.title}`}
        />
      </header>

      <h3 className="mt-3 text-base font-semibold" style={{ color: "var(--text)" }}>
        {prompt.title}
      </h3>

      <p
        className="mt-1.5 text-xs italic"
        style={{ color: "var(--text-quiet)" }}
      >
        When to use: {prompt.whenToUse}
      </p>

      <p
        className="mt-2 text-sm leading-relaxed"
        style={{ color: "var(--text-muted)" }}
      >
        {prompt.description}
      </p>

      <pre
        className="mt-4 overflow-x-auto rounded-lg p-3 text-[11px] leading-relaxed whitespace-pre-wrap font-mono"
        style={{
          background: "var(--surface-strong)",
          border: "1px solid var(--border)",
          color: "var(--text-muted)",
        }}
        data-testid={`prompt-preview-${prompt.id}`}
      >
        {prompt.preview}
        {"\n…"}
      </pre>

      <footer className="mt-3">
        <UpdatedLabel date={prompt.updated} />
      </footer>
    </article>
  );
}

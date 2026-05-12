"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { CopyButton } from "@/components/hermes/CopyButton";

import type { Prompt, Sop, SopBlock } from "./sops-content";

// ── Shared atoms ─────────────────────────────────────────────────────────────

function CategoryBadge({ label }: { label: string }) {
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-widest"
      style={{
        background: "var(--accent-soft)",
        color: "var(--accent-strong)",
        border: "1px solid var(--border)",
      }}
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

// ── SOP block renderer ───────────────────────────────────────────────────────
//
// Normal SOPs render as readable prose: short paragraphs, sub-headings,
// numbered steps, and simple bullet lists. Never a monospace code block —
// SOPs are for the COO to read, not paste.

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

// ── SOP card ─────────────────────────────────────────────────────────────────
//
// Notion-style gallery card. Click "View SOP" to expand. SOP cards do NOT
// have copy buttons — they're meant to be read, not copied. Copy is only on
// Claude prompt cards below.

export function SopCard({ sop }: { sop: Sop }) {
  const [open, setOpen] = useState(false);

  return (
    <article
      className="rounded-2xl p-5 transition-colors"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
      }}
      data-testid={`sop-card-${sop.id}`}
    >
      <header className="flex items-center justify-between gap-3">
        <CategoryBadge label={sop.category} />
        <UpdatedLabel date={sop.updated} />
      </header>

      <h3
        className="mt-3 text-base font-semibold"
        style={{ color: "var(--text)" }}
      >
        {sop.title}
      </h3>
      <p
        className="mt-1.5 text-sm leading-relaxed"
        style={{ color: "var(--text-muted)" }}
      >
        {sop.description}
      </p>

      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        data-testid={`sop-toggle-${sop.id}`}
        className="mt-4 inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium transition-colors hover:bg-white/5"
        style={{
          borderColor: "var(--border)",
          color: open ? "var(--accent-strong)" : "var(--text-muted)",
        }}
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5" />
        )}
        {open ? "Hide SOP" : "View SOP"}
      </button>

      {open && (
        <div
          className="mt-5 rounded-xl p-4"
          style={{
            background: "var(--surface-strong)",
            border: "1px solid var(--border)",
          }}
          data-testid={`sop-body-${sop.id}`}
        >
          <SopBlocks blocks={sop.blocks} />
        </div>
      )}
    </article>
  );
}

// ── Prompt card ──────────────────────────────────────────────────────────────
//
// Only prompt cards expose a Copy button. The full prompt is on the clipboard
// after click; the card itself only shows a preview so the gallery stays
// scannable. Copy failure handling is inherited from the shared CopyButton.

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
        <CategoryBadge label="Prompt" />
        <CopyButton
          text={prompt.body}
          label="Copy prompt"
          ariaLabel={`Copy ${prompt.title}`}
        />
      </header>

      <h3
        className="mt-3 text-base font-semibold"
        style={{ color: "var(--text)" }}
      >
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

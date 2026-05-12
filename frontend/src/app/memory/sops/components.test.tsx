import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PromptCard, SopBlocks, SopCard } from "./components";
import { PROMPT_LIBRARY, SOP_LIBRARY, type Sop } from "./sops-content";

// ── SOP library shape ────────────────────────────────────────────────────────

describe("SOP_LIBRARY (data contract)", () => {
  it("contains exactly the six expected SOPs in order", () => {
    expect(SOP_LIBRARY.map((s) => s.id)).toEqual([
      "mission-control-build-sop",
      "github-branch-workflow",
      "safety-rules",
      "bot-workflow-build-rules",
      "render-deployment-rules",
      "emergency-rules",
    ]);
  });

  it("every SOP has a non-empty title, category, description, and at least one block", () => {
    for (const sop of SOP_LIBRARY) {
      expect(sop.title.length).toBeGreaterThan(0);
      expect(sop.category.length).toBeGreaterThan(0);
      expect(sop.description.length).toBeGreaterThan(0);
      expect(sop.blocks.length).toBeGreaterThan(0);
    }
  });

  it("no SOP body is rendered as a giant monospace dump — content is structured blocks", () => {
    // The block-renderer in components.tsx maps heading / paragraph / numbered
    // / bullets to readable HTML, never to <pre> / monospace. This test just
    // asserts the data shape — the renderer test below covers the visual.
    for (const sop of SOP_LIBRARY) {
      for (const block of sop.blocks) {
        expect(["heading", "paragraph", "numbered", "bullets"]).toContain(
          block.type,
        );
      }
    }
  });
});

// ── Prompt library shape ─────────────────────────────────────────────────────

describe("PROMPT_LIBRARY (data contract)", () => {
  it("contains exactly the six expected prompts in order", () => {
    expect(PROMPT_LIBRARY.map((p) => p.id)).toEqual([
      "start-development-safely",
      "import-existing-code",
      "build-safe-bot-or-tool",
      "run-safety-check",
      "open-pr-summary",
      "emergency-debug",
    ]);
  });

  it("Import Existing Code prompt is present with the exact title and the eleven-step body", () => {
    const importPrompt = PROMPT_LIBRARY.find(
      (p) => p.id === "import-existing-code",
    );
    expect(importPrompt).toBeDefined();
    expect(importPrompt?.title).toBe("Import Existing Code Into Mission Control");
    // The body must include each of the eleven step headers so that copying
    // the prompt actually produces the safe-import flow.
    for (let n = 1; n <= 11; n += 1) {
      expect(importPrompt?.body).toContain(`Step ${n}:`);
    }
    expect(importPrompt?.body).toContain("incoming/coo-import/");
    expect(importPrompt?.body).toContain("coo/import-existing-code");
  });

  it("every prompt has a non-empty whenToUse, description, preview, and body", () => {
    for (const prompt of PROMPT_LIBRARY) {
      expect(prompt.whenToUse.length).toBeGreaterThan(0);
      expect(prompt.description.length).toBeGreaterThan(0);
      expect(prompt.preview.length).toBeGreaterThan(0);
      expect(prompt.body.length).toBeGreaterThan(prompt.preview.length);
    }
  });
});

// ── SopBlocks renderer ───────────────────────────────────────────────────────

describe("SopBlocks renderer", () => {
  it("renders each block type with the right HTML tag", () => {
    render(
      <SopBlocks
        blocks={[
          { type: "heading", text: "Hello heading" },
          { type: "paragraph", text: "Hello paragraph" },
          { type: "numbered", items: ["one", "two"] },
          { type: "bullets", items: ["alpha", "beta"] },
        ]}
      />,
    );

    // Heading → h4
    const h4 = screen.getByText("Hello heading");
    expect(h4.tagName).toBe("H4");

    // Paragraph → p
    expect(screen.getByText("Hello paragraph").tagName).toBe("P");

    // Numbered → ol with li children
    const one = screen.getByText("one");
    expect(one.tagName).toBe("LI");
    expect(one.parentElement?.tagName).toBe("OL");

    // Bullets → ul with li children
    const alpha = screen.getByText("alpha");
    expect(alpha.tagName).toBe("LI");
    expect(alpha.parentElement?.tagName).toBe("UL");
  });

  it("does not render a <pre> monospace dump for any block", () => {
    const { container } = render(
      <SopBlocks
        blocks={[
          { type: "paragraph", text: "Some paragraph" },
          { type: "numbered", items: ["a", "b"] },
        ]}
      />,
    );
    expect(container.querySelector("pre")).toBeNull();
  });
});

// ── SopCard ──────────────────────────────────────────────────────────────────

const FIXTURE_SOP: Sop = {
  id: "fixture",
  title: "Fixture SOP",
  category: "Workflow",
  description: "A fixture SOP for tests.",
  updated: "2026-05-12",
  blocks: [
    { type: "paragraph", text: "Body paragraph one." },
    { type: "numbered", items: ["First step", "Second step"] },
  ],
};

describe("SopCard", () => {
  it("renders title, category, description, and updated date in the collapsed state", () => {
    render(<SopCard sop={FIXTURE_SOP} />);
    expect(screen.getByText("Fixture SOP")).toBeInTheDocument();
    expect(screen.getByText("Workflow")).toBeInTheDocument();
    expect(screen.getByText("A fixture SOP for tests.")).toBeInTheDocument();
    expect(screen.getByText(/Updated 2026-05-12/)).toBeInTheDocument();
  });

  it("does NOT render a copy button — SOPs are read-only in the UI", () => {
    render(<SopCard sop={FIXTURE_SOP} />);
    // The shared CopyButton component renders text "Copy" or aria-label
    // matching "Copy …". SOP cards must not include either.
    expect(screen.queryByRole("button", { name: /^copy/i })).toBeNull();
  });

  it("body is hidden until View SOP is clicked, then visible", () => {
    render(<SopCard sop={FIXTURE_SOP} />);
    expect(screen.queryByText("Body paragraph one.")).toBeNull();

    fireEvent.click(screen.getByTestId("sop-toggle-fixture"));
    expect(screen.getByText("Body paragraph one.")).toBeInTheDocument();
    expect(screen.getByText("First step")).toBeInTheDocument();
  });

  it("toggle button flips its aria-expanded and label", () => {
    render(<SopCard sop={FIXTURE_SOP} />);
    const btn = screen.getByTestId("sop-toggle-fixture");
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    expect(btn.textContent).toContain("View SOP");

    fireEvent.click(btn);
    expect(btn.getAttribute("aria-expanded")).toBe("true");
    expect(btn.textContent).toContain("Hide SOP");
  });
});

// ── PromptCard ───────────────────────────────────────────────────────────────

describe("PromptCard", () => {
  const FIXTURE_PROMPT = PROMPT_LIBRARY[0];

  it("renders title, when-to-use line, description, and updated date", () => {
    render(<PromptCard prompt={FIXTURE_PROMPT} />);
    expect(screen.getByText(FIXTURE_PROMPT.title)).toBeInTheDocument();
    expect(
      screen.getByText(new RegExp(FIXTURE_PROMPT.whenToUse.slice(0, 20))),
    ).toBeInTheDocument();
    expect(screen.getByText(FIXTURE_PROMPT.description)).toBeInTheDocument();
    expect(screen.getByText(/Updated/)).toBeInTheDocument();
  });

  it("renders a Copy button (this is the only card type that does)", () => {
    render(<PromptCard prompt={FIXTURE_PROMPT} />);
    const copy = screen.getByRole("button", {
      name: new RegExp(`copy ${FIXTURE_PROMPT.title}`, "i"),
    });
    expect(copy).toBeInTheDocument();
  });

  it("shows a preview of the prompt body but not the full body inline", () => {
    render(<PromptCard prompt={FIXTURE_PROMPT} />);
    const preview = screen.getByTestId(`prompt-preview-${FIXTURE_PROMPT.id}`);
    expect(preview.textContent).toContain(FIXTURE_PROMPT.preview.split("\n")[0]);
    // The full body line beyond the preview should not be rendered inline.
    const bodyLines = FIXTURE_PROMPT.body.split("\n");
    const farLine = bodyLines.find((line) => line.startsWith("Task:"));
    if (farLine) {
      expect(screen.queryByText(farLine)).toBeNull();
    }
  });
});

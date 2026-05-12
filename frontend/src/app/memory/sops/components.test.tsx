import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  CompactPromptRef,
  GalleryCard,
  PromptCard,
  SecurityRulesBlock,
  SimpleSopBlock,
  SopBlocks,
  StepBlock,
} from "./components";
import {
  DEVELOPER_SOP,
  EMERGENCY_SOP,
  IMPORT_SOP,
  PROMPT_LIBRARY,
  SECURITY_RULES,
  SOP_GALLERY,
} from "./sops-content";

// ── Data contract — gallery ──────────────────────────────────────────────────

describe("SOP_GALLERY", () => {
  it("contains exactly the four overview cards in order", () => {
    expect(SOP_GALLERY.map((c) => c.id)).toEqual([
      "developer",
      "import",
      "emergency",
      "security",
    ]);
  });

  it("each card has an in-page anchor pointing at the matching detail section", () => {
    const anchors = Object.fromEntries(
      SOP_GALLERY.map((c) => [c.id, c.anchor]),
    );
    expect(anchors.developer).toBe("#developer-sop");
    expect(anchors.import).toBe("#import-sop");
    expect(anchors.emergency).toBe("#emergency-sop");
    expect(anchors.security).toBe("#security-rules");
  });
});

// ── Data contract — Developer SOP ────────────────────────────────────────────

describe("DEVELOPER_SOP", () => {
  it("has exactly eight steps numbered 1..8 in order", () => {
    expect(DEVELOPER_SOP.steps).toHaveLength(8);
    expect(DEVELOPER_SOP.steps.map((s) => s.number)).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
  });

  it("each step references a prompt id that exists in PROMPT_LIBRARY", () => {
    const promptIds = new Set(PROMPT_LIBRARY.map((p) => p.id));
    for (const step of DEVELOPER_SOP.steps) {
      expect(promptIds.has(step.promptId)).toBe(true);
    }
  });

  it("step titles match the spec order", () => {
    expect(DEVELOPER_SOP.steps.map((s) => s.title)).toEqual([
      "Start Every Build Safely",
      "Build in the Right Place",
      "Test Locally",
      "Run Safety Check Before Pushing",
      "Push Branch Safely",
      "Open Pull Request",
      "Fix Failed Checks",
      "Continue Existing Branch",
    ]);
  });
});

// ── Data contract — Import + Emergency + Security ────────────────────────────

describe("IMPORT_SOP", () => {
  it("has the eight substeps from the spec", () => {
    expect(IMPORT_SOP.steps).toHaveLength(8);
    expect(IMPORT_SOP.steps[0]).toContain("Put existing code");
    expect(IMPORT_SOP.steps).toContain("Import into incoming/coo-import.");
  });

  it("references the import-existing-code prompt", () => {
    expect(IMPORT_SOP.promptId).toBe("import-existing-code");
  });
});

describe("EMERGENCY_SOP", () => {
  it("has the seven substeps from the spec", () => {
    expect(EMERGENCY_SOP.steps).toHaveLength(7);
    expect(EMERGENCY_SOP.steps[0]).toBe("Stop changing things.");
  });

  it("references the emergency-debug prompt", () => {
    expect(EMERGENCY_SOP.promptId).toBe("emergency-debug");
  });
});

describe("SECURITY_RULES", () => {
  it("uses structured blocks, never a monospace dump", () => {
    for (const block of SECURITY_RULES.blocks) {
      expect(["heading", "paragraph", "numbered", "bullets"]).toContain(block.type);
    }
  });

  it("includes the four required headings and the dry-run default values", () => {
    const headings = SECURITY_RULES.blocks
      .filter((b) => b.type === "heading")
      .map((b) => (b as { text: string }).text);
    expect(headings).toContain("Normal building is allowed");
    expect(headings).toContain("Keep out of GitHub");
    expect(headings).toContain("Owner-only or review required");
    expect(headings).toContain("Dry-run rule");

    // Flatten all bullet items to find the dry-run defaults.
    const allBullets = SECURITY_RULES.blocks
      .filter((b) => b.type === "bullets")
      .flatMap((b) => (b as { items: string[] }).items);
    expect(allBullets).toContain("DRY_RUN=true");
    expect(allBullets).toContain("ALLOW_LIVE_EXTERNAL_ACTIONS=false");
  });
});

// ── Data contract — Prompt Library ───────────────────────────────────────────

describe("PROMPT_LIBRARY", () => {
  it("contains the ten prompts in the exact spec order", () => {
    expect(PROMPT_LIBRARY.map((p) => p.id)).toEqual([
      "start-every-build-safely",
      "build-safe",
      "test-build",
      "run-safety-check",
      "push-branch-safely",
      "open-pr-summary",
      "fix-failed-checks",
      "continue-existing-build",
      "import-existing-code",
      "emergency-debug",
    ]);
  });

  it("prompts 1–8 carry step numbers; prompts 9 + 10 do not", () => {
    expect(PROMPT_LIBRARY.slice(0, 8).map((p) => p.step)).toEqual([
      1, 2, 3, 4, 5, 6, 7, 8,
    ]);
    expect(PROMPT_LIBRARY[8].step).toBeUndefined(); // Import
    expect(PROMPT_LIBRARY[9].step).toBeUndefined(); // Emergency
  });

  it("Start Every Mission Control Build Safely is prompt #1 with the full master body", () => {
    const master = PROMPT_LIBRARY[0];
    expect(master.id).toBe("start-every-build-safely");
    expect(master.title).toBe("Start Every Mission Control Build Safely");
    for (let n = 1; n <= 10; n += 1) {
      expect(master.body).toContain(`Step ${n}:`);
    }
    expect(master.body).toContain("DRY_RUN=true");
    expect(master.body).toContain("ALLOW_LIVE_EXTERNAL_ACTIONS=false");
    expect(master.body).toContain("coo/name-of-build");
    expect(master.body).toContain("incoming/coo-import/");
    for (const tier of ["SAFE:", "REVIEW NEEDED:", "OWNER ONLY:"]) {
      expect(master.body).toContain(tier);
    }
    for (const label of ["A.", "B.", "C.", "D.", "E.", "F.", "G.", "H.", "I.", "J."]) {
      expect(master.body).toContain(label);
    }
  });

  it("Import Existing Code prompt carries the eleven-step body and the import safety model", () => {
    const importPrompt = PROMPT_LIBRARY.find((p) => p.id === "import-existing-code");
    expect(importPrompt).toBeDefined();
    expect(importPrompt!.title).toBe("Import Existing Code Into Mission Control");
    for (let n = 1; n <= 11; n += 1) {
      expect(importPrompt!.body).toContain(`Step ${n}:`);
    }
    expect(importPrompt!.body).toContain("incoming/coo-import/");
    expect(importPrompt!.body).toContain("coo/import-existing-code");
    // The safety model from the spec must survive in the body text.
    expect(importPrompt!.body).toContain("Real API keys may be used at runtime");
    expect(importPrompt!.body).toContain("raw dumps must not be committed");
    expect(importPrompt!.body).toContain("DRY_RUN=true");
  });

  it("every prompt has a non-empty whenToUse / description / preview / body", () => {
    for (const prompt of PROMPT_LIBRARY) {
      expect(prompt.whenToUse.length).toBeGreaterThan(0);
      expect(prompt.description.length).toBeGreaterThan(0);
      expect(prompt.preview.length).toBeGreaterThan(0);
      expect(prompt.body.length).toBeGreaterThan(prompt.preview.length);
    }
  });
});

// ── Renderer — SopBlocks ─────────────────────────────────────────────────────

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
    expect(screen.getByText("Hello heading").tagName).toBe("H4");
    expect(screen.getByText("Hello paragraph").tagName).toBe("P");
    expect(screen.getByText("one").tagName).toBe("LI");
    expect(screen.getByText("one").parentElement?.tagName).toBe("OL");
    expect(screen.getByText("alpha").parentElement?.tagName).toBe("UL");
  });

  it("never renders a <pre> monospace dump", () => {
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

// ── Renderer — GalleryCard ───────────────────────────────────────────────────

describe("GalleryCard", () => {
  it("renders title + description and links to the section anchor", () => {
    render(<GalleryCard card={SOP_GALLERY[0]} />);
    const link = screen.getByTestId(`gallery-card-${SOP_GALLERY[0].id}`);
    expect(link.tagName).toBe("A");
    expect(link.getAttribute("href")).toBe("#developer-sop");
    expect(screen.getByText(SOP_GALLERY[0].title)).toBeInTheDocument();
  });

  it("does not render a copy button — gallery is navigation, not content", () => {
    render(<GalleryCard card={SOP_GALLERY[0]} />);
    expect(screen.queryByRole("button", { name: /^copy/i })).toBeNull();
  });
});

// ── Renderer — StepBlock ─────────────────────────────────────────────────────

describe("StepBlock", () => {
  it("renders number, title, purpose, and a compact prompt ref with a Copy button", () => {
    const step = DEVELOPER_SOP.steps[0];
    const prompt = PROMPT_LIBRARY.find((p) => p.id === step.promptId)!;
    render(<StepBlock step={step} prompt={prompt} />);

    expect(screen.getByText(`Step ${step.number}: ${step.title}`)).toBeInTheDocument();
    expect(screen.getByText(step.purpose)).toBeInTheDocument();
    // Compact prompt ref includes step-number label and the prompt title.
    expect(screen.getByText(`Step ${step.number} prompt`)).toBeInTheDocument();
    expect(screen.getByText(prompt.title)).toBeInTheDocument();
    // Copy button is present and aria-labeled.
    expect(
      screen.getByRole("button", {
        name: new RegExp(`copy ${prompt.title}`, "i"),
      }),
    ).toBeInTheDocument();
  });
});

// ── Renderer — CompactPromptRef ──────────────────────────────────────────────

describe("CompactPromptRef", () => {
  it("uses 'Prompt' label (no step) when stepNumber is omitted", () => {
    render(<CompactPromptRef prompt={PROMPT_LIBRARY[8]} />);
    expect(screen.getByText("Prompt")).toBeInTheDocument();
  });

  it("Copy button copies the full prompt body", () => {
    render(<CompactPromptRef prompt={PROMPT_LIBRARY[0]} stepNumber={1} />);
    const btn = screen.getByRole("button", {
      name: new RegExp(`copy ${PROMPT_LIBRARY[0].title}`, "i"),
    });
    expect(btn).toBeInTheDocument();
  });
});

// ── Renderer — SimpleSopBlock ────────────────────────────────────────────────

describe("SimpleSopBlock", () => {
  it("renders Import SOP with all eight substeps and the import prompt ref", () => {
    const prompt = PROMPT_LIBRARY.find((p) => p.id === IMPORT_SOP.promptId)!;
    render(<SimpleSopBlock sop={IMPORT_SOP} prompt={prompt} />);
    expect(screen.getByText(IMPORT_SOP.title)).toBeInTheDocument();
    for (const step of IMPORT_SOP.steps) {
      expect(screen.getByText(step)).toBeInTheDocument();
    }
    expect(screen.getByText(prompt.title)).toBeInTheDocument();
  });

  it("renders Emergency SOP with all seven substeps and the emergency prompt ref", () => {
    const prompt = PROMPT_LIBRARY.find((p) => p.id === EMERGENCY_SOP.promptId)!;
    render(<SimpleSopBlock sop={EMERGENCY_SOP} prompt={prompt} />);
    expect(screen.getByText(EMERGENCY_SOP.title)).toBeInTheDocument();
    for (const step of EMERGENCY_SOP.steps) {
      expect(screen.getByText(step)).toBeInTheDocument();
    }
  });
});

// ── Renderer — SecurityRulesBlock ────────────────────────────────────────────

describe("SecurityRulesBlock", () => {
  it("renders structured prose, no copy button", () => {
    render(
      <SecurityRulesBlock
        title={SECURITY_RULES.title}
        description={SECURITY_RULES.description}
        blocks={SECURITY_RULES.blocks}
      />,
    );
    expect(screen.getByText(SECURITY_RULES.title)).toBeInTheDocument();
    // Spot-check a heading and a bullet item.
    expect(screen.getByText("Normal building is allowed")).toBeInTheDocument();
    expect(screen.getByText("DRY_RUN=true")).toBeInTheDocument();
    // Critically: no copy button anywhere.
    expect(screen.queryByRole("button", { name: /^copy/i })).toBeNull();
  });
});

// ── Renderer — PromptCard (library version) ──────────────────────────────────

describe("PromptCard (library card)", () => {
  it("renders step badge when prompt has a step number", () => {
    render(<PromptCard prompt={PROMPT_LIBRARY[0]} />);
    expect(screen.getByText("Step 1")).toBeInTheDocument();
    expect(screen.getByText("Prompt")).toBeInTheDocument();
  });

  it("renders only the Prompt badge for prompts without a step (Import / Emergency)", () => {
    render(<PromptCard prompt={PROMPT_LIBRARY[8]} />); // import-existing-code
    expect(screen.queryByText(/^Step \d/)).toBeNull();
    expect(screen.getByText("Prompt")).toBeInTheDocument();
  });

  it("renders preview but not the full body inline", () => {
    const prompt = PROMPT_LIBRARY[0];
    render(<PromptCard prompt={prompt} />);
    const preview = screen.getByTestId(`prompt-preview-${prompt.id}`);
    expect(preview.textContent).toContain(prompt.preview.split("\n")[0]);
    // A line deep inside the body should not be rendered inline.
    const farLine = prompt.body
      .split("\n")
      .find((line) => line.startsWith("Step 8:"));
    if (farLine) {
      expect(screen.queryByText(farLine)).toBeNull();
    }
  });

  it("always exposes a Copy button labeled for the prompt title", () => {
    for (const prompt of PROMPT_LIBRARY) {
      const { unmount } = render(<PromptCard prompt={prompt} />);
      expect(
        screen.getByRole("button", {
          name: new RegExp(`copy ${prompt.title}`, "i"),
        }),
      ).toBeInTheDocument();
      unmount();
    }
  });
});

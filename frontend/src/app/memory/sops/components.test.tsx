import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  BuildStepCard,
  ExtraStepGroup,
  GalleryCard,
  IntroFolderBlock,
  SafetyRulesBlock,
  SopBlocks,
} from "./components";
import {
  EMERGENCY_FOLDER,
  IMPORT_FOLDER,
  MISSION_CONTROL_BUILD,
  PROMPT_LIBRARY,
  SAFETY_RULES,
  SOP_GALLERY,
} from "./sops-content";

// ── Data contract — gallery (4 folder cards) ────────────────────────────────

describe("SOP_GALLERY", () => {
  it("contains exactly the four folder cards in order", () => {
    expect(SOP_GALLERY.map((c) => c.id)).toEqual([
      "mission-control-build",
      "import-existing-code",
      "safety-rules",
      "emergency-debug",
    ]);
  });

  it("Mission Control Build is the first card", () => {
    expect(SOP_GALLERY[0].title).toBe("Mission Control Build");
  });

  it("each card's anchor points at the matching detail section", () => {
    expect(SOP_GALLERY[0].anchor).toBe("#mission-control-build");
    expect(SOP_GALLERY[1].anchor).toBe("#import-existing-code");
    expect(SOP_GALLERY[2].anchor).toBe("#safety-rules");
    expect(SOP_GALLERY[3].anchor).toBe("#emergency-debug");
  });
});

// ── Data contract — Mission Control Build ───────────────────────────────────

describe("MISSION_CONTROL_BUILD", () => {
  it("has exactly five main steps numbered 1..5 in spec order", () => {
    expect(MISSION_CONTROL_BUILD.steps).toHaveLength(5);
    expect(MISSION_CONTROL_BUILD.steps.map((s) => s.number)).toEqual([1, 2, 3, 4, 5]);
    expect(MISSION_CONTROL_BUILD.steps.map((s) => s.title)).toEqual([
      "Start Safe",
      "Build",
      "Test",
      "Safety Check",
      "Push Branch",
    ]);
  });

  it("has exactly three extras with the spec labels in order", () => {
    expect(MISSION_CONTROL_BUILD.extras).toHaveLength(3);
    expect(MISSION_CONTROL_BUILD.extras.map((x) => x.label)).toEqual([
      "When ready for PR",
      "If checks fail",
      "Continue later",
    ]);
  });

  it("every step and extra references a prompt id that exists in PROMPT_LIBRARY", () => {
    const promptIds = new Set(PROMPT_LIBRARY.map((p) => p.id));
    for (const step of MISSION_CONTROL_BUILD.steps) {
      expect(promptIds.has(step.promptId)).toBe(true);
    }
    for (const extra of MISSION_CONTROL_BUILD.extras) {
      expect(promptIds.has(extra.step.promptId)).toBe(true);
    }
  });

  it("extras have no step number — they're rendered under sub-headings, not as steps 6/7/8", () => {
    for (const extra of MISSION_CONTROL_BUILD.extras) {
      expect(extra.step.number).toBeUndefined();
    }
  });
});

// ── Data contract — Import + Emergency folders ──────────────────────────────

describe("IMPORT_FOLDER", () => {
  it("has the right title, anchor id, and references the import prompt", () => {
    expect(IMPORT_FOLDER.id).toBe("import-existing-code");
    expect(IMPORT_FOLDER.title).toBe("Import Existing Code");
    expect(IMPORT_FOLDER.promptId).toBe("import-existing-code-into-mission-control");
  });
});

describe("EMERGENCY_FOLDER", () => {
  it("has the right title, anchor id, and references the emergency prompt", () => {
    expect(EMERGENCY_FOLDER.id).toBe("emergency-debug");
    expect(EMERGENCY_FOLDER.title).toBe("Emergency Debug");
    expect(EMERGENCY_FOLDER.promptId).toBe("emergency-debug-prompt");
  });
});

// ── Data contract — Safety Rules ────────────────────────────────────────────

describe("SAFETY_RULES", () => {
  it("uses structured blocks, never a monospace dump", () => {
    for (const block of SAFETY_RULES.blocks) {
      expect(["heading", "paragraph", "numbered", "bullets"]).toContain(block.type);
    }
  });

  it("includes the four required headings and the dry-run defaults", () => {
    const headings = SAFETY_RULES.blocks
      .filter((b) => b.type === "heading")
      .map((b) => (b as { text: string }).text);
    expect(headings).toContain("Normal building is allowed");
    expect(headings).toContain("Keep out of GitHub");
    expect(headings).toContain("Owner-only or review required");
    expect(headings).toContain("Dry-run rule");

    const allBullets = SAFETY_RULES.blocks
      .filter((b) => b.type === "bullets")
      .flatMap((b) => (b as { items: string[] }).items);
    expect(allBullets).toContain("DRY_RUN=true");
    expect(allBullets).toContain("ALLOW_LIVE_EXTERNAL_ACTIONS=false");
  });
});

// ── Data contract — Prompt Library (10 prompts) ─────────────────────────────

describe("PROMPT_LIBRARY", () => {
  it("contains the ten prompts in the exact spec order", () => {
    expect(PROMPT_LIBRARY.map((p) => p.id)).toEqual([
      "start-mission-control-build",
      "build-inside-mission-control",
      "test-mission-control-build",
      "run-pre-push-safety-check",
      "push-branch-safely",
      "open-pull-request-summary",
      "fix-failed-github-checks",
      "continue-existing-mission-control-build",
      "import-existing-code-into-mission-control",
      "emergency-debug-prompt",
    ]);
  });

  it("matches the spec titles in order", () => {
    expect(PROMPT_LIBRARY.map((p) => p.title)).toEqual([
      "Start Mission Control Build",
      "Build Inside Mission Control",
      "Test Mission Control Build",
      "Run Pre-Push Safety Check",
      "Push Branch Safely",
      "Open Pull Request Summary",
      "Fix Failed GitHub Checks",
      "Continue Existing Mission Control Build",
      "Import Existing Code Into Mission Control",
      "Emergency Debug Prompt",
    ]);
  });

  it("prompts 1–5 (Mission Control Build main steps) carry step numbers; 6–10 do not", () => {
    expect(PROMPT_LIBRARY.slice(0, 5).map((p) => p.step)).toEqual([1, 2, 3, 4, 5]);
    for (const prompt of PROMPT_LIBRARY.slice(5)) {
      expect(prompt.step).toBeUndefined();
    }
  });

  it("Start Mission Control Build is prompt #1 and carries the full master pre-build body", () => {
    const master = PROMPT_LIBRARY[0];
    expect(master.id).toBe("start-mission-control-build");
    expect(master.title).toBe("Start Mission Control Build");
    for (let n = 1; n <= 9; n += 1) {
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

  it("Import Existing Code prompt carries the eleven-step body and the runtime-keys-allowed-but-not-committed safety model", () => {
    const importPrompt = PROMPT_LIBRARY.find(
      (p) => p.id === "import-existing-code-into-mission-control",
    );
    expect(importPrompt).toBeDefined();
    expect(importPrompt!.title).toBe("Import Existing Code Into Mission Control");
    for (let n = 1; n <= 11; n += 1) {
      expect(importPrompt!.body).toContain(`Step ${n}:`);
    }
    expect(importPrompt!.body).toContain("incoming/coo-import/");
    expect(importPrompt!.body).toContain("coo/import-existing-code");
    // The safety-model lines from the spec must survive in the body.
    expect(importPrompt!.body).toContain(
      "Real API keys may be used at runtime, but must never be committed.",
    );
    expect(importPrompt!.body).toContain(
      "Real client data may be used internally, but raw dumps must not be committed.",
    );
    expect(importPrompt!.body).toContain(
      "Live external actions require explicit dry-run and live-mode gates.",
    );
  });

  it("Emergency Debug prompt exists and contains the smallest-safe-fix language", () => {
    const emergency = PROMPT_LIBRARY.find((p) => p.id === "emergency-debug-prompt");
    expect(emergency).toBeDefined();
    expect(emergency!.title).toBe("Emergency Debug Prompt");
    expect(emergency!.body).toContain("Make the smallest safe fix.");
    expect(emergency!.body).toContain("Do not rebuild from scratch.");
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

// ── Renderer — SopBlocks ────────────────────────────────────────────────────

describe("SopBlocks renderer", () => {
  it("renders each block type with the right HTML tag and never a <pre>", () => {
    const { container } = render(
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
    expect(screen.getByText("one").parentElement?.tagName).toBe("OL");
    expect(screen.getByText("alpha").parentElement?.tagName).toBe("UL");
    expect(container.querySelector("pre")).toBeNull();
  });
});

// ── Renderer — GalleryCard ──────────────────────────────────────────────────

describe("GalleryCard", () => {
  it("renders title + description, links to the anchor, and has no Copy button", () => {
    render(<GalleryCard card={SOP_GALLERY[0]} />);
    const link = screen.getByTestId("gallery-card-mission-control-build");
    expect(link.tagName).toBe("A");
    expect(link.getAttribute("href")).toBe("#mission-control-build");
    expect(screen.getByText("Mission Control Build")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^copy/i })).toBeNull();
  });
});

// ── Renderer — BuildStepCard ────────────────────────────────────────────────

describe("BuildStepCard", () => {
  it("renders the step number badge, title, purpose, prompt title, preview, and Copy button for a numbered step", () => {
    const step = MISSION_CONTROL_BUILD.steps[0]; // Start Safe
    const prompt = PROMPT_LIBRARY.find((p) => p.id === step.promptId)!;
    render(<BuildStepCard step={step} prompt={prompt} />);

    expect(screen.getByText(`Step ${step.number}: ${step.title}`)).toBeInTheDocument();
    expect(screen.getByText(step.purpose)).toBeInTheDocument();
    expect(screen.getByText(prompt.title)).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: new RegExp(`copy ${prompt.title}`, "i"),
      }),
    ).toBeInTheDocument();
    // Preview is rendered; full body line should not appear inline.
    const preview = screen.getByTestId(`build-step-preview-${prompt.id}`);
    expect(preview.textContent).toContain(prompt.preview.split("\n")[0]);
    const deepBodyLine = prompt.body
      .split("\n")
      .find((l) => l.startsWith("Step 9:"));
    if (deepBodyLine) {
      expect(screen.queryByText(deepBodyLine)).toBeNull();
    }
  });

  it("renders no step number badge for an extra (no number on the step)", () => {
    const extra = MISSION_CONTROL_BUILD.extras[0]; // When ready for PR
    const prompt = PROMPT_LIBRARY.find((p) => p.id === extra.step.promptId)!;
    render(<BuildStepCard step={extra.step} prompt={prompt} />);
    expect(screen.queryByText(/^Step \d:/)).toBeNull();
    // Title is rendered as-is.
    expect(screen.getByText(extra.step.title)).toBeInTheDocument();
  });
});

// ── Renderer — ExtraStepGroup ───────────────────────────────────────────────

describe("ExtraStepGroup", () => {
  it("renders the label header and the embedded BuildStepCard", () => {
    const extra = MISSION_CONTROL_BUILD.extras[1]; // If checks fail
    const prompt = PROMPT_LIBRARY.find((p) => p.id === extra.step.promptId)!;
    render(<ExtraStepGroup label={extra.label} step={extra.step} prompt={prompt} />);
    expect(screen.getByText("If checks fail")).toBeInTheDocument();
    expect(screen.getByText(extra.step.title)).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: new RegExp(`copy ${prompt.title}`, "i"),
      }),
    ).toBeInTheDocument();
  });
});

// ── Renderer — IntroFolderBlock (Import + Emergency) ────────────────────────

describe("IntroFolderBlock", () => {
  it("renders Import folder title, description, intro, prompt title, and Copy button", () => {
    const prompt = PROMPT_LIBRARY.find((p) => p.id === IMPORT_FOLDER.promptId)!;
    render(<IntroFolderBlock folder={IMPORT_FOLDER} prompt={prompt} />);
    expect(screen.getByText("Import Existing Code")).toBeInTheDocument();
    expect(screen.getByText(IMPORT_FOLDER.intro)).toBeInTheDocument();
    expect(screen.getByText(prompt.title)).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: new RegExp(`copy ${prompt.title}`, "i"),
      }),
    ).toBeInTheDocument();
  });

  it("renders Emergency folder with its Copy button too", () => {
    const prompt = PROMPT_LIBRARY.find((p) => p.id === EMERGENCY_FOLDER.promptId)!;
    render(<IntroFolderBlock folder={EMERGENCY_FOLDER} prompt={prompt} />);
    expect(screen.getByText("Emergency Debug")).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: new RegExp(`copy ${prompt.title}`, "i"),
      }),
    ).toBeInTheDocument();
  });
});

// ── Renderer — SafetyRulesBlock ─────────────────────────────────────────────

describe("SafetyRulesBlock", () => {
  it("renders structured prose with no Copy button", () => {
    render(
      <SafetyRulesBlock
        title={SAFETY_RULES.title}
        description={SAFETY_RULES.description}
        blocks={SAFETY_RULES.blocks}
      />,
    );
    expect(screen.getByText("Safety Rules")).toBeInTheDocument();
    expect(screen.getByText("Normal building is allowed")).toBeInTheDocument();
    expect(screen.getByText("DRY_RUN=true")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^copy/i })).toBeNull();
  });
});

// ── Cross-cut — every prompt has exactly one Copy button when rendered ──────

describe("Copy button posture across the page", () => {
  it("every BuildStepCard renders exactly one Copy button labeled for its prompt title", () => {
    for (const step of MISSION_CONTROL_BUILD.steps) {
      const prompt = PROMPT_LIBRARY.find((p) => p.id === step.promptId)!;
      const { unmount } = render(<BuildStepCard step={step} prompt={prompt} />);
      const buttons = screen.getAllByRole("button", {
        name: new RegExp(`copy ${prompt.title}`, "i"),
      });
      expect(buttons).toHaveLength(1);
      unmount();
    }
  });

  it("every Mission Control Build extra renders exactly one Copy button", () => {
    for (const extra of MISSION_CONTROL_BUILD.extras) {
      const prompt = PROMPT_LIBRARY.find((p) => p.id === extra.step.promptId)!;
      const { unmount } = render(
        <ExtraStepGroup label={extra.label} step={extra.step} prompt={prompt} />,
      );
      expect(
        screen.getAllByRole("button", {
          name: new RegExp(`copy ${prompt.title}`, "i"),
        }),
      ).toHaveLength(1);
      unmount();
    }
  });
});

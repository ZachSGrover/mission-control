import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { MCRole } from "@/lib/roles";

// ── Mocks ────────────────────────────────────────────────────────────────────
//
// usePathname is reset per test via the pathnameMock hoisted ref. The default
// is "/" so tests that don't care don't need to set it.

const pathnameMock = vi.hoisted(() => ({ current: "/" as string }));

vi.mock("next/navigation", () => ({
  usePathname: () => pathnameMock.current,
}));

vi.mock("@/api/generated/default/default", () => ({
  useHealthzHealthzGet: () => ({
    data: { data: { ok: true } },
    isError: false,
    refetch: () => {},
  }),
}));

vi.mock("@/api/mutator", () => ({
  ApiError: class extends Error {},
}));

vi.mock("@/hooks/use-git-save", () => ({
  useGitSave: () => ({
    status: "idle",
    message: "",
    filesChanged: 0,
    commitHash: "",
    error: "",
    save: async () => {},
    reset: () => {},
  }),
}));

const roleMock = vi.hoisted(() => ({ current: "viewer" as MCRole | null }));

vi.mock("@/hooks/use-role", () => ({
  useRole: () => ({
    role: roleMock.current,
    realRole: roleMock.current,
    previewing: false,
    disabled: false,
    loading: false,
    error: null,
  }),
}));

import { DashboardSidebar } from "./DashboardSidebar";

afterEach(() => {
  roleMock.current = "viewer";
  pathnameMock.current = "/";
});

// ── Sidebar structure ────────────────────────────────────────────────────────

describe("DashboardSidebar — visible sections", () => {
  it("renders the five top-level section headings to every role", () => {
    // "Chat" and "Memory" appear twice in the DOM — once as a section heading
    // and once as a NavLink label inside that section. getAllByText covers
    // both occurrences; for the unambiguous sections we still use getByText.
    for (const role of ["owner", "operator", "builder", "viewer"] as MCRole[]) {
      roleMock.current = role;
      const { unmount } = render(<DashboardSidebar />);
      expect(screen.getAllByText("Chat").length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText("Memory").length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText("Workspace")).toBeInTheDocument();
      expect(screen.getByText("Modern Sales Agency")).toBeInTheDocument();
      expect(screen.getByText("System")).toBeInTheDocument();
      unmount();
    }
  });

  it("renders SOPs in the Memory section for every role", () => {
    for (const role of ["owner", "operator", "builder", "viewer"] as MCRole[]) {
      roleMock.current = role;
      const { unmount } = render(<DashboardSidebar />);
      expect(screen.getByTestId("nav-sops")).toBeInTheDocument();
      unmount();
    }
  });

  it("renames Skills to Tools and keeps the /skills route", () => {
    roleMock.current = "owner";
    render(<DashboardSidebar />);
    const tools = screen.getByTestId("nav-tools");
    expect(tools).toBeInTheDocument();
    expect(tools).toHaveAttribute("href", "/skills");
    expect(screen.queryByText("Skills")).not.toBeInTheDocument();
  });

  it("renames the Business / Intelligence section to Modern Sales Agency", () => {
    roleMock.current = "owner";
    render(<DashboardSidebar />);
    expect(screen.queryByText("Business / Intelligence")).not.toBeInTheDocument();
    expect(screen.getByText("Modern Sales Agency")).toBeInTheDocument();
  });
});

// ── Hidden items ─────────────────────────────────────────────────────────────

describe("DashboardSidebar — hidden items", () => {
  it("hides Hermes, Boards, Control, Bot Builder, Build Requests, Guide, Security from the sidebar for owner", () => {
    roleMock.current = "owner";
    render(<DashboardSidebar />);
    expect(screen.queryByText("Hermes")).not.toBeInTheDocument();
    expect(screen.queryByText("Boards")).not.toBeInTheDocument();
    expect(screen.queryByText("Control")).not.toBeInTheDocument();
    expect(screen.queryByTestId("nav-bot-builder")).not.toBeInTheDocument();
    expect(screen.queryByText("Bot Builder")).not.toBeInTheDocument();
    expect(screen.queryByTestId("nav-build-requests")).not.toBeInTheDocument();
    expect(screen.queryByText("Build Requests")).not.toBeInTheDocument();
    expect(screen.queryByText("Guide")).not.toBeInTheDocument();
    expect(screen.queryByTestId("nav-security")).not.toBeInTheDocument();
    expect(screen.queryByText("Security")).not.toBeInTheDocument();
  });

  it("hides those same items from every other role too", () => {
    for (const role of ["operator", "builder", "viewer"] as MCRole[]) {
      roleMock.current = role;
      const { unmount } = render(<DashboardSidebar />);
      expect(screen.queryByText("Hermes")).not.toBeInTheDocument();
      expect(screen.queryByText("Boards")).not.toBeInTheDocument();
      expect(screen.queryByText("Control")).not.toBeInTheDocument();
      expect(screen.queryByTestId("nav-bot-builder")).not.toBeInTheDocument();
      expect(screen.queryByTestId("nav-build-requests")).not.toBeInTheDocument();
      expect(screen.queryByText("Guide")).not.toBeInTheDocument();
      expect(screen.queryByTestId("nav-security")).not.toBeInTheDocument();
      unmount();
    }
  });
});

// ── Role visibility ──────────────────────────────────────────────────────────

describe("DashboardSidebar — role-gated items", () => {
  it("shows Bots to owner + operator, hides from builder + viewer", () => {
    roleMock.current = "owner";
    const ownerRender = render(<DashboardSidebar />);
    expect(screen.getByTestId("nav-bots")).toBeInTheDocument();
    ownerRender.unmount();

    roleMock.current = "operator";
    const operatorRender = render(<DashboardSidebar />);
    expect(screen.getByTestId("nav-bots")).toBeInTheDocument();
    operatorRender.unmount();

    for (const role of ["builder", "viewer"] as MCRole[]) {
      roleMock.current = role;
      const { unmount } = render(<DashboardSidebar />);
      expect(screen.queryByTestId("nav-bots")).not.toBeInTheDocument();
      unmount();
    }
  });

  it("shows Users / Integrations / Save only to owner", () => {
    roleMock.current = "owner";
    const ownerRender = render(<DashboardSidebar />);
    expect(screen.getByTestId("nav-users")).toBeInTheDocument();
    expect(screen.getByTestId("nav-integrations")).toBeInTheDocument();
    expect(screen.getByTestId("nav-save")).toBeInTheDocument();
    ownerRender.unmount();

    for (const role of ["operator", "builder", "viewer"] as MCRole[]) {
      roleMock.current = role;
      const { unmount } = render(<DashboardSidebar />);
      expect(screen.queryByTestId("nav-users")).not.toBeInTheDocument();
      expect(screen.queryByTestId("nav-integrations")).not.toBeInTheDocument();
      expect(screen.queryByTestId("nav-save")).not.toBeInTheDocument();
      unmount();
    }
  });

  it("places Usage Tracker inside System for every role", () => {
    for (const role of ["owner", "operator", "builder", "viewer"] as MCRole[]) {
      roleMock.current = role;
      const { unmount } = render(<DashboardSidebar />);
      expect(screen.getByTestId("nav-usage")).toBeInTheDocument();
      unmount();
    }
  });
});

// ── Bots active matching ─────────────────────────────────────────────────────
//
// Verifies the spec requirement:
//   - Bots highlights for /bots
//   - Bots also highlights for /bots/builder
//   - No duplicate Bot Builder sidebar entry exists.

describe("DashboardSidebar — Bots active matching", () => {
  it("highlights Bots on /bots", () => {
    roleMock.current = "operator";
    pathnameMock.current = "/bots";
    render(<DashboardSidebar />);
    const bots = screen.getByTestId("nav-bots");
    // Active state uses font-medium; inactive uses font-normal.
    expect(bots.className).toContain("font-medium");
  });

  it("highlights Bots on /bots/builder too (section match)", () => {
    roleMock.current = "operator";
    pathnameMock.current = "/bots/builder";
    render(<DashboardSidebar />);
    const bots = screen.getByTestId("nav-bots");
    expect(bots.className).toContain("font-medium");
    // And there is no separate Bot Builder entry to also light up.
    expect(screen.queryByTestId("nav-bot-builder")).not.toBeInTheDocument();
  });

  it("does NOT highlight Bots on unrelated paths like /bots-other", () => {
    // Defensive: section matching must use a slash boundary, not raw
    // startsWith, so a future sibling route would not falsely match.
    roleMock.current = "operator";
    pathnameMock.current = "/bots-other";
    render(<DashboardSidebar />);
    const bots = screen.getByTestId("nav-bots");
    expect(bots.className).toContain("font-normal");
  });
});

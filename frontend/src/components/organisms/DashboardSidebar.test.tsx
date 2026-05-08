import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { MCRole } from "@/lib/roles";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
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
});

describe("DashboardSidebar", () => {
  it("hides Bots, Bot Builder, Users, Integrations, and Security from viewer role", () => {
    roleMock.current = "viewer";
    render(<DashboardSidebar />);
    expect(screen.queryByTestId("nav-bots")).not.toBeInTheDocument();
    expect(screen.queryByTestId("nav-bot-builder")).not.toBeInTheDocument();
    expect(screen.queryByText("Users")).not.toBeInTheDocument();
    expect(screen.queryByText("Integrations")).not.toBeInTheDocument();
    expect(screen.queryByTestId("nav-security")).not.toBeInTheDocument();
  });

  it("shows Bots and Bot Builder to operator but still hides Users, Integrations, Security", () => {
    roleMock.current = "operator";
    render(<DashboardSidebar />);
    expect(screen.getByTestId("nav-bots")).toBeInTheDocument();
    expect(screen.getByTestId("nav-bot-builder")).toBeInTheDocument();
    expect(screen.queryByText("Users")).not.toBeInTheDocument();
    expect(screen.queryByText("Integrations")).not.toBeInTheDocument();
    expect(screen.queryByTestId("nav-security")).not.toBeInTheDocument();
  });

  it("shows Bots, Bot Builder, Users, Integrations, Security, and Usage Tracker to owner", () => {
    roleMock.current = "owner";
    render(<DashboardSidebar />);
    expect(screen.getByTestId("nav-bots")).toBeInTheDocument();
    expect(screen.getByTestId("nav-bot-builder")).toBeInTheDocument();
    expect(screen.getByText("Users")).toBeInTheDocument();
    expect(screen.getByText("Integrations")).toBeInTheDocument();
    expect(screen.getByTestId("nav-security")).toBeInTheDocument();
    expect(screen.getByTestId("nav-usage")).toBeInTheDocument();
  });

  it("hides Bots and Bot Builder from builder role", () => {
    roleMock.current = "builder";
    render(<DashboardSidebar />);
    expect(screen.queryByTestId("nav-bots")).not.toBeInTheDocument();
    expect(screen.queryByTestId("nav-bot-builder")).not.toBeInTheDocument();
    expect(screen.queryByTestId("nav-security")).not.toBeInTheDocument();
  });

  it("places Usage Tracker inside the System nav (visible to all roles)", () => {
    for (const role of ["owner", "operator", "builder", "viewer"] as MCRole[]) {
      roleMock.current = role;
      const { unmount } = render(<DashboardSidebar />);
      expect(screen.getByTestId("nav-usage")).toBeInTheDocument();
      unmount();
    }
  });
});

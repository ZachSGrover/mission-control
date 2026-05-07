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
  it("hides Bots, Users, Integrations, and Security from viewer role", () => {
    roleMock.current = "viewer";
    render(<DashboardSidebar />);
    expect(screen.queryByText("Bots")).not.toBeInTheDocument();
    expect(screen.queryByText("Users")).not.toBeInTheDocument();
    expect(screen.queryByText("Integrations")).not.toBeInTheDocument();
    expect(screen.queryByTestId("nav-security")).not.toBeInTheDocument();
  });

  it("shows Bots to operator but still hides Users, Integrations, Security", () => {
    roleMock.current = "operator";
    render(<DashboardSidebar />);
    expect(screen.getByText("Bots")).toBeInTheDocument();
    expect(screen.queryByText("Users")).not.toBeInTheDocument();
    expect(screen.queryByText("Integrations")).not.toBeInTheDocument();
    expect(screen.queryByTestId("nav-security")).not.toBeInTheDocument();
  });

  it("shows Bots, Users, Integrations, and Security to owner", () => {
    roleMock.current = "owner";
    render(<DashboardSidebar />);
    expect(screen.getByText("Bots")).toBeInTheDocument();
    expect(screen.getByText("Users")).toBeInTheDocument();
    expect(screen.getByText("Integrations")).toBeInTheDocument();
    expect(screen.getByTestId("nav-security")).toBeInTheDocument();
  });

  it("hides Bots from builder", () => {
    roleMock.current = "builder";
    render(<DashboardSidebar />);
    expect(screen.queryByText("Bots")).not.toBeInTheDocument();
    expect(screen.queryByTestId("nav-security")).not.toBeInTheDocument();
  });
});

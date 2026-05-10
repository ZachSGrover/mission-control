import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { MCRole } from "@/lib/roles";

const roleState = vi.hoisted(() => ({
  realRole: "owner" as MCRole | null,
}));

vi.mock("@/hooks/use-role", () => ({
  useRole: () => ({
    role: roleState.realRole,
    realRole: roleState.realRole,
    previewing: false,
    disabled: false,
    loading: false,
    error: null,
  }),
}));

import { RolePreviewControl } from "./RolePreviewControl";

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  roleState.realRole = "owner";
  localStorage.clear();
});

describe("RolePreviewControl", () => {
  it("renders nothing for non-owner roles", () => {
    for (const role of ["operator", "builder", "viewer", null] as Array<MCRole | null>) {
      roleState.realRole = role;
      const { container, unmount } = render(<RolePreviewControl />);
      expect(container.firstChild).toBeNull();
      unmount();
    }
  });

  it("renders the control for owner with all four role buttons", () => {
    roleState.realRole = "owner";
    render(<RolePreviewControl />);
    expect(screen.getByTestId("role-preview-control")).toBeInTheDocument();
    for (const role of ["owner", "operator", "builder", "viewer"]) {
      expect(screen.getByTestId(`role-preview-${role}`)).toBeInTheDocument();
    }
  });

  it("clicking a non-owner role writes to localStorage", () => {
    roleState.realRole = "owner";
    render(<RolePreviewControl />);
    fireEvent.click(screen.getByTestId("role-preview-operator"));
    expect(localStorage.getItem("mc:rolePreview")).toBe("operator");
  });

  it("clicking owner clears the preview", () => {
    roleState.realRole = "owner";
    localStorage.setItem("mc:rolePreview", "operator");
    render(<RolePreviewControl />);
    fireEvent.click(screen.getByTestId("role-preview-owner"));
    expect(localStorage.getItem("mc:rolePreview")).toBeNull();
  });
});

import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { MCRole } from "@/lib/roles";

const roleState = vi.hoisted(() => ({
  role: "owner" as MCRole | null,
  realRole: "owner" as MCRole | null,
  previewing: false,
  disabled: false,
  loading: false,
  error: null as string | null,
}));

vi.mock("@/hooks/use-role", () => ({
  useRole: () => roleState,
}));

const setRolePreviewMock = vi.fn();

vi.mock("@/lib/role-preview", () => ({
  setRolePreview: (value: MCRole | null) => setRolePreviewMock(value),
}));

import { RolePreviewBanner } from "./RolePreviewBanner";

afterEach(() => {
  roleState.role = "owner";
  roleState.realRole = "owner";
  roleState.previewing = false;
  setRolePreviewMock.mockReset();
});

describe("RolePreviewBanner", () => {
  it("renders nothing when previewing is false", () => {
    roleState.previewing = false;
    const { container } = render(<RolePreviewBanner />);
    expect(container.firstChild).toBeNull();
  });

  it("renders the previewing banner when previewing is true", () => {
    roleState.role = "operator";
    roleState.realRole = "owner";
    roleState.previewing = true;
    render(<RolePreviewBanner />);
    expect(screen.getByTestId("role-preview-banner")).toBeInTheDocument();
    expect(screen.getByText(/Previewing operator view/i)).toBeInTheDocument();
    expect(
      screen.getByText(/does not change your real permissions/i),
    ).toBeInTheDocument();
  });

  it("clears the preview when Exit preview is clicked", () => {
    roleState.role = "viewer";
    roleState.realRole = "owner";
    roleState.previewing = true;
    render(<RolePreviewBanner />);
    fireEvent.click(screen.getByTestId("role-preview-banner-clear"));
    expect(setRolePreviewMock).toHaveBeenCalledWith(null);
  });
});

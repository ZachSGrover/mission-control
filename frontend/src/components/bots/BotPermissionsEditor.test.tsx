import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { MCRole } from "@/lib/roles";

import { BotPermissionsEditor } from "./BotPermissionsEditor";

type Save = (slug: string, roles: MCRole[]) => Promise<MCRole[]>;

function renderEditor(overrides: Partial<{
  viewerRole: MCRole | null;
  permittedRoles: MCRole[];
  readOnlyExternal: boolean;
  onSave: Save;
}> = {}) {
  const defaultSave: Save = async (_slug, roles) => roles;
  const props = {
    slug: "master_control_loop",
    permittedRoles: ["owner"] as MCRole[],
    readOnlyExternal: false,
    viewerRole: "owner" as MCRole | null,
    onSave: defaultSave,
    ...overrides,
  };
  return render(<BotPermissionsEditor {...props} />);
}

describe("BotPermissionsEditor", () => {
  it("renders nothing for non-owner roles", () => {
    for (const role of ["operator", "builder", "viewer", null] as Array<MCRole | null>) {
      const { container, unmount } = renderEditor({ viewerRole: role });
      expect(container.firstChild).toBeNull();
      unmount();
    }
  });

  it("renders an informational, uneditable surface for read_only_external bots", () => {
    renderEditor({ readOnlyExternal: true });
    expect(screen.getByTestId("bot-permissions-blocked")).toBeInTheDocument();
    expect(screen.queryByTestId("bot-permissions-editor")).not.toBeInTheDocument();
    expect(screen.queryByTestId("bot-permissions-save")).not.toBeInTheDocument();
  });

  it("shows owner as checked and disabled — cannot be removed by toggling", () => {
    renderEditor({ permittedRoles: ["owner"] });
    const ownerCheckbox = screen.getByTestId("bot-permissions-owner") as HTMLInputElement;
    expect(ownerCheckbox.checked).toBe(true);
    expect(ownerCheckbox.disabled).toBe(true);

    fireEvent.click(ownerCheckbox);
    expect(ownerCheckbox.checked).toBe(true);
  });

  it("submits a permitted_roles list that always contains owner", async () => {
    const calls: Array<{ slug: string; roles: MCRole[] }> = [];
    const onSave: Save = async (slug, roles) => {
      calls.push({ slug, roles });
      return roles;
    };

    renderEditor({ permittedRoles: ["owner"], onSave });
    const operator = screen.getByTestId("bot-permissions-operator") as HTMLInputElement;
    fireEvent.click(operator);
    expect(operator.checked).toBe(true);

    fireEvent.click(screen.getByTestId("bot-permissions-save"));
    await new Promise((r) => setTimeout(r, 0));

    expect(calls.length).toBe(1);
    expect(calls[0].slug).toBe("master_control_loop");
    const submitted = new Set(calls[0].roles);
    expect(submitted.has("owner")).toBe(true);
    expect(submitted.has("operator")).toBe(true);
  });

  it("re-injects owner on save even if local state somehow drops it", async () => {
    let receivedRoles: MCRole[] = [];
    const onSave: Save = async (_slug, roles) => {
      receivedRoles = roles;
      return roles;
    };

    renderEditor({ permittedRoles: ["operator"], onSave });
    fireEvent.click(screen.getByTestId("bot-permissions-save"));
    await new Promise((r) => setTimeout(r, 0));

    expect(new Set(receivedRoles).has("owner")).toBe(true);
  });

  it("never renders any field that could be a secret or token", () => {
    const { container } = renderEditor({
      permittedRoles: ["owner", "operator"],
    });
    const html = container.innerHTML.toLowerCase();
    for (const forbidden of [
      "token",
      "secret",
      "webhook",
      "api_key",
      "api-key",
      "password",
      "credential",
    ]) {
      expect(html.includes(forbidden)).toBe(false);
    }
  });

  it("displays the on-screen save error when onSave rejects", async () => {
    const onSave: Save = async () => {
      throw new Error("HTTP 403");
    };
    renderEditor({ onSave });
    fireEvent.click(screen.getByTestId("bot-permissions-save"));
    await new Promise((r) => setTimeout(r, 0));
    expect(await screen.findByText(/HTTP 403/i)).toBeInTheDocument();
  });
});

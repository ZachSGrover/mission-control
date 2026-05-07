import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AddAllowlistPanel } from "./AddAllowlistPanel";

type FetchFn = (url: string, init?: RequestInit) => Promise<Response>;

function makeFetch(): { calls: Array<{ url: string; init?: RequestInit }>; fn: FetchFn } {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fn: FetchFn = async (url, init) => {
    calls.push({ url: String(url), init });
    return new Response(
      JSON.stringify({
        clerk_user_id: null,
        email: "coo@test.local",
        name: null,
        role: "operator",
        added_by_clerk_user_id: null,
        created_at: new Date().toISOString(),
        pending: true,
      }),
      { status: 201, headers: { "Content-Type": "application/json" } },
    );
  };
  return { calls, fn };
}

describe("AddAllowlistPanel — invite role dropdown", () => {
  it("includes Operator in the role dropdown", () => {
    const { fn } = makeFetch();
    render(<AddAllowlistPanel fetchFn={fn} onAdded={() => {}} />);
    const select = screen.getByTestId("invite-role-select") as HTMLSelectElement;
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toContain("operator");
  });

  it("orders roles owner, operator, builder, viewer", () => {
    const { fn } = makeFetch();
    render(<AddAllowlistPanel fetchFn={fn} onAdded={() => {}} />);
    const select = screen.getByTestId("invite-role-select") as HTMLSelectElement;
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toEqual(["owner", "operator", "builder", "viewer"]);
  });

  it("submits role=operator to /api/v1/allowed-users when Operator is chosen", async () => {
    const { calls, fn } = makeFetch();
    render(<AddAllowlistPanel fetchFn={fn} onAdded={() => {}} />);

    const emailInput = screen.getByPlaceholderText("name@example.com") as HTMLInputElement;
    fireEvent.change(emailInput, { target: { value: "coo@test.local" } });

    const select = screen.getByTestId("invite-role-select") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "operator" } });

    fireEvent.click(screen.getByText("Invite"));
    await new Promise((r) => setTimeout(r, 0));

    expect(calls.length).toBe(1);
    expect(calls[0].url).toContain("/api/v1/allowed-users");
    const body = JSON.parse(String(calls[0].init?.body ?? "{}"));
    expect(body.role).toBe("operator");
    expect(body.email).toBe("coo@test.local");
  });
});

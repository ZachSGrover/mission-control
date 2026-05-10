import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getRolePreview,
  setRolePreview,
  subscribeRolePreview,
} from "./role-preview";

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
});

describe("role-preview lib", () => {
  it("returns null when nothing is stored", () => {
    expect(getRolePreview()).toBeNull();
  });

  it("round-trips a valid role", () => {
    setRolePreview("operator");
    expect(getRolePreview()).toBe("operator");
  });

  it("clears the preview when set to null", () => {
    setRolePreview("operator");
    setRolePreview(null);
    expect(getRolePreview()).toBeNull();
  });

  it("ignores invalid role values written directly to localStorage", () => {
    localStorage.setItem("mc:rolePreview", "founder");
    expect(getRolePreview()).toBeNull();
  });

  it("notifies subscribers on change", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeRolePreview(listener);
    setRolePreview("operator");
    expect(listener).toHaveBeenCalledTimes(1);
    setRolePreview(null);
    expect(listener).toHaveBeenCalledTimes(2);
    unsubscribe();
    setRolePreview("builder");
    expect(listener).toHaveBeenCalledTimes(2);
  });
});

/**
 * Frontend-only role preview.
 *
 * Lets the owner choose a role to *preview* in their browser session.
 * The preview only affects what the UI renders — every backend call
 * still resolves the caller's real role server-side, so no privileged
 * action can leak through preview mode.
 *
 * Storage:
 *   localStorage key ``mc:rolePreview``.  Cleared by setting to ``""``.
 *
 * Synchronization across components:
 *   ``window`` dispatches a ``mc:role-preview-changed`` CustomEvent on
 *   write so hooks can re-render without listening to the underlying
 *   ``storage`` event (which fires only across tabs, not same-tab).
 */

import type { MCRole } from "@/lib/roles";

const STORAGE_KEY = "mc:rolePreview";
const EVENT_NAME = "mc:role-preview-changed";

const VALID: ReadonlySet<MCRole> = new Set<MCRole>([
  "owner",
  "operator",
  "builder",
  "viewer",
]);

function isBrowser(): boolean {
  return typeof window !== "undefined" && typeof localStorage !== "undefined";
}

export function getRolePreview(): MCRole | null {
  if (!isBrowser()) return null;
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  return VALID.has(raw as MCRole) ? (raw as MCRole) : null;
}

export function setRolePreview(role: MCRole | null): void {
  if (!isBrowser()) return;
  if (role === null) {
    localStorage.removeItem(STORAGE_KEY);
  } else if (VALID.has(role)) {
    localStorage.setItem(STORAGE_KEY, role);
  } else {
    return;
  }
  window.dispatchEvent(new CustomEvent(EVENT_NAME));
}

export function subscribeRolePreview(listener: () => void): () => void {
  if (!isBrowser()) return () => {};
  const handler = (): void => listener();
  window.addEventListener(EVENT_NAME, handler);
  // Cross-tab sync via the native ``storage`` event.
  const storageHandler = (e: StorageEvent): void => {
    if (e.key === STORAGE_KEY) listener();
  };
  window.addEventListener("storage", storageHandler);
  return () => {
    window.removeEventListener(EVENT_NAME, handler);
    window.removeEventListener("storage", storageHandler);
  };
}

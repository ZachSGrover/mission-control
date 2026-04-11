/**
 * Mission Control role definitions and permission constants.
 *
 * Roles (in descending privilege order):
 *   owner   — full access, credential management, user management
 *   builder — AI, Projects, Memory, Automation; NO credentials or user mgmt
 *   viewer  — read-only access to everything a builder can see
 */

export type MCRole = "owner" | "builder" | "viewer";

/** Features each role can access. */
export const ROLE_CAN = {
  /** Manage API keys and GitHub credentials in Settings. */
  manageCredentials: (role: MCRole) => role === "owner",
  /** Manage other users (invite, change role, disable). */
  manageUsers: (role: MCRole) => role === "owner",
  /** Use AI chat, operator, code features. */
  useAI: (role: MCRole) => role === "owner" || role === "builder",
  /** Run automations and create agents. */
  useAutomation: (role: MCRole) => role === "owner" || role === "builder",
  /** Read boards, tasks, memory (no mutations). */
  readContent: (_role: MCRole) => true,
} as const;

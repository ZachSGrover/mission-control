/**
 * Mission Control role definitions and permission constants.
 *
 * Roles (in descending privilege order):
 *   owner    — full access, credential management, user management
 *   operator — operate bots; cannot manage credentials or users
 *   builder  — AI, Projects, Memory, Automation; NO credentials or user mgmt
 *   viewer   — read-only access to everything a builder can see
 */

export type MCRole = "owner" | "operator" | "builder" | "viewer";

/** Privilege ordering — higher number = more privileged. */
export const ROLE_RANK: Record<MCRole, number> = {
  owner: 4,
  operator: 3,
  builder: 2,
  viewer: 1,
};

export function hasMinRole(role: MCRole, required: MCRole): boolean {
  return ROLE_RANK[role] >= ROLE_RANK[required];
}

/** Features each role can access. */
export const ROLE_CAN = {
  /** Manage API keys and GitHub credentials in Settings. */
  manageCredentials: (role: MCRole) => role === "owner",
  /** Manage other users (invite, change role, disable). */
  manageUsers: (role: MCRole) => role === "owner",
  /** View masked previews of which integrations are configured. */
  viewIntegrationStatus: (role: MCRole) => role === "owner",
  /** Use AI chat, operator, code features. */
  useAI: (role: MCRole) => role === "owner" || role === "builder",
  /** Run automations and create agents. */
  useAutomation: (role: MCRole) => role === "owner" || role === "builder",
  /** See the Bots dashboard sidebar entry / page. */
  viewBots: (role: MCRole) => role === "owner" || role === "operator",
  /** Start/stop a bot via the Bots dashboard.  Per-bot ``permitted_roles``
      is still enforced server-side; this only hides controls in the UI. */
  operateBots: (role: MCRole) => role === "owner" || role === "operator",
  /** Read boards, tasks, memory (no mutations). */
  readContent: (_role: MCRole) => true,
} as const;

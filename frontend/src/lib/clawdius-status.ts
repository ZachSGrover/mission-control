// Clawdius (chat) gateway status — derives a user-facing view-state from the
// raw OpenClaw WebSocket ConnectionStatus plus whether the gateway URL and
// token are configured for the current runtime.
//
// The raw status alone cannot distinguish "no URL for this host" from "URL
// configured but token missing" from "URL + token configured but WS handshake
// failed", which all collapse to "Offline" in the previous UI. Splitting them
// here lets the chat header tell the operator *why* chat is not reachable and
// what to do about it.
//
// This module is pure (no side effects, no React, no DOM) so the singleton
// helpers and the test suite can call it directly.

import type { ConnectionStatus } from "@/lib/openclaw-client";

export type ClawdiusViewKind =
  | "connected"
  | "connecting"
  | "no_gateway"
  | "no_token"
  | "unreachable"
  | "idle";

export type ClawdiusTone = "ok" | "pending" | "warn" | "error" | "muted";

export interface ClawdiusViewState {
  kind: ClawdiusViewKind;
  /** Short label suitable for the dot. */
  label: string;
  /** Longer one-line hint suitable for a tooltip / help row. */
  hint: string;
  /** Color tone the dot/text should render with. */
  tone: ClawdiusTone;
  /** Whether the operator can usefully press Reconnect now. */
  canReconnect: boolean;
  /** Whether to point the operator at /settings to fix this state. */
  needsSettings: boolean;
  /** Whether the chat input should be enabled. */
  canSend: boolean;
}

export interface ClawdiusInputs {
  status: ConnectionStatus;
  gatewayConfigured: boolean;
  tokenConfigured: boolean;
}

/**
 * Pure mapping from (raw WS status, config flags) → human view-state.
 *
 * Precedence (highest first):
 *   1. no_gateway  — no WS URL is configured for this host
 *   2. no_token    — URL configured but operator token missing
 *   3. raw status mapping (connected / connecting / unreachable / idle)
 */
export function deriveClawdiusViewState(
  inputs: ClawdiusInputs,
): ClawdiusViewState {
  const { status, gatewayConfigured, tokenConfigured } = inputs;

  if (!gatewayConfigured) {
    return {
      kind: "no_gateway",
      label: "Gateway not configured",
      hint: "No OpenClaw gateway URL is configured for this host.",
      tone: "muted",
      canReconnect: false,
      needsSettings: false,
      canSend: false,
    };
  }

  if (!tokenConfigured) {
    return {
      kind: "no_token",
      label: "Gateway token missing",
      hint: "Open Settings → Gateway to paste your OpenClaw operator token.",
      tone: "warn",
      canReconnect: false,
      needsSettings: true,
      canSend: false,
    };
  }

  switch (status) {
    case "connected":
      return {
        kind: "connected",
        label: "Online",
        hint: "Connected to the OpenClaw gateway.",
        tone: "ok",
        canReconnect: false,
        needsSettings: false,
        canSend: true,
      };
    case "connecting":
      return {
        kind: "connecting",
        label: "Connecting…",
        hint: "Establishing the WebSocket handshake.",
        tone: "pending",
        canReconnect: false,
        needsSettings: false,
        canSend: false,
      };
    case "disconnected":
    case "error":
      return {
        kind: "unreachable",
        label: "Gateway unreachable",
        hint: "Cloudflare Access or the operator token may be expired. Click Reconnect, or re-auth at the gateway URL.",
        tone: "error",
        canReconnect: true,
        needsSettings: false,
        canSend: false,
      };
    case "idle":
    default:
      return {
        kind: "idle",
        label: "Ready",
        hint: "Waiting to connect.",
        tone: "muted",
        canReconnect: true,
        needsSettings: false,
        canSend: false,
      };
  }
}

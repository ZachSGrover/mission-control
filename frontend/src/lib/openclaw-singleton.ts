// Module-level singleton OpenClaw WebSocket client.
// Lives outside React component lifecycle so the connection and in-flight
// requests survive tab switches without disconnecting.

import {
  OpenClawClient,
  extractText,
  type ChatEvent,
  type ConnectionStatus,
} from "@/lib/openclaw-client";
import { requestManager } from "@/lib/request-manager";

const ENV_WS_URL =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_OPENCLAW_WS_URL) ||
  "";
const TOKEN =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_OPENCLAW_TOKEN) ||
  "";

// Resolve the WS URL at client-create time (not module load), so SSR and
// deployed browsers behave correctly:
//   - Explicit NEXT_PUBLIC_OPENCLAW_WS_URL always wins (local or production).
//   - No env var + browser on localhost → default to ws://localhost:18789 (dev).
//   - No env var + browser on hq.digidle.com → wss://claw.digidle.com (the
//     Cloudflare-tunneled gateway exposing the operator's local OpenClaw).
//   - No env var + any other deployed host → null, stay "disconnected".
//   - SSR / non-browser → null (never auto-connect during render).
const PRODUCTION_HOST_GATEWAYS: Record<string, string> = {
  "hq.digidle.com": "wss://claw.digidle.com",
};

function _resolveWsUrl(): string | null {
  if (ENV_WS_URL) return ENV_WS_URL;
  if (typeof window === "undefined") return null;
  const host = window.location.hostname;
  if (host === "localhost" || host === "127.0.0.1" || host === "0.0.0.0") {
    return "ws://localhost:18789";
  }
  if (host in PRODUCTION_HOST_GATEWAYS) {
    return PRODUCTION_HOST_GATEWAYS[host];
  }
  return null;
}

export const GATEWAY_OFFLINE_MESSAGE =
  "OpenClaw gateway is offline. This deployed build has no NEXT_PUBLIC_OPENCLAW_WS_URL configured, so it will not attempt to reach ws://localhost:18789 from your browser. Configure a secure gateway endpoint (e.g. wss://gateway.example.com) in the hosting provider's env vars, or run Mission Control locally.";

// runId → provider, populated on the first delta of each response
const _runIdToProvider = new Map<string, string>();

// The next sendMessage call will register its runId to this provider
let _pendingProvider: string | null = null;

type StatusListener = (status: ConnectionStatus) => void;
const _statusListeners = new Set<StatusListener>();
let _currentStatus: ConnectionStatus = "idle";

function _notifyStatus(status: ConnectionStatus) {
  _currentStatus = status;
  for (const fn of _statusListeners) fn(status);
}

function _handleEvent(event: ChatEvent) {
  const { runId, state, message, errorMessage } = event;

  // First delta: bind runId → provider
  if (!_runIdToProvider.has(runId) && _pendingProvider) {
    const provider = _pendingProvider;
    _pendingProvider = null;
    _runIdToProvider.set(runId, provider);
    requestManager.start(provider, runId);
  }

  const provider = _runIdToProvider.get(runId);
  if (!provider) return;

  if (state === "delta") {
    const chunk = extractText(message);
    if (chunk) requestManager.appendDelta(provider, chunk);
  }

  if (state === "final") {
    const finalText = extractText(message);
    if (finalText) requestManager.setFinalText(provider, finalText);
    requestManager.complete(provider);
    _runIdToProvider.delete(runId);
  }

  if (state === "aborted" || state === "error") {
    requestManager.fail(provider, errorMessage ?? state);
    _runIdToProvider.delete(runId);
  }
}

let _client: OpenClawClient | null = null;
let _offlineReported = false;

function _getClient(): OpenClawClient | null {
  if (_client) return _client;
  const url = _resolveWsUrl();
  if (!url) {
    if (!_offlineReported) {
      _offlineReported = true;
      _notifyStatus("disconnected");
    }
    return null;
  }
  _client = new OpenClawClient({
    url,
    token: TOKEN,
    onChatEvent: _handleEvent,
    onStatusChange: _notifyStatus,
  });
  _client.connect();
  return _client;
}

/** Returns true if a gateway URL is configured for the current runtime. */
export function isGatewayConfigured(): boolean {
  return _resolveWsUrl() !== null;
}

/** Send a message via the persistent singleton client. */
export async function openClawSend(
  provider: string,
  sessionKey: string,
  text: string,
): Promise<void> {
  const client = _getClient();
  if (!client) {
    throw new Error(GATEWAY_OFFLINE_MESSAGE);
  }
  _pendingProvider = provider;
  await client.sendMessage(sessionKey, text);
}

/** Subscribe to WebSocket connection status changes. Returns unsubscribe fn. */
export function subscribeToClaudeStatus(fn: StatusListener): () => void {
  // Ensure client is created so it connects on first subscribe
  _getClient();
  _statusListeners.add(fn);
  fn(_currentStatus); // deliver current status immediately
  return () => _statusListeners.delete(fn);
}

export function getCurrentClaudeStatus(): ConnectionStatus {
  return _currentStatus;
}

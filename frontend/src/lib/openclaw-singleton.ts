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

const WS_URL =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_OPENCLAW_WS_URL) ||
  "ws://localhost:18789";
const TOKEN =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_OPENCLAW_TOKEN) ||
  "";

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

function _getClient(): OpenClawClient {
  if (_client) return _client;
  _client = new OpenClawClient({
    url: WS_URL,
    token: TOKEN,
    onChatEvent: _handleEvent,
    onStatusChange: _notifyStatus,
  });
  _client.connect();
  return _client;
}

/** Send a message via the persistent singleton client. */
export async function openClawSend(
  provider: string,
  sessionKey: string,
  text: string,
): Promise<void> {
  const client = _getClient();
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
